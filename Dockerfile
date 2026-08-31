# ============================================================
# 讲书升级Agent — Web 工作台 Docker 镜像
# 适配 Render / Railway / Fly.io 等支持 Docker 的平台部署
# ============================================================
FROM python:3.11-slim

# 环境变量：中文 UTF-8 + 时区
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

# 安装系统依赖：ffmpeg（视频合成）+ 中文字体（字幕/封面文字）
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先拷贝依赖清单并安装（利用 Docker 缓存层，改动代码不重装依赖）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码
COPY . .

# 字幕/标题默认使用容器内的 Noto CJK 中文字体
ENV SUBTITLE_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# 启动 Web 工作台（0.0.0.0 供平台对外访问）
CMD ["uvicorn", "web_app:app", "--host", "0.0.0.0", "--port", "8000"]
