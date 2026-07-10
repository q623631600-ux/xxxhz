# 讲书升级Agent

**书本知识视频自动生成系统** — 输入一本书，自动输出带配音、字幕、配图的完整知识科普视频。

## 工作流程

```
书名 → 选题规划 → 脚本生成 → 内容切分 → 画面设计
→ 图片生成 → 语音合成 → 时间线组装 → 字幕生成 → 最终视频
```

## 快速开始

### 1. 环境要求
- Python 3.10+
- FFmpeg（需安装并加入 PATH）
- 各 API 服务密钥（见下方）

### 2. 安装

```bash
git clone https://github.com/q623631600-ux/xxxhz.git
cd 讲书升级Agent
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
```

然后编辑 `.env`，填入你自己的 API Key（详见 `.env.example` 中的注释）。

### 4. 启动

```bash
# Web 工作台
python web_app.py
# 访问 http://127.0.0.1:8001

# 或命令行模式
python main.py --produce --book "书名"
```

## 核心依赖

| 组件 | 技术 |
|------|------|
| LLM | DeepSeek / OpenAI 兼容接口 |
| 图片生成 | lk888 / DALL-E / 通义万相 |
| 语音合成 | Edge-TTS（免费）/ 火山引擎 / MiniMax |
| 视频合成 | FFmpeg |
| Web 框架 | FastAPI + Jinja2 |

## 项目结构

```
讲书升级Agent/
├── agent.py                # Agent 决策引擎
├── main.py                 # CLI 入口
├── web_app.py              # Web 工作台
├── services/               # 核心业务服务
│   ├── pipeline_engine.py  # Pipeline 调度引擎
│   ├── script_generator.py # 脚本生成
│   ├── image_generator.py  # 图片生成
│   ├── final_video_composer.py # 视频合成
│   └── ...
├── prompts/                # LLM 提示词模板
├── web/                    # 前端页面
├── utils/                  # 工具函数
├── config.py               # 配置管理
└── .env.example            # 环境配置模板
```

## License

MIT
