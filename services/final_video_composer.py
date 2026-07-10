"""
最终视频合成服务 — 图片 + 音频 + 字幕 + 标题 → 最终 MP4

输入: timeline.json + images/ + audio/seg_*.mp3 + subtitles.srt + title_overlays.json
输出: final.mp4

FFmpeg 合成流程:
  1. 每 beat 创建视频片段（图片 + 对应音频）
  2. 片段间淡入淡出转场 (xfade)
  3. 拼接所有片段
  4. 烧录字幕 (subtitles filter)
  5. 叠加标题 (drawtext filter)
"""
import json
import shutil
import subprocess
from pathlib import Path

from config import (
    VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS,
    VIDEO_TRANSITION_DURATION,
    SUBTITLE_FONT_PATH, SUBTITLE_FONT_SIZE,
    TITLE_FONT_SIZE, TITLE_POSITION_Y,
    SUBTITLE_MARGIN_V,
)
from utils.logger import log


class FinalVideoComposer:
    """合成最终带字幕的 MP4 视频"""

    def __init__(self):
        self.width = VIDEO_WIDTH
        self.height = VIDEO_HEIGHT
        self.fps = VIDEO_FPS
        self.transition = VIDEO_TRANSITION_DURATION
        self.temp_dir = None

    # ================================================================
    # 主入口
    # ================================================================

    def compose(self, kp_dir: Path, image_source: Path = None) -> Path:
        """
        合成最终视频。

        Args:
            kp_dir: 知识点目录
            image_source: 图片目录（默认 kp_dir/images/）

        Returns:
            最终视频路径
        """
        # 进度文件
        self._progress_path = kp_dir / "compose_progress.json"
        self._update_progress("init", 0, 0, "准备中...")

        # 路径准备
        images_dir = image_source or (kp_dir / "images")
        timeline_path = kp_dir / "timeline.json"
        srt_path = kp_dir / "subtitles.srt"
        title_path = kp_dir / "title_overlays.json"
        audio_dir = kp_dir / "audio"
        output_path = kp_dir / "final.mp4"
        self.temp_dir = kp_dir / "temp_video"
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # 验证输入
        if not timeline_path.exists():
            raise FileNotFoundError(f"未找到 timeline.json: {timeline_path}")
        if not srt_path.exists():
            raise FileNotFoundError(f"未找到 subtitles.srt，请先生成字幕")
        if not images_dir.exists():
            raise FileNotFoundError(f"图片目录不存在: {images_dir}")

        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        beats = timeline.get("timeline", [])
        if not beats:
            raise ValueError("timeline.json 中无数据")

        # 检查书级别封面图（用于钩子文字叠加，不单独插入 beat，避免画面与音频错位）
        book_dir = kp_dir.parent
        book_cover_path = book_dir / "cover.png"
        has_cover = book_cover_path.exists()

        # 生成钩子文字叠加图（双语 + 黄色强调）
        hook_overlay_path = None
        if has_cover:
            hook_overlay_path = self._create_hook_overlay(kp_dir)
            log.info(f"  使用书籍封面: {book_cover_path}")

        log.info(f"开始合成视频: {len(beats)} 个画面, {self.width}x{self.height}")
        total_beats = len(beats)

        # === 阶段1: 为每个 beat 创建视频片段 ===
        self._update_progress("segments", 1, 5, f"创建画面片段 (0/{total_beats})...")
        seg_videos = self._create_segment_videos(beats, images_dir, audio_dir, total_beats, hook_overlay_path)

        # === 阶段2: 拼接片段（带转场） ===
        self._update_progress("xfade", 2, 5, "拼接转场中...")
        if len(seg_videos) == 1:
            merged = seg_videos[0]
        else:
            merged = self._concat_with_transitions(seg_videos, beats)

        # === 阶段3: 混合音频 ===
        self._update_progress("audio", 3, 5, "混合音频轨道...")
        video_with_audio = self._mix_full_audio(merged, audio_dir)

        # === 阶段4: 烧录字幕 ===
        self._update_progress("subtitle", 4, 5, "烧录字幕...")
        video_with_subs = self._burn_subtitles(video_with_audio, srt_path)

        # === 阶段5: 完成 ===
        self._update_progress("finish", 5, 5, "完成!")
        final = video_with_subs

        # 复制到最终输出路径
        if final != output_path:
            shutil.copy2(final, output_path)

        # 清理临时文件
        shutil.rmtree(self.temp_dir, ignore_errors=True)

        # 输出信息
        total_duration = timeline.get("total_duration_seconds", 0)
        log.success(f"视频合成完成: {output_path} "
                     f"({self._fmt_time(total_duration)})")
        return output_path

    # ================================================================
    # 阶段1: 创建片段视频（图片 + 该 beat 对应的音频切片）
    # ================================================================

    def _create_hook_overlay(self, kp_dir: Path) -> Path | None:
        """生成钩子文字叠加图：16:9纯黑背景、居中、双语、关键句黄色强调

        参考 new_hook_preview.png 排版：
          - 上方中文块：第1句(格式A问题/格式B每天十分钟)全黄色，后续句子白色
          - 下方英文块：[Book Insight] 黄色 + 知识点名 白色
          - 两块整体垂直居中，块间距约 80px
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            log.warn("Pillow 未安装，跳过钩子文字叠加")
            return None

        # 读取脚本
        script = None
        for name in ["script_edited.json", "script_safe.json", "script.json"]:
            sp = kp_dir / name
            if sp.exists():
                script = json.loads(sp.read_text(encoding="utf-8"))
                break
        if not script:
            return None

        full_script = script.get("full_script", "")
        if not full_script:
            return None

        first_para = full_script.split("\n\n")[0].strip()
        if not first_para:
            return None

        # 字体
        font_paths = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]

        img_w, img_h = self.width, self.height  # 1920x1080 (16:9)
        overlay = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 255))
        draw = ImageDraw.Draw(overlay)

        # ---- 拆分中文：第1句(黄色) + 后续(白色)，整体分行 ----
        cn_lines, yellow_spans = self._split_hook_lines(first_para)

        # 字号：16:9 横屏，行少字大，同时确保不超出画面
        margin_x = 120
        max_text_w = img_w - 2 * margin_x
        cn_sizes = [88, 72, 60, 48, 40, 36]
        cn_size = cn_sizes[0]
        cn_font = None
        for sz in cn_sizes:
            font = self._load_font(font_paths, sz)
            # 检查最长行是否超出
            max_line_w = max((draw.textbbox((0, 0), line, font=font)[2] for line in cn_lines), default=0)
            if max_line_w <= max_text_w:
                cn_size = sz
                cn_font = font
                break
        if cn_font is None:
            cn_font = self._load_font(font_paths, 36)
            cn_size = 36
        en_size = max(24, cn_size * 2 // 5)  # ~40% of CN size
        en_font = self._load_font(font_paths, en_size)

        # ---- 计算中文块尺寸 ----
        cn_line_h = draw.textbbox((0, 0), "Ag", font=cn_font)[3] - draw.textbbox((0, 0), "Ag", font=cn_font)[1]
        cn_gap = int(cn_size * 0.35)
        cn_block_h = len(cn_lines) * cn_line_h + (len(cn_lines) - 1) * cn_gap

        # ---- 英文块 ----
        en_line_h = draw.textbbox((0, 0), "Ag", font=en_font)[3] - draw.textbbox((0, 0), "Ag", font=en_font)[1]
        en_gap = int(en_size * 0.35)
        en_lines = self._get_en_hook_lines(first_para, script)
        en_block_h = len(en_lines) * en_line_h + (len(en_lines) - 1) * en_gap if en_lines else 0

        # ---- 垂直居中：中文块 + 间距 + 英文块 ----
        cn_en_gap = 80 if en_lines else 0  # 中英文块间距
        total_h = cn_block_h + cn_en_gap + en_block_h
        start_y = (img_h - total_h) // 2

        # ---- 绘制中文行 ----
        y = start_y
        for li, line in enumerate(cn_lines):
            spans = yellow_spans.get(li, [])
            self._draw_mixed_line(draw, line, spans, cn_font, cn_size, y, img_w)
            y += cn_line_h + cn_gap

        # ---- 绘制英文行 ----
        if en_lines:
            y += cn_en_gap - cn_gap  # 调整已累加的最后一次 gap
            for li, line in enumerate(en_lines):
                # 第1行英文黄色，第2行英文白色（与参考图一致）
                color = (255, 215, 0, 255) if li == 0 else (255, 255, 255, 255)
                tw = draw.textbbox((0, 0), line, font=en_font)[2]
                x = (img_w - tw) // 2
                # 微弱的阴影增加质感
                draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 180), font=en_font)
                draw.text((x, y), line, fill=color, font=en_font)
                y += en_line_h + en_gap

        overlay_path = self.temp_dir / "hook_overlay.png"
        overlay.save(str(overlay_path), "PNG")
        log.info(f"  钩子文字叠加图已生成 (16:9, {len(cn_lines)}行CN + {len(en_lines)}行EN): {overlay_path}")
        return overlay_path

    def _split_hook_lines(self, text: str) -> tuple:
        """将钩子文字拆分为行，第1句(格式A问题/格式B每天十分钟)全黄色独占首行

        返回: (行列表, {行号: [(start, end, is_yellow), ...]})
        """
        # 按句末标点拆句子
        sentences = []
        buf = ""
        for ch in text:
            buf += ch
            if ch in "。！？":
                sentences.append(buf)
                buf = ""
        if buf:
            sentences.append(buf)

        if not sentences:
            return [text], {0: [(0, len(text), True)]}

        first_sentence = sentences[0]
        rest_text = "".join(sentences[1:])

        # 第1句独占首行（黄色）
        if not rest_text:
            # 只有一句话：短句不拆分，长句对半拆
            if len(first_sentence) <= 25:
                return [first_sentence], {0: [(0, len(first_sentence), True)]}
            mid = len(first_sentence) // 2
            return [first_sentence[:mid], first_sentence[mid:]], {0: [(0, mid, True)], 1: [(0, len(first_sentence)-mid, True)]}

        lines = [first_sentence]  # 第1行=黄色句

        # 剩余文字按长度分1-2行（白色）
        if len(rest_text) <= 50:
            lines.append(rest_text)
        else:
            # 按标点拆分剩余文字
            parts = []
            buf = ""
            for ch in rest_text:
                buf += ch
                if ch in "。！？；，":
                    parts.append(buf)
                    buf = ""
            if buf:
                parts.append(buf)

            target = len(rest_text) / 2
            line2 = ""
            line2_len = 0
            remaining = []
            for p in parts:
                if not line2 or line2_len + len(p) <= target * 1.25:
                    line2 += p
                    line2_len += len(p)
                else:
                    remaining.append(p)
            line3 = "".join(remaining)

            if line2:
                lines.append(line2)
            if line3:
                lines.append(line3)

        # 标记黄色：仅第1行全黄
        yellow_spans = {0: [(0, len(first_sentence), True)]}
        for li in range(1, len(lines)):
            yellow_spans[li] = []

        return lines, yellow_spans

    def _draw_mixed_line(self, draw, line: str, yellow_spans: list, font, font_size: int, y: int, img_w: int):
        """绘制一行文字，支持指定位置用黄色，其余白色"""
        if not yellow_spans:
            # 全白
            tw = draw.textbbox((0, 0), line, font=font)[2]
            x = (img_w - tw) // 2
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 200), font=font)
            draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)
            return

        # 有黄色区间：逐段绘制
        # 先计算整行宽度用于居中
        total_w = draw.textbbox((0, 0), line, font=font)[2]
        start_x = (img_w - total_w) // 2

        spans = sorted(yellow_spans, key=lambda s: s[0])
        # 构建段落: [(text, is_yellow), ...]
        segments = []
        pos = 0
        for s_start, s_end, _ in spans:
            if pos < s_start:
                segments.append((line[pos:s_start], False))
            segments.append((line[s_start:s_end], True))
            pos = s_end
        if pos < len(line):
            segments.append((line[pos:], False))

        x = start_x
        for seg_text, is_yellow in segments:
            if not seg_text:
                continue
            color = (255, 215, 0, 255) if is_yellow else (255, 255, 255, 255)
            draw.text((x + 2, y + 2), seg_text, fill=(0, 0, 0, 200), font=font)
            draw.text((x, y), seg_text, fill=color, font=font)
            x += draw.textbbox((0, 0), seg_text, font=font)[2]

    def _get_en_hook_lines(self, cn_text: str, script: dict) -> list[str]:
        """获取英文行（知识点标题，黄色）"""
        kp = script.get("knowledge_point", "")
        if not kp:
            return []
        return [kp]

    def _load_font(self, font_paths: list, size: int):
        """加载字体"""
        from PIL import ImageFont
        for fp in font_paths:
            if Path(fp).exists():
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _create_segment_videos(
        self, beats: list[dict], images_dir: Path, audio_dir: Path,
        total_beats: int = 0, hook_overlay: Path = None
    ) -> list[Path]:
        """为每个 beat 创建一个带音频的视频片段"""
        seg_videos = []
        image_found = 0
        image_missing = 0
        total = total_beats or len(beats)

        for i, beat in enumerate(beats):
            bid = beat["beat"]
            duration = beat.get("duration_seconds", 5)

            # 更新进度
            self._update_progress("segments", 1, 5,
                                  f"创建画面片段 ({i+1}/{total})...",
                                  current=i+1, total=total)

            # 用 start_seconds/end_seconds 计算精确帧数，避免浮点取整累积误差
            start_sec = beat.get("start_seconds", 0)
            end_sec = beat.get("end_seconds", start_sec + duration)
            start_frame = round(start_sec * self.fps)
            end_frame = round(end_sec * self.fps)
            exact_frames = end_frame - start_frame
            if exact_frames < 1:
                exact_frames = 1

            # 封面 beat（beat_id=0）：直接使用指定图片
            cover_img = beat.get("_use_image", "")
            if cover_img:
                img_path = Path(cover_img)
                image_found += 1
            else:
                # 找到对应图片
                img_path = self._find_image(bid, images_dir)
                if img_path:
                    image_found += 1
                else:
                    image_missing += 1
                    img_path = self._create_placeholder(bid)

            seg_path = self.temp_dir / f"seg_{bid:03d}.mp4"

            if seg_path.exists() and self._is_valid_video(seg_path):
                pass  # 已有有效片段，跳过
            else:
                if seg_path.exists():
                    seg_path.unlink()  # 删除损坏文件
                self._make_image_video_exact(img_path, exact_frames, seg_path)

            # 封面 beat：叠加钩子文字
            if cover_img and hook_overlay and hook_overlay.exists():
                seg_path = self._overlay_hook_on_segment(seg_path, hook_overlay, exact_frames / self.fps)

            seg_videos.append(seg_path)

        log.info(f"  图片: {image_found} 张就绪, {image_missing} 张占位")
        return seg_videos

    def _find_image(self, beat_id: int, images_dir: Path) -> Path | None:
        """查找 beat 对应的图片文件（支持多种命名格式）"""
        # 尝试多种命名格式
        candidates = [
            images_dir / f"beat_{beat_id:03d}.png",
            images_dir / f"beat_{beat_id:03d}.jpg",
            images_dir / f"beat_{beat_id:03d}.jpeg",
            images_dir / f"beat_{beat_id:02d}.png",
            images_dir / f"beat_{beat_id:02d}.jpg",
            images_dir / f"beat_{beat_id:02d}.jpeg",
            images_dir / f"beat_{beat_id}.png",
            images_dir / f"beat_{beat_id}.jpg",
            images_dir / f"beat_{beat_id}.jpeg",
            images_dir / f"{beat_id - 1}.jpeg",   # 分镜图: 0.jpeg → beat 1
            images_dir / f"{beat_id - 1}.jpg",
            images_dir / f"{beat_id - 1}.png",
            images_dir / f"{beat_id}.jpeg",
            images_dir / f"{beat_id}.jpg",
            images_dir / f"{beat_id}.png",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def _create_placeholder(self, beat_id: int) -> Path:
        """创建占位图片"""
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            # 返回一个简单的黑色图片路径
            black = self.temp_dir / f"_placeholder_{beat_id:03d}.png"
            if not black.exists():
                # 用 FFmpeg 生成纯色图
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"color=c=0x1E1E28:s={self.width}x{self.height}:d=1",
                    "-frames:v", "1", str(black),
                ], capture_output=True,
                   creationflags=(subprocess.CREATE_NO_WINDOW
                                  if hasattr(subprocess, "CREATE_NO_WINDOW") else 0))
            return black

        img = Image.new("RGB", (self.width, self.height), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)
        text = f"Beat {beat_id}"
        bbox = draw.textbbox((0, 0), text)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((self.width - tw) / 2, (self.height - th) / 2),
                  text, fill=(180, 180, 180))
        placeholder = self.temp_dir / f"_placeholder_{beat_id:03d}.png"
        img.save(str(placeholder))
        return placeholder

    def _make_image_video_exact(self, img_path: Path, total_frames: int, output: Path):
        """图片 → 视频片段（精确帧数，零累积误差）"""
        sf = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(img_path),
            "-vf", f"{sf},fps={self.fps}",
            "-vframes", str(total_frames),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output),
        ]
        for attempt in range(2):
            self._run_ffmpeg(cmd, f"创建片段 Beat")
            if self._is_valid_video(output):
                return
            if attempt == 0:
                log.warn(f"  片段损坏，重试中...")
                output.unlink(missing_ok=True)
        raise RuntimeError(f"片段生成失败（重试后仍损坏）: {output}")

    def _make_image_video(self, img_path: Path, duration: float, output: Path):
        """图片 → 视频片段，自动校验防损坏"""
        # 保持原图比例缩放，不够的地方加黑边，不拉伸不裁剪
        scale_filter = (
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )

        # 用精确帧数，避免浮点取整累积误差导致图声错位
        total_frames = round(duration * self.fps)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(img_path),
            "-vf", f"{scale_filter},fps={self.fps}",
            "-vframes", str(total_frames),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(output),
        ]

        # 带重试：如果输出损坏，重试一次
        for attempt in range(2):
            self._run_ffmpeg(cmd, f"创建片段 Beat")
            if self._is_valid_video(output):
                return
            if attempt == 0:
                log.warn(f"  片段损坏，重试中...")
                output.unlink(missing_ok=True)

        raise RuntimeError(f"片段生成失败（重试后仍损坏）: {output}")

    def _overlay_hook_on_segment(self, seg_path: Path, overlay_path: Path, duration: float) -> Path:
        """将钩子文字叠加图合成到封面视频片段上"""
        output = self.temp_dir / f"{seg_path.stem}_with_hook.mp4"

        # overlay 滤镜：将半透明 PNG 叠到底层视频上，位置居中
        vf = (
            f"[0:v][1:v]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2:"
            f"enable='between(t,0,{duration})'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(seg_path),
            "-i", str(overlay_path),
            "-filter_complex", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-r", str(self.fps),
            "-pix_fmt", "yuv420p",
            "-an",
            str(output),
        ]
        self._run_ffmpeg(cmd, "叠加钩子文字")

        return output

    def _is_valid_video(self, path: Path) -> bool:
        """用 ffprobe 校验视频文件是否完整"""
        if not path.exists() or path.stat().st_size < 1000:
            return False
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
                capture_output=True, timeout=30,
                encoding="utf-8", errors="replace",
                creationflags=(subprocess.CREATE_NO_WINDOW
                               if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
            )
            return result.returncode == 0 and len(result.stdout.strip()) > 0
        except Exception:
            return False

    # ================================================================
    # 阶段2: 拼接片段（xfade 转场）
    # ================================================================

    def _concat_with_transitions(
        self, seg_videos: list[Path], beats: list[dict]
    ) -> Path:
        """拼接所有片段（concat demuxer，精确对齐，无时间偏移）"""
        if len(seg_videos) <= 1:
            return seg_videos[0] if seg_videos else None

        output = self.temp_dir / "merged_video.mp4"

        # 用 concat demuxer，每个片段首尾对齐，无 xfade 时间偏移
        concat_file = self.temp_dir / "concat_list.txt"
        lines = [f"file '{v.absolute().as_posix()}'" for v in seg_videos]
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-r", str(self.fps),
            "-pix_fmt", "yuv420p",
            "-an",
            str(output),
        ]
        self._run_ffmpeg(cmd, "concat 拼接")

        return output

    # ================================================================
    # 阶段3: 混合音频
    # ================================================================

    def _mix_full_audio(self, video_path: Path, audio_dir: Path) -> Path:
        """将完整音频轨道混合到视频中"""
        output = self.temp_dir / "video_with_audio.mp4"

        # 拼接所有音频段
        full_audio = self._concat_audio_segments(audio_dir)

        if full_audio is None:
            log.warn("未找到音频文件，生成静音视频")
            # 获取视频时长并生成静音
            duration = self._get_video_duration(video_path)
            silent = self.temp_dir / "silent.aac"
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", str(duration),
                "-c:a", "aac", "-b:a", "128k",
                str(silent),
            ], capture_output=True,
               creationflags=(subprocess.CREATE_NO_WINDOW
                              if hasattr(subprocess, "CREATE_NO_WINDOW") else 0))
            full_audio = silent

        # 获取音频时长，确保视频不短于音频
        audio_dur = self._get_video_duration(full_audio)
        video_dur = self._get_video_duration(video_path)
        duration_diff = audio_dur - video_dur

        if duration_diff > 0.5:
            # 视频比音频短（xfade 转场吞掉的时间），pad 最后一个画面补足
            log.info(f"  视频{self._fmt_time(video_dur)} < 音频{self._fmt_time(audio_dur)}，补齐尾部{duration_diff:.1f}s")
            padded_video = self.temp_dir / "video_padded.mp4"
            pad_cmd = [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-vf", f"tpad=stop_mode=clone:stop_duration={duration_diff:.2f}",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an",
                str(padded_video),
            ]
            self._run_ffmpeg(pad_cmd, "pad视频")
            video_path = padded_video

        # 重新测量 pad 后的视频时长，确保 >= 音频
        padded_dur = self._get_video_duration(video_path)
        # 不用 -shortest！用 -t 显式指定输出时长 = 音频时长，防止视频流时间戳偏差导致提前截断
        output_dur = min(padded_dur, audio_dur)
        log.info(f"  混合: 视频{self._fmt_time(padded_dur)} + 音频{self._fmt_time(audio_dur)} → 输出{self._fmt_time(output_dur)}")

        cmd = [
            "ffmpeg", "-y",
            "-fflags", "+genpts",
            "-i", str(video_path),
            "-i", str(full_audio),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{output_dur:.6f}",
            str(output),
        ]
        self._run_ffmpeg(cmd, "混合音频")

        return output

    def _concat_audio_segments(self, audio_dir: Path) -> Path | None:
        """拼接所有音频段为完整音频"""
        audio_files = sorted(audio_dir.glob("seg_*.mp3"))
        if not audio_files:
            return None

        if len(audio_files) == 1:
            return audio_files[0]

        concat_file = self.temp_dir / "audio_concat.txt"
        lines = [f"file '{p.absolute().as_posix()}'" for p in audio_files]
        concat_file.write_text("\n".join(lines), encoding="utf-8")

        output = self.temp_dir / "full_audio.mp3"
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-c:a", "libmp3lame", "-b:a", "128k",
            str(output),
        ]
        self._run_ffmpeg(cmd, "拼接音频")

        return output

    # ================================================================
    # 阶段4: 烧录字幕
    # ================================================================

    def _burn_subtitles(self, video_path: Path, srt_path: Path) -> Path:
        """将 SRT 字幕烧录到视频中"""
        output = self.temp_dir / "video_with_subs.mp4"

        # 字体路径处理（FFmpeg 需要绝对路径，Windows 下转义冒号）
        font_path = Path(SUBTITLE_FONT_PATH)
        if not font_path.exists():
            # 尝试常见的备选字体
            fallbacks = [
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/simsun.ttc",
            ]
            for fb in fallbacks:
                if Path(fb).exists():
                    font_path = Path(fb)
                    break
            else:
                raise FileNotFoundError(
                    f"未找到中文字体: {SUBTITLE_FONT_PATH}，"
                    f"请安装微软雅黑或设置 SUBTITLE_FONT_PATH"
                )

        font_path_str = font_path.absolute().as_posix()

        # FFmpeg subtitles force_style 参数
        style = (
            f"FontName=Microsoft YaHei,"
            f"FontSize={SUBTITLE_FONT_SIZE},"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"BorderStyle=1,"
            f"Outline=2,"
            f"Shadow=2,"
            f"Alignment=2,"
            f"MarginV={SUBTITLE_MARGIN_V}"
        )

        srt_abs = srt_path.absolute().as_posix()
        srt_escaped = srt_abs.replace(":", "\\:").replace("'", "\\'")

        # 使用 subtitles 滤镜时，需要设置 fontsdir 或嵌入字体路径
        # Windows 下直接用绝对路径
        vf = f"subtitles='{srt_escaped}':force_style='{style}'"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            str(output),
        ]
        self._run_ffmpeg(cmd, "烧录字幕")

        return output

    # ================================================================
    # 阶段5: 叠加标题 (ASS 格式)
    # ================================================================

    def _add_title_overlays(self, video_path: Path, title_path: Path) -> Path:
        """用 ASS 格式在视频上叠加标题（更可靠，避免 drawtext 转义问题）"""
        output = self.temp_dir / "video_final.mp4"

        overlays_data = json.loads(title_path.read_text(encoding="utf-8"))
        overlays = overlays_data.get("overlays", [])
        if not overlays:
            log.warn("title_overlays.json 中无叠加数据，跳过标题")
            return video_path

        # 去重：合并相同文本的标题段
        merged = self._merge_overlays(overlays)

        # 生成 ASS 字幕文件用于标题
        ass_path = self.temp_dir / "titles.ass"
        self._generate_title_ass(merged, ass_path)

        log.info(f"  叠加 {len(merged)} 个标题（已去重合并）")

        # 用 ass 滤镜叠加标题
        ass_escaped = ass_path.absolute().as_posix().replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"ass='{ass_escaped}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            str(output),
        ]
        self._run_ffmpeg(cmd, "叠加标题(ASS)")

        return output

    def _merge_overlays(self, overlays: list[dict]) -> list[dict]:
        """合并相邻且文本相同的标题"""
        if not overlays:
            return []

        merged = []
        current = dict(overlays[0])

        for ov in overlays[1:]:
            if ov.get("text") == current.get("text"):
                # 相同文本，扩展结束时间
                current["end_seconds"] = max(current["end_seconds"], ov.get("end_seconds", 0))
            else:
                # 清理短标题后保存
                if self._is_valid_title(current):
                    merged.append(current)
                current = dict(ov)

        if self._is_valid_title(current):
            merged.append(current)

        return merged

    def _is_valid_title(self, ov: dict) -> bool:
        """检查标题是否值得显示"""
        text = ov.get("text", "").strip()
        if not text:
            return False
        duration = ov.get("end_seconds", 0) - ov.get("start_seconds", 0)
        if duration < 2.0:
            return False
        if len(text) < 4:
            return False
        return True

    def _generate_title_ass(self, overlays: list[dict], output_path: Path):
        """生成 ASS 格式标题字幕文件"""
        lines = []
        lines.append("[Script Info]")
        lines.append("ScriptType: v4.00+")
        lines.append("PlayResX: 1080")
        lines.append("PlayResY: 1920")
        lines.append("WrapStyle: 2")
        lines.append("")
        lines.append("[V4+ Styles]")
        lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
                      "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
                      "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                      "Alignment, MarginL, MarginR, MarginV, Encoding")
        # Alignment=8: 顶部居中
        lines.append("Style: Title,Microsoft YaHei,36,&H00FFFFFF,&H000000FF,"
                      "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,2,"
                      "8,10,10,150,1")
        lines.append("")
        lines.append("[Events]")
        lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
                      "MarginV, Effect, Text")

        for ov in overlays:
            start = self._fmt_ass_time(ov.get("start_seconds", 0))
            end = self._fmt_ass_time(ov.get("end_seconds", 0))
            text = ov.get("text", "").strip()
            if not text:
                continue
            lines.append(f"Dialogue: 0,{start},{end},Title,,0,0,0,,{text}")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        log.info(f"  标题 ASS 已生成: {output_path}")

    def _fmt_ass_time(self, seconds: float) -> str:
        """秒 → ASS 时间格式 H:MM:SS.cc"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int((seconds - int(seconds)) * 100)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    # ================================================================
    # 进度追踪
    # ================================================================

    def _update_progress(self, stage: str, step: int, total_steps: int,
                         message: str, current: int = 0, total: int = 0):
        """写入进度文件供前端轮询"""
        if not hasattr(self, '_progress_path') or not self._progress_path:
            return
        try:
            data = {
                "stage": stage,
                "step": step,
                "total_steps": total_steps,
                "message": message,
                "current": current,
                "total": total,
                "percent": round(step / total_steps * 100) if total_steps else 0,
            }
            self._progress_path.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ================================================================
    # 工具方法
    # ================================================================

    def _shift_srt_times(self, srt_path: Path, offset: float) -> Path:
        """将 SRT 字幕的所有时间戳向后偏移 offset 秒（用于封面延迟）"""
        import re
        content = srt_path.read_text(encoding="utf-8")
        shifted_path = self.temp_dir / "subtitles_shifted.srt"

        def shift_line(match):
            h1, m1, s1, ms1 = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
            h2, m2, s2, ms2 = int(match.group(5)), int(match.group(6)), int(match.group(7)), int(match.group(8))
            t1 = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0 + offset
            t2 = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0 + offset
            t1, t2 = max(0, t1), max(0, t2)
            return (f"{int(t1 // 3600):02d}:{int((t1 % 3600) // 60):02d}:{int(t1 % 60):02d},{int((t1 - int(t1)) * 1000):03d}"
                    f" --> "
                    f"{int(t2 // 3600):02d}:{int((t2 % 3600) // 60):02d}:{int(t2 % 60):02d},{int((t2 - int(t2)) * 1000):03d}")

        shifted_content = re.sub(
            r'(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})',
            shift_line, content,
        )
        shifted_path.write_text(shifted_content, encoding="utf-8")
        log.info(f"  字幕时间已偏移 +{offset}秒（封面延迟）")
        return shifted_path

    # ================================================================

    def _get_video_duration(self, video_path: Path) -> float:
        """获取视频时长"""
        result = subprocess.run(
            ["ffprobe", "-v", "quiet",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(video_path)],
            capture_output=True, text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
        )
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 60.0  # 默认60秒

    def _run_ffmpeg(self, cmd: list[str], step_name: str = "FFmpeg"):
        """运行 FFmpeg 命令并处理错误"""
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=600,
                encoding="utf-8", errors="replace",
                creationflags=(subprocess.CREATE_NO_WINDOW
                               if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
            )
            if result.returncode != 0:
                stderr_tail = result.stderr[-800:] if result.stderr else "(无输出)"
                raise RuntimeError(f"FFmpeg 错误 ({step_name}):\n{stderr_tail}")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"FFmpeg 超时 ({step_name})")

    def _fmt_time(self, seconds: float) -> str:
        """秒 → 分:秒"""
        m, s = divmod(int(seconds), 60)
        return f"{m}分{s}秒"
