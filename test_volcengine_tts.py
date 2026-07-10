"""
火山引擎 TTS V3 HTTP Chunked 单向流式 — 单句测试
用法: python test_volcengine_tts.py "你好，测试文本"
"""
import sys
import json
import base64
from pathlib import Path
from dotenv import load_dotenv
import os
import aiohttp
import asyncio

load_dotenv(".env")

APP_ID = os.getenv("VOLCENGINE_TTS_APP_ID", "")
ACCESS_TOKEN = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN", "")
RESOURCE_ID = os.getenv("VOLCENGINE_TTS_RESOURCE_ID", "seed-tts-2.0")
SPEAKER = os.getenv("VOLCENGINE_TTS_SPEAKER", "zh_male_qingse")

API_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


async def synthesize(text: str, output_path: Path):
    print(f"文本: {text}")
    print(f"Speaker: {SPEAKER}")

    # 校验参数
    missing = []
    if not APP_ID:
        missing.append("VOLCENGINE_TTS_APP_ID")
    if not ACCESS_TOKEN:
        missing.append("VOLCENGINE_TTS_ACCESS_TOKEN")
    if not SPEAKER:
        missing.append("VOLCENGINE_TTS_SPEAKER")
    if missing:
        print(f"[FAIL] 缺少配置: {', '.join(missing)}")
        print("请在 .env 中填写以上字段")
        return False

    headers = {
        "Content-Type": "application/json",
        "X-Api-App-Id": APP_ID,
        "X-Api-Access-Key": ACCESS_TOKEN,
        "X-Api-Resource-Id": RESOURCE_ID,
    }

    body = {
        "user": {"uid": "book_workflow_test"},
        "req_params": {
            "text": text,
            "speaker": SPEAKER,
            "audio_params": {
                "format": "mp3",
                "sample_rate": 24000,
            },
        },
    }

    print(f"请求: {API_URL}")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=body, headers=headers) as resp:
                http_code = resp.status
                log_id = resp.headers.get("X-Tt-Logid", "N/A")
                print(f"HTTP {http_code}  LogId: {log_id}")

                if http_code != 200:
                    error_text = await resp.text()
                    try:
                        error_json = json.loads(error_text)
                        print(f"[FAIL] code={error_json.get('code')} message={error_json.get('message')}")
                    except Exception:
                        print(f"[FAIL] {error_text[:300]}")
                    return False

                # 流式读取 chunks
                audio_chunks = []
                chunk_count = 0

                async for line in resp.content:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        chunk_count += 1
                        code = chunk.get("code", -1)
                        msg = chunk.get("message", "")

                        if code == 20000000:
                            print(f"[OK] 合成结束 (chunks: {chunk_count})")
                            break

                        if code == 0:
                            data_b64 = chunk.get("data", "")
                            if data_b64:
                                audio_chunks.append(base64.b64decode(data_b64))
                        elif code != 0:
                            print(f"[FAIL] chunk #{chunk_count} code={code} message={msg}")
                            return False

                    except json.JSONDecodeError:
                        pass  # 非 JSON 行，跳过

                if not audio_chunks:
                    print("[FAIL] 没有收到音频数据")
                    return False

                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"".join(audio_chunks))
                size_kb = output_path.stat().st_size / 1024
                print(f"[OK] 生成成功: {output_path} ({size_kb:.1f} KB)")
                return True

    except aiohttp.ClientError as e:
        print(f"[FAIL] 网络错误: {e}")
        return False


def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "你好，这是火山引擎语音合成测试。"
    output = Path("output/test_tts/volcengine_test.mp3")
    success = asyncio.run(synthesize(text, output))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
