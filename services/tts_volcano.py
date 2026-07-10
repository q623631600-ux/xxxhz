"""
火山引擎 TTS V3 HTTP Chunked — 已跑通
文档: https://www.volcengine.com/docs/6561/1598757
"""
import json
import asyncio
import base64
import subprocess
from pathlib import Path
import aiohttp

from utils.logger import log

API_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


class VolcanoTTS:
    """火山引擎 TTS V3 HTTP Chunked"""

    def __init__(self, app_id: str, access_token: str, speaker: str,
                 resource_id: str = "seed-tts-2.0"):
        self.app_id = app_id
        self.access_token = access_token
        self.speaker = speaker
        self.resource_id = resource_id

    async def generate_text(self, text: str, output_path: Path):
        """合成单段文字"""
        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": self.resource_id,
        }
        body = {
            "user": {"uid": "book_workflow"},
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=body, headers=headers) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    raise RuntimeError(f"TTS API {resp.status}: {error[:200]}")

                audio_chunks = []
                async for line in resp.content:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        code = chunk.get("code", -1)

                        if code == 20000000:  # 结束
                            break
                        if code == 0 and chunk.get("data"):
                            audio_chunks.append(base64.b64decode(chunk["data"]))
                        elif code != 0:
                            raise RuntimeError(
                                f"TTS chunk error: code={code} "
                                f"message={chunk.get('message', '')}"
                            )
                    except json.JSONDecodeError:
                        continue

                if not audio_chunks:
                    raise RuntimeError("TTS 返回空音频")

                output_path.write_bytes(b"".join(audio_chunks))

    async def generate(self, segments: list[dict], output_dir: Path) -> list[dict]:
        """批量合成"""
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"火山引擎 TTS V3 配音中（{len(segments)} 段）...")

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
                duration = len(text) / 4

            seg["audio_path"] = str(audio_path)
            seg["duration"] = round(duration, 2)

        timing = [
            {"index": s.get("index", i+1), "duration": s.get("duration", 0),
             "text_preview": s.get("text", "")[:40],
             "text": s.get("text", "")}  # 完整文本，供字幕生成精确对齐
            for i, s in enumerate(segments)
        ]
        (audio_dir / "timing.json").write_text(
            json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")

        total = sum(t["duration"] for t in timing)
        log.success(f"配音完成: {len(segments)} 段，{int(total//60)}分{int(total%60)}秒")
        return segments
