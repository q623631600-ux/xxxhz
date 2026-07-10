"""
视频合成服务 - 使用 FFmpeg 将图片和配音合成为竖屏视频
"""
import subprocess
from pathlib import Path

from config import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from utils.logger import log


class VideoComposer:
    """图片 + 配音 → 竖屏 MP4"""

    def __init__(self):
        self.width = VIDEO_WIDTH
        self.height = VIDEO_HEIGHT
        self.fps = VIDEO_FPS

    def compose(
        self,
        segments: list[dict],
        output_dir: Path,
        output_name: str = "final.mp4",
        add_transitions: bool = True,
    ) -> Path:
        """
        合成视频

        Args:
            segments: [{image_path, audio_path, duration, ...}]
            output_dir: 输出目录
            output_name: 输出文件名
            add_transitions: 是否添加转场效果

        Returns:
            输出视频路径
        """
        output_path = output_dir / output_name

        log.info(f"正在合成视频（{len(segments)} 段）...")

        if add_transitions and len(segments) > 1:
            return self._compose_with_transitions(segments, output_path)
        else:
            return self._compose_simple(segments, output_path)

    def _compose_simple(self, segments: list[dict], output_path: Path) -> Path:
        """简单拼接（无转场）"""
        # 构建 FFmpeg concat 输入
        inputs = []
        filter_parts = []
        concat_parts = []

        for i, seg in enumerate(segments):
            img_path = seg.get("image_path", "")
            audio_path = seg.get("audio_path", "")
            duration = seg.get("duration", 10)

            if not img_path or not Path(img_path).exists():
                log.warn(f"  第 {i+1} 段缺少图片，使用黑屏")
                # 创建纯色占位
                img_path = self._create_placeholder(i, output_path.parent)

            inputs.extend(["-loop", "1", "-t", str(duration), "-i", str(img_path)])
            if audio_path and Path(audio_path).exists():
                inputs.extend(["-t", str(duration), "-i", str(audio_path)])
            else:
                # 无声轨道
                inputs.extend(["-f", "lavfi", "-t", str(duration), "-i", "anullsrc"])

            # 视频流索引
            vid_idx = i * 2
            # 音频流索引
            aud_idx = i * 2 + 1

            filter_parts.append(
                f"[{vid_idx}:v]scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1[v{i}]"
            )
            concat_parts.append(f"[v{i}][{aud_idx}:a]")

        # 构建完整命令
        filter_complex = (
            ";".join(filter_parts) + ";"
            + "".join(concat_parts)
            + f"concat=n={len(segments)}:v=1:a=1[outv][outa]"
        )

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-r", str(self.fps),
            "-pix_fmt", "yuv420p",
            str(output_path),
        ]

        subprocess.run(cmd, check=True, capture_output=True,
                       creationflags=(subprocess.CREATE_NO_WINDOW
                                      if hasattr(subprocess, "CREATE_NO_WINDOW") else 0))
        log.success(f"视频合成完成: {output_path}")
        return output_path

    def _compose_with_transitions(self, segments: list[dict], output_path: Path) -> Path:
        """带淡入淡出转场的拼接"""
        # FFmpeg xfade 实现平滑转场
        # 先创建每段的独立视频片段，再用 xfade 连接
        temp_dir = output_path.parent / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        segment_videos = []

        for i, seg in enumerate(segments):
            img_path = seg.get("image_path", "")
            audio_path = seg.get("audio_path", "")
            duration = seg.get("duration", 10)

            if not img_path or not Path(img_path).exists():
                img_path = self._create_placeholder(i, output_path.parent)

            seg_video = temp_dir / f"seg_{i:02d}.mp4"
            segment_videos.append(seg_video)

            if seg_video.exists():
                continue

            # 为每张图创建一个带淡入淡出的视频片段
            fade_frames = min(12, int(duration * self.fps / 4))  # 淡入淡出帧数

            vf = (
                f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
                f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
                f"fade=t=in:st=0:d={fade_frames / self.fps},"
                f"fade=t=out:st={duration - fade_frames / self.fps}:d={fade_frames / self.fps},"
                f"setsar=1"
            )

            inputs = ["-loop", "1", "-t", str(duration), "-i", str(img_path)]
            if audio_path and Path(audio_path).exists():
                inputs.extend(["-t", str(duration), "-i", str(audio_path)])
                cmd = [
                    "ffmpeg", "-y",
                    *inputs,
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-c:a", "aac", "-b:a", "128k",
                    "-r", str(self.fps),
                    "-shortest",
                    str(seg_video),
                ]
            else:
                cmd = [
                    "ffmpeg", "-y",
                    *inputs,
                    "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-r", str(self.fps),
                    "-shortest",
                    str(seg_video),
                ]

            subprocess.run(cmd, check=True, capture_output=True,
                           creationflags=(subprocess.CREATE_NO_WINDOW
                                          if hasattr(subprocess, "CREATE_NO_WINDOW") else 0))

        # 用 concat demuxer 拼接所有片段
        concat_file = temp_dir / "concat.txt"
        concat_file.write_text(
            "\n".join(f"file '{v}'" for v in segment_videos),
            encoding="utf-8",
        )

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(output_path),
            ],
            check=True, capture_output=True,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
        )

        # 清理临时文件
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

        log.success(f"视频合成完成: {output_path}")
        return output_path

    def _create_placeholder(self, index: int, output_dir: Path) -> str:
        """创建占位图片"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            # 如果 PIL 不可用，返回空字符串（调用方会处理）
            return ""

        img = Image.new("RGB", (self.width, self.height), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        text = f"第 {index+1} 段"
        # 简单居中绘制
        bbox = draw.textbbox((0, 0), text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.text(
            ((self.width - text_w) / 2, (self.height - text_h) / 2),
            text, fill=(200, 200, 200),
        )
        placeholder_path = output_dir / f"_placeholder_{index:02d}.png"
        img.save(str(placeholder_path))
        return str(placeholder_path)
