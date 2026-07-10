"""
MiniMax TTS — 目前中文最自然的语音合成
注册: https://platform.minimax.chat
文档: https://www.minimax.io/api-document
"""
import json
import time
import asyncio
import subprocess
from pathlib import Path
import aiohttp

from utils.logger import log


class MinimaxTTS:
    """MiniMax 语音合成"""

    # 音色推荐（读书/知识类视频）
    VOICES = {
        "audiobook_male":   "audiobook_male_1",    # 有声书男声（推荐）
        "audiobook_female": "audiobook_female_1",  # 有声书女声
        "presenter_male":   "presenter_male",      # 主持人男声
        "presenter_female": "presenter_female",    # 主持人女声
        "calm_male":        "male-qn-qingse",      # 温和男声
    }

    API_URL = "https://api.minimax.chat/v1/t2a_v2"

    def __init__(self, api_key: str, voice: str = "audiobook_male"):
        self.api_key = api_key
        self.voice_id = self.VOICES.get(voice, "audiobook_male_1")

    async def generate_text(self, text: str, output_path: Path):
        """合成单段文字"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "speech-01",
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": self.voice_id,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.API_URL, json=payload, headers=headers) as resp:
                data = await resp.json()

                if resp.status != 200:
                    raise RuntimeError(f"MiniMax API 返回 {resp.status}: {json.dumps(data, ensure_ascii=False)[:300]}")

                base_resp = data.get("base_resp", {})
                status_code = base_resp.get("status_code", -1)

                if status_code == 0:
                    # 成功：音频在 data.audio 中，hex 编码
                    audio_hex = data.get("data", {}).get("audio", "")
                    if audio_hex:
                        output_path.write_bytes(bytes.fromhex(audio_hex))
                        return True

                msg = base_resp.get("status_msg", "未知错误")
                raise RuntimeError(f"MiniMax TTS 失败: {msg}")

    async def generate(self, segments: list[dict], output_dir: Path) -> list[dict]:
        """批量合成"""
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"MiniMax TTS 配音中（{len(segments)} 段）...")

        for i, seg in enumerate(segments):
            text = seg.get("text", "").strip()
            if not text:
                continue

            seg_num = seg.get("index", i + 1)
            audio_path = audio_dir / f"seg_{seg_num:02d}.mp3"

            if audio_path.exists():
                log.info(f"  [{seg_num}/{len(segments)}] 跳过")
            else:
                log.info(f"  [{seg_num}/{len(segments)}] 合成: {text[:30]}...")
                await self.generate_text(text, audio_path)

            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                    capture_output=True, text=True,
                    creationflags=(subprocess.CREATE_NO_WINDOW
                                   if hasattr(subprocess, "CREATE_NO_WINDOW") else 0),
                )
                duration = float(result.stdout.strip()) if result.stdout.strip() else 5.0
            except Exception:
                duration = len(text) / 4  # 估算

            seg["audio_path"] = str(audio_path)
            seg["duration"] = round(duration, 2)

        timing = [
            {"index": s.get("index", i+1), "duration": s.get("duration", 0),
             "text_preview": s.get("text", "")[:40]}
            for i, s in enumerate(segments)
        ]
        (audio_dir / "timing.json").write_text(
            json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")

        total = sum(t["duration"] for t in timing)
        log.success(f"配音完成: {len(segments)} 段，{int(total//60)}分{int(total%60)}秒")
        return segments
