"""
配音服务 - 使用 Edge-TTS 将文本转为语音
"""
import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts

from config import TTS_VOICE
from utils.logger import log


class TTSGenerator:
    """文字 → 配音 MP3（Edge-TTS，免费）"""

    VOICE_OPTIONS = {
        "xiaoxiao": "zh-CN-XiaoxiaoNeural",   # 女声，活泼
        "yunxi": "zh-CN-YunxiNeural",         # 男声，年轻
        "xiaoyi": "zh-CN-XiaoyiNeural",       # 女声，温柔
        "yunjian": "zh-CN-YunjianNeural",     # 男声，稳重
    }

    def __init__(self, voice: str = "", rate: str = "-10%"):
        self.voice = voice or TTS_VOICE
        self.rate = rate

    def _get_duration(self, audio_path: Path) -> float:
        """用 FFprobe 获取音频时长（秒）"""
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True, text=True,
            creationflags=(subprocess.CREATE_NO_WINDOW
                           if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
        )
        return float(result.stdout.strip())

    async def _generate_audio(self, text: str, output_path: Path):
        """调用 edge-tts Python API 生成单个音频文件"""
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        await communicate.save(str(output_path))

    async def generate(self, segments: list[dict], output_dir: Path) -> list[dict]:
        """
        为每段脚本生成配音

        Args:
            segments: [{index, text, ...}]
            output_dir: 输出目录

        Returns:
            segments 列表（添加了 audio_path 和 duration 字段）
        """
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"正在生成配音（{len(segments)} 段）...")

        timing_data = []

        for i, seg in enumerate(segments):
            seg_num = seg.get("index", i + 1)
            text = seg["text"].strip()
            audio_path = audio_dir / f"seg_{seg_num:02d}.mp3"

            if audio_path.exists():
                log.info(f"  [{seg_num}/{len(segments)}] 跳过（已存在）")
            else:
                log.info(f"  [{seg_num}/{len(segments)}] 生成配音: {text[:30]}...")
                await self._generate_audio(text, audio_path)

            duration = self._get_duration(audio_path)

            seg["audio_path"] = str(audio_path)
            seg["duration"] = round(duration, 2)
            timing_data.append({
                "index": seg_num,
                "duration": round(duration, 2),
                "text_preview": text[:40],
                "text": text,  # 完整文本，供字幕生成精确对齐
            })

        # 保存时间线
        timing_path = output_dir / "timing.json"
        timing_path.write_text(
            json.dumps(timing_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        total_seconds = sum(t["duration"] for t in timing_data)
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        log.success(f"配音生成完成，总时长: {minutes}分{seconds}秒")

        return segments
