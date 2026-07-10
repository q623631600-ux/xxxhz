"""
配置管理 - 从 .env 文件和环境变量读取配置
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# ========== 项目路径 ==========
PROJECT_ROOT = Path(__file__).parent
OUTPUT_DIR = PROJECT_ROOT / os.getenv("OUTPUT_DIR", "output")
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_WAREHOUSE_DIR = Path(os.getenv("DATA_WAREHOUSE_DIR", str(PROJECT_ROOT / "data_warehouse")))

# ========== LLM 配置 ==========
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# ========== 图片生成配置 ==========
IMAGE_API_KEY = os.getenv("IMAGE_API_KEY", "")
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "https://api.openai.com/v1")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "dall-e-3")
IMAGE_STYLE = os.getenv("IMAGE_STYLE", "温馨治愈的插画风格，色彩柔和")

# ========== 配音配置 ==========
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")

# ========== 视频配置 ==========
VIDEO_WIDTH = int(os.getenv("VIDEO_WIDTH", "1920"))
VIDEO_HEIGHT = int(os.getenv("VIDEO_HEIGHT", "1080"))
VIDEO_FPS = int(os.getenv("VIDEO_FPS", "24"))
VIDEO_TRANSITION_DURATION = float(os.getenv("VIDEO_TRANSITION_DURATION", "0.3"))

# ========== 字幕配置 ==========
SUBTITLE_FONT_PATH = os.getenv("SUBTITLE_FONT_PATH", "C:/Windows/Fonts/msyh.ttc")
SUBTITLE_FONT_SIZE = int(os.getenv("SUBTITLE_FONT_SIZE", "24"))     # FFmpeg subtitles 字体大小
SUBTITLE_BOLD = os.getenv("SUBTITLE_BOLD", "1")                     # 0=正常 1=粗体
SUBTITLE_MARGIN_V = int(os.getenv("SUBTITLE_MARGIN_V", "30"))       # 距底部距离
TITLE_FONT_SIZE = int(os.getenv("TITLE_FONT_SIZE", "36"))           # 标题字体大小(px)
TITLE_POSITION_Y = int(os.getenv("TITLE_POSITION_Y", "200"))        # 标题距顶部距离


def check_config() -> list[str]:
    """检查必要配置是否完整，返回缺失项列表"""
    issues = []
    if not LLM_API_KEY:
        issues.append("LLM_API_KEY 未设置（生成脚本需要）")
    if not IMAGE_API_KEY:
        issues.append("IMAGE_API_KEY 未设置（生成图片需要）")
    return issues
