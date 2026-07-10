# Changelog

## [V1.1.0] - 2026-06-22

### 新增：批量选题生产 + 深度策略注入

#### 批量生产（不再一本书只出一个视频）
- `agent.py` 新增 `produce_topics(topics, count)` — 一次性处理多个选题
- `orchestrator.py` 新增 `batch_run_knowledge_points()` — 循环调用脚本引擎，不依赖 plan_book
- `orchestrator.py` 新增 `_topic_to_kp_info()` — 将 topic 字段映射为标准 kp_info 格式
- CLI 支持：逗号分隔多选（`1,3,5`）、TopN（`3`=Top3, `5`=Top5）、单个、默认 Top1
- Web API `/api/agent/confirm-topic` 支持 `topic_ids: [1,2,3]` 数组
- 批量容错：单个选题失败不影响其他选题，输出成功/失败汇总

#### 深度策略注入（Agent 输出结构化穿透到6个Prompt）
- `format_agent_context()` 将 topic 字段转为标准 `## 🎯 Agent Strategy Context` 文本块
- 以下 5 个 Prompt 均加入 `{agent_strategy_context}` 占位符：
  - `planner.txt`、`script_long.txt`、`full_script_writer.txt`、`opening_generator.txt`、`image_prompt_generator.txt`
- 注入链路：`agent.py` → `orchestrator.py` → `content_planner.py` + `script_generator.py`（3个子步骤）+ `image_prompt_generator.py`
- `pipeline_engine.py` 中 `run_generate_script()` 从 `plan["_agent_context_block"]` 读取并传递
- `image_prompt_generator.py` 中 `run()` 从 `knowledge_plan.json` 读取并注入

#### 零改动
- ContentPlanner 核心逻辑不动
- ScriptGenerator 核心逻辑不动
- 所有 TTS / 图片 / 视频合成服务不动
- 原有 `--plan-only` / `--kp-id` 模式完全保留

## [V1.0.0] - 2026-06-22

### 新增：Book Growth Agent 架构

项目从纯 Workflow 流水线升级为 **Agent + Workflow 混合架构**，形成"内容生产 → 数据分析 → 复盘优化 → 再生产"的增长闭环。

#### 核心新增

- **`agent.py`** — BookGrowthAgent 单Agent核心类
  - Phase 1：内容生产前决策（书籍分类 / 核心观点提炼 / 内容策略选择）
  - Phase 2：发布后分析（单视频诊断 / 批量复盘 / 爆款归因 / 增长建议）
  - 统一 Memory 读写，实现策略→效果追踪

- **`services/data_loader.py`** — 数据导入模块
  - 支持 Excel (.xlsx) 和 CSV (.csv)
  - 自动字段映射（中英文列名兼容）
  - CSV 编码自动检测（UTF-8/GBK）

- **`memory/`** — 记忆系统（3个 JSON 文件）
  - `book_strategy_memory.json`：每次生产时的分类+策略+效果
  - `analysis_memory.json`：每次分析的记录
  - `strategy_effectiveness.json`：策略效果追踪表

#### 新增 Prompt 文件（7个）

| 文件 | 用途 |
|------|------|
| `book_classifier.txt` | 书籍分类决策 |
| `insight_extractor.txt` | 核心观点提炼 |
| `strategy_selector.txt` | 内容策略选择 |
| `single_diagnosis.txt` | 单视频诊断 |
| `batch_analysis.txt` | 批量复盘分析 |
| `attribution_analysis.txt` | 爆款归因分析 |
| `growth_advisor.txt` | 增长建议生成 |

#### CLI 新增模式

- `python main.py --produce --book "书名"` — Agent 内容生产
- `python main.py --analyze --file data.xlsx` — 数据分析
- `python main.py --review --book "书名"` — 增长复盘
- 原有 `--plan-only` / `--kp-id` 模式保持向后兼容

#### Web UI 新增

- 侧边栏新增「增长」导航标签
- `/dashboard` — 增长仪表盘页面
- 快速操作：Agent 内容生产、数据分析、增长复盘
- 策略效果追踪表、最近分析记录

#### 架构改动

- `orchestrator.py`：`plan_book()` 新增 `strategy_params` 参数，可选接收 Agent 决策注入
- Web API 新增 5 个路由：`/api/agent/produce`、`/api/agent/analyze`、`/api/agent/diagnose`、`/api/agent/review`、`/api/agent/memory`
- 所有原有 Workflow 代码和服务类 **零改动**

### V1 范围

- ✅ 单Agent（BookGrowthAgent）
- ✅ 内容生产（分类 + 观点 + 策略 → 调用现有 Workflow）
- ✅ 数据分析（Excel/CSV 导入 → 诊断/复盘 → 归因 → 建议）
- ✅ 增长闭环（Memory 驱动的策略→效果追踪）
- ❌ 不做多Agent
- ❌ 不做OCR/截图
- ❌ 不做RAG
- ❌ 不做同行分析
- ❌ 不做自动抓取
