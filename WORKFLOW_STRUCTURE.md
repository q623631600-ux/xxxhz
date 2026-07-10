# 讲书工作流 — 完整结构分析

> 生成日期：2026-06-22
> 项目路径：D:\\讲书升级Agent
> 说明：保留原项目所有节点、Prompt、配置和逻辑，不做任何修改。

---

## 目录

- [1. 项目全景](#1-项目全景)
- [2. 工作流总览](#2-工作流总览)
- [3. 节点详解](#3-节点详解)
- [4. Prompt 清单](#4-prompt-清单)
- [5. 数据流与 I/O 关系](#5-数据流与-io-关系)
- [6. 工具调用关系](#6-工具调用关系)
- [7. Web 前端结构](#7-web-前端结构)
- [8. 配置体系](#8-配置体系)
- [9. 入口点与运行模式](#9-入口点与运行模式)
- [10. 完整文件清单](#10-完整文件清单)

---

## 1. 项目全景

讲书工作流是一个自动化的「书本→知识视频」生成系统。它接收一本书名，通过多步骤 LLM 调用和多媒体处理管道，最终产出一个含配音、字幕、配图的完整视频。

### 核心理念
- **每本书只有一个核心洞察，只做一个视频**
- **内容必须包含书中特有的案例/数据/故事，禁止瞎编**
- **让每个普通人都觉得"这个思想跟我有关"**

### 技术栈
| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI (uvicorn) |
| LLM 接口 | OpenAI 兼容客户端 → DeepSeek API |
| 图片生成 | lk888 API（异步，1920×1088） |
| 语音合成 | Edge-TTS / Volcano Engine TTS V3 / MiniMax TTS |
| 视频合成 | FFmpeg（libx264, subtitles, concat） |
| 图片处理 | Pillow |
| 前端 | Jinja2 模板 + 原生 JS |

---

## 2. 工作流总览

```
┌─────────────────────────────────────────────────────────────────┐
│                       完整工作流（10步）                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [1] 生成选题大纲 ───────────────────────────────────────────── │
│       ContentPlanner.plan() → knowledge_plan.json               │
│       Prompt：planner.txt                                       │
│       LLM: 1次调用                                               │
│                                                                  │
│  [2] 生成知识点脚本 ──────────────────────────────────────────── │
│       ScriptGenerator.generate_knowledge_point()                 │
│        ├─ Step 2a: 生成脚本结构 → script_long.txt               │
│        ├─ Step 2b: 撰写完整讲稿 → full_script_writer.txt        │
│        └─ Step 2c: 生成开场白 → opening_generator.txt           │
│       + QualityChecker.check() → quality_check.txt              │
│       + SafetyChecker.check() → safety_check.txt                │
│       LLM: 4-5次调用 (结构+脚本+开场白+质量审核+安全审核)       │
│       输出：script.json, quality_check.json, safety_check.json   │
│                                                                  │
│  [3] 内容单元切分 ────────────────────────────────────────────── │
│       ContentUnitSegmenter.segment() → content_units.json       │
│       Prompt：content_unit_segmenter.txt                        │
│       LLM: 1-N次（脚本超2000字时分片，每片1次调用）             │
│                                                                  │
│  [4] 画面点提取 ──────────────────────────────────────────────── │
│       VisualBeatExtractor.extract() → visual_beats.json         │
│       Prompt：visual_beat_extractor.txt                         │
│       LLM: 1-N次（每10个unit为一批）                            │
│                                                                  │
│  [5] 图片提示词生成 ──────────────────────────────────────────── │
│       ImagePromptGenerator.generate_prompts() → image_prompts.json│
│       Prompt：image_prompt_generator.txt                        │
│       LLM: 1-N次（每2个beat为一批）                             │
│                                                                  │
│  [5.5] 生成图片 ─────────────────────────────────────────────── │
│       ImageGenerator.generate_images() → images/beat_NNN.png    │
│       调用 lk888 API（并发模式，MAX_CONCURRENT=5）              │
│       非LLM调用                                                  │
│                                                                  │
│  [6] 生成配音 ────────────────────────────────────────────────── │
│       TTSGenerator/VolcanoTTS/MinimaxTTS.generate()              │
│         → audio/seg_NN.mp3 + audio/timing.json                  │
│       非LLM调用（TTS 引擎直出）                                  │
│                                                                  │
│  [7] 时间线组装 ──────────────────────────────────────────────── │
│       TimelineAssembler.assemble() → timeline.json               │
│       按文本长度权重分配时间，非LLM                               │
│                                                                  │
│  [8] 生成字幕 ────────────────────────────────────────────────── │
│       SubtitleGenerator.generate() → subtitles.srt              │
│                                   + title_overlays.json          │
│       非LLM                                                      │
│                                                                  │
│  [9] 合成最终视频 ────────────────────────────────────────────── │
│       FinalVideoComposer.compose() → final.mp4                  │
│       FFmpeg 5阶段流水线                                          │
│       非LLM                                                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 节点详解

### 3.1 生成选题大纲（plan_book）

| 属性 | 值 |
|---|---|
| 服务类 | `ContentPlanner` (`services/content_planner.py`) |
| Prompt | `prompts/planner.txt` |
| LLM 模型 | `LLM_MODEL`（DeepSeek Chat） |
| 温度 | 0.7 |
| 最大 Token | 8000 |
| 输入字段 | `{book_name}`, `{toc_text}`, `{source_text}`, `{focus_hint}` |
| 输出文件 | `output/{book}/knowledge_plan.json` |
| 标准化后结构 | `content_outline[0].knowledge_points[0]`（强制单KP） |

**`planner.txt` 核心指令**：
- 每本书只做一个视频，只提炼最核心的一个思想
- 防瞎编铁律（必须包含书中特有概念/案例/数据）
- 输出扁平格式 `core_insight` → 代码层标准化为 `content_outline`

**输出 JSON 字段**（标准化后）：
```
book_name, planning_principle,
content_outline[0]: {
  chapter, chapter_summary,
  knowledge_points[0]: {
    id, title, source_scope, original_meaning, core_problem,
    why_useful, universal_relevance, presentation_approach,
    specific_book_content[], suggested_video_length, hook_idea
  }
}
```

---

### 3.2 生成知识点脚本（generate_script）

| 属性 | 值 |
|---|---|
| 服务类 | `ScriptGenerator` (`services/script_generator.py`) |
| 内部步骤 | 3个子步骤 |
| LLM 调用次数 | 3次（结构+脚本+开场白） |

#### Step 2a: 生成脚本结构

| 属性 | 值 |
|---|---|
| Prompt | `prompts/script_long.txt` |
| 温度 | 0.8 |
| 最大 Token | 4000 |
| 输入 | `{book_name}`, `{kp_title}`, `{original_meaning}`, `{core_problem}`, `{why_useful}`, `{source_scope}`, `{relation_context}`, `{suggested_length}`, `{specific_book_content}` |
| 输出 | `script_structure`（结构对象） |

**`script_long.txt` 核心指令**：
- 禁止套用模板、禁止瞎编
- 通用结构骨架：Hook → 核心洞察 → 为什么 → 回到生活 → 行动指引 → 收束
- 字数硬性要求：5-8分≥1500字，8-12分≥2500字，12-15分≥3500字

**输出字段**：
```
core_message, universal_relevance, hook_angle, structure_overview,
sections[{section, title, purpose, key_content, book_content_used, estimated_words}]
```

#### Step 2b: 撰写完整讲稿

| 属性 | 值 |
|---|---|
| Prompt | `full_script_writer.txt` 或 `full_script_writer_worldcup.txt` |
| 温度 | 0.8 |
| 最大 Token | 8000 |
| 输入 | `{book_name}`, `{kp_title}`, `{suggested_length}`, `{structure_json}`, `{specific_book_content}` |
| 输出 | `full_script`（字符串）+ `paragraph_labels` |

**三条铁律**：
1. 用"我们"不用"你"
2. 每个抽象概念必须"落地"成日常语言
3. 结构由内容决定，不套模板

#### Step 2c: 生成开场白

| 属性 | 值 |
|---|---|
| Prompt | `prompts/opening_generator.txt`（新增） |
| 温度 | 0.8 |
| 最大 Token | 1000 |
| 输入 | `{book_name}`, `{kp_title}`, `{core_problem}`, `{universal_relevance}`, `{structure_overview}` |
| 输出 | `{"opening": "...", "mode": "A/B/C", "mode_reason": "..."}` |

**三种开场模式**：
- A: 问题共鸣型 — "你有没有过这种经历..."
- B: 反常识型 — "说一个反常识的事实..."
- C: 场景代入型 — "想象一下..."

开场白自动 prepend 到 `full_script` 正文前。脚本结构新增字段：
```
script.opening        # 开场白文本
script.opening_mode   # A/B/C
```

#### 质量审核（Quality Checker）

| 属性 | 值 |
|---|---|
| 服务类 | `QualityChecker` (`services/quality_checker.py`) |
| Prompt | `prompts/quality_check.txt` |
| 温度 | 0.1 |
| 最大 Token | 2000 |
| 输出文件 | `quality_check.json` |

**16个审核维度**（满分100分）：
```
source_accuracy(5), original_understanding(10), problem_awareness(10),
big_to_small_translation(12), explanation_clarity(15), logic_integrity(10),
progressive_structure(10), thinking_framework(8), life_judgment_tool(5),
transfer_ability(5), application_binding(5), plain_language(5),
practical_value(5), length_reasonableness(5), language_safety(8),
relatability(5)
```

一票否决条件：17项（缺少大→小转换、抽象词没拆解、全程用"你"等）。

#### 安全审核（Safety Checker）

| 属性 | 值 |
|---|---|
| 服务类 | `SafetyChecker` (`services/safety_checker.py`) |
| Prompt | `prompts/safety_check.txt` |
| 温度 | 0.1 |
| 最大 Token | 2000 |
| 输出 | `{"passed": bool, "risk_level": "safe/low/high/blocked", "issues": []}` |
| 输出文件 | `safety_check.json` |

---

### 3.3 内容单元切分（content_units）

| 属性 | 值 |
|---|---|
| 服务类 | `ContentUnitSegmenter` (`services/content_unit_segmenter.py`) |
| Prompt | `prompts/content_unit_segmenter.txt` |
| 温度 | 0.3 |
| 最大 Token | 8000 |
| 输入文件 | `script.json` → `full_script` |
| 输出文件 | `content_units.json` |

**切分策略**：
- 脚本≤2000字 → 单次LLM调用
- 脚本>2000字 → 分片处理（每片≤2000字，200字上下文重叠）
- JSON解析失败时自动降级为按句号切分

**输出格式**：
```
segmentation_principle, total_units,
content_units[{unit_id, text, estimated_reading_seconds}]
```

**数量硬限制**：
- ≤8分钟 → 不超过80个单元
- 8-12分钟 → 不超过100个单元

---

### 3.4 画面点提取（visual_beats）

| 属性 | 值 |
|---|---|
| 服务类 | `VisualBeatExtractor` (`services/visual_beat_extractor.py`) |
| Prompt | `prompts/visual_beat_extractor.txt` |
| 温度 | 0.3 |
| 最大 Token | 8000 |
| 输入文件 | `content_units.json` |
| 输出文件 | `visual_beats.json` |

**核心规则**：一个 content unit = 一个 visual beat，数量必须相等。

**分批策略**：每批10个unit。缺失时逐条补提。JSON解析失败时自动降级。

**输出格式**：
```
visual_beats[{beat_id, unit_id, stage, covered_text, core_message,
              visual_reason, visual_goal, visual_type, estimated_display_seconds, status}]
```

**visual_type 分类**：scene, concept, framework, case, warning, summary, transition, metaphor

---

### 3.5 图片提示词生成（image_prompts）

| 属性 | 值 |
|---|---|
| 服务类 | `ImagePromptGenerator` (`services/image_prompt_generator.py`) |
| Prompt | `prompts/image_prompt_generator.txt` |
| 温度 | 0.7 |
| 最大 Token | 16000 |
| 输入文件 | `visual_beats.json` |
| 输出文件 | `image_prompts.json` |

**分批策略**：每批2个beat。批次内注入统一风格参考，同视频风格一致。

**风格注入**：代码自动在每个 prompt 前加 `"美式漫画风格，粗黑轮廓线..."`。

**封面图**：每本书共用一张封面（不重复生成）。

**输出格式**：
```
items[{beat_id, stage, visual_type, covered_text, core_message,
       visual_goal, image_prompt, negative_prompt, image_status, image_path, notes}]
```

---

### 3.6 生成图片（generate_images）

| 属性 | 值 |
|---|---|
| 服务类 | `ImageGenerator` (`services/image_generator.py`) |
| API | lk888（异步，1920×1088） |
| 并发数 | `MAX_CONCURRENT = 5`（满载任务池） |
| 最大重试轮次 | 5轮 |
| 输出目录 | `kp_dir/images/beat_NNN.png` |
| 进度文件 | `kp_dir/generate_progress.json` |

**并发模型**：
1. 首次提交 `MAX_CONCURRENT`个任务填满线程池
2. 任意任务完成 → 处理结果 → 立即补充新任务
3. 池始终保持满载

**错误分级**：
- **Hard Error**（401/402）→ 取消所有任务，立即终止
- **Rate Limit**（429）→ 等待3-5s重试1次
- **Soft Error**（5xx/超时）→ 标记failed，下一轮重试
- 失败的生成占位图（30×40纯色）

---

### 3.7 生成配音（generate_audio）

| 属性 | 值 |
|---|---|
| 服务类 | 三选一（`.env`中 `TTS_ENGINE`） |
| 可选引擎 | Edge-TTS（免费）/ Volcano TTS V3 / MiniMax TTS |
| 输入文件 | `script.json` → `full_script` |
| 输出目录 | `kp_dir/audio/seg_NN.mp3` |
| 输出文件 | `kp_dir/audio/timing.json` |

**配音流程**：
1. 脚本按自然段拆分，最多50段
2. 每段生成独立MP3
3. 记录每段时长到 `timing.json`
4. `timing.json` 包含完整文本 → 供字幕精确同步

---

### 3.8 时间线组装（timeline_assembly）

| 属性 | 值 |
|---|---|
| 服务类 | `TimelineAssembler` (`services/timeline_assembler.py`) |
| 输入文件 | `visual_beats.json` + `content_units.json` + `audio/timing.json` |
| 输出文件 | `timeline.json` |

**对齐算法**：
- 按内容单元文本长度占脚本总长度的百分比分配音频时长
- 每个 beat 的开始 = 对应 unit 的开始时间
- 最后一个 unit 精确对齐到音频结尾

---

### 3.9 生成字幕（generate_subtitles）

| 属性 | 值 |
|---|---|
| 服务类 | `SubtitleGenerator` (`services/subtitle_generator.py`) |
| 输入文件 | `script.json` + `audio/timing.json` + `timeline.json` |
| 输出文件 | `subtitles.srt` + `title_overlays.json` |

**字幕规则**：
- 每行最多20个中文字符，单行模式
- 按字数比例分配时间，与配音精确同步
- 最后一条字幕填满剩余时间

**标题叠加**：从 timeline.json 中提取 core_message，生成时间轴标题数据。

---

### 3.10 合成最终视频（compose_final_video）

| 属性 | 值 |
|---|---|
| 服务类 | `FinalVideoComposer` (`services/final_video_composer.py`) |
| 输入文件 | `timeline.json` + `images/` + `audio/` + `subtitles.srt` |
| 输出文件 | `final.mp4` |
| 分辨率 | 1920×1080（.env 配置） |
| 帧率 | 24fps |

**5阶段FFmpeg流水线**：
1. 创建片段：每个beat生成一个精确帧数的视频片段
2. 拼接片段：concat demuxer 精确对齐
3. 混合音频：拼接音频段 → 混合到视频
4. 烧录字幕：subtitles filter
5. 叠加标题：ASS格式标题（可选）

**防错措施**：
- 视频短于音频时自动pad尾部帧
- 所有FFmpeg命令错误校验
- 占位图自动生成

---

## 4. Prompt 清单

共14个Prompt文件，位于 `prompts/` 目录：

| # | 文件名 | 用途 | 调用节点 | 温度 | 最大Token |
|---|--------|------|----------|------|-----------|
| 1 | `planner.txt` | 生成选题大纲（单视频单KP） | content_planner | 0.7 | 8000 |
| 2 | `planner_chapter.txt` | 备选：按章节规划 | — | — | — |
| 3 | `script_long.txt` | 设计脚本结构 | script_generator Step 2a | 0.8 | 4000 |
| 4 | `full_script_writer.txt` | 撰写完整讲稿 | script_generator Step 2b | 0.8 | 8000 |
| 5 | `full_script_writer_worldcup.txt` | 世界杯模式讲稿 | script_generator (世界杯模式) | 0.8 | 8000 |
| 6 | `opening_generator.txt` | 生成开场白 | script_generator Step 2c | 0.8 | 1000 |
| 7 | `content_unit_segmenter.txt` | 切分内容单元 | content_unit_segmenter | 0.3 | 8000 |
| 8 | `visual_beat_extractor.txt` | 提取画面点 | visual_beat_extractor | 0.3 | 8000 |
| 9 | `image_prompt_generator.txt` | 生成图片提示词 | image_prompt_generator | 0.7 | 16000 |
| 10 | `quality_check.txt` | 质量审核（16维度） | quality_checker | 0.1 | 2000 |
| 11 | `safety_check.txt` | 安全审核 | safety_checker | 0.1 | 2000 |
| 12 | `deep_analysis.txt` | 深度分析（模式A） | script_generator（旧模式A） | — | — |
| 13 | `bridge_design.txt` | 教学设计（模式A） | script_generator（旧模式A） | — | — |
| 14 | `teach_write.txt` | 撰写概述（模式A） | script_generator（旧模式A） | — | — |

---

## 5. 数据流与 I/O 关系

### 5.1 Pipeline 数据流图

```
用户输入：book_name
     │
     ▼
[1] plan_book ─── LLM(planner.txt) ──→ knowledge_plan.json
     │                                  ├── book_name
     │                                  ├── planning_principle
     │                                  └── content_outline[0].knowledge_points[0]
     │                                        ├── title, original_meaning
     │                                        ├── universal_relevance
     │                                        └── specific_book_content[]
     │
     ├── 用户选择 kp_id ──────────────────────┘
     ▼
[2] generate_script ─┬─ LLM(script_long.txt) ──→ script_structure (内存)
                     ├─ LLM(full_script_writer.txt) ──→ full_script
                     ├─ LLM(opening_generator.txt) ──→ opening (前置到full_script)
                     ├─ LLM(quality_check.txt) ──→ quality_check.json
                     └─ LLM(safety_check.txt) ──→ safety_check.json
                     │
                     ▼
               script.json ├── full_script (含开场白)
                           ├── opening, opening_mode
                           ├── script_structure
                           ├── paragraph_labels
                           └── estimated_video_length
     │
     ▼
[3] content_units ─── LLM(content_unit_segmenter.txt) ──→ content_units.json
     │                                                    └── [{unit_id, text, estimated_reading_seconds}]
     ▼
[4] visual_beats ──── LLM(visual_beat_extractor.txt) ──→ visual_beats.json
     │                                                    └── [{beat_id, stage, visual_type, covered_text, ...}]
     ▼
[5] image_prompts ─── LLM(image_prompt_generator.txt) ──→ image_prompts.json
     │                                                    └── [{beat_id, image_prompt, image_status: waiting_api, ...}]
     ▼
[5.5] generate_images ── lk888 API（并发×5）────→ images/beat_NNN.png
                                                     更新 image_prompts.json
     │
[6] generate_audio ─── TTS Engine ────────────→ audio/seg_NN.mp3
                                                  audio/timing.json
     │
     ▼
[7] timeline_assembly (非LLM) ────────────────→ timeline.json
     │
     ▼
[8] generate_subtitles (非LLM) ───────────────→ subtitles.srt
                                                   title_overlays.json
     │
     ▼
[9] compose_final_video ─── FFmpeg ───────────→ final.mp4
```

### 5.2 文件间依赖关系

```
                    knowledge_plan.json
                           │
                    script.json (含 opening)
                      ╱    │    ╲
          content_units  审核文件  audio/timing.json
                │                           │
         visual_beats                       │
                │                           │
         image_prompts                      │
                │                           │
           images/                          │
                ╲                          ╱
               timeline.json ← visual_beats + timing
                     │
               subtitles.srt
                     │
               final.mp4
```

---

## 6. 工具调用关系

### 6.1 外部 API

| 工具 | 用途 | 调用方式 | 配置（.env） | 备注 |
|------|------|----------|-------------|------|
| DeepSeek Chat（LLM） | 所有脚本/审核/提示词生成 | OpenAI SDK（Python） | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | 所有LLM调用走同一客户端 |
| lk888（生图API） | 图片生成 | HTTP POST（异步） | `IMAGE_API1_KEY`, `IMAGE_API1_URL`, `IMAGE_API1_SIZE` | 1920×1088 |
| 火山引擎 TTS V3 | 语音合成 | HTTP Chunked（aiohttp） | `TTS_ENGINE=volcano` + 火山相关配置 | 默认引擎 |
| Edge-TTS | 语音合成（备选） | Python edge-tts 库 | `TTS_ENGINE=edge` | 免费 |
| MiniMax TTS | 语音合成（备选） | aiohttp | `TTS_ENGINE=minimax` | 中文自然 |
| FFmpeg | 视频合成/音频处理 | subprocess | 视频参数在config.py | 本地安装 |

### 6.2 LLM 调用汇总

每个步骤使用独立的 prompt 文件、温度和 max_tokens。所有 LLM 调用通过 `OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)` 发出。

| 服务 | 方法 | 调用位置 | 每任务调用次数 |
|------|------|----------|--------------|
| ContentPlanner | `plan()` | `pipeline_engine.run_plan_book()` | 1次 |
| ScriptGenerator | `_generate_structure()` | `pipeline_engine.run_generate_script()` → `generate_knowledge_point()` | 1次 |
| ScriptGenerator | `_generate_full_script()` | 同上 | 1次 |
| ScriptGenerator | `_generate_opening()` | 同上 | 1次 |
| QualityChecker | `check()` | 同上（步骤2内） | 1次 |
| SafetyChecker | `check()` | 同上（步骤2内） | 1次 |
| ContentUnitSegmenter | `segment()` → `_segment_single()` / 分片 | `pipeline_engine.run_content_units()` | 1-N次 |
| VisualBeatExtractor | `extract()` → 分批 | `pipeline_engine.run_visual_beats()` | 1-N次 |
| ImagePromptGenerator | `generate_prompts()` → 分批 | `pipeline_engine.run_image_prompts()` | 1-N次 |

每个完整知识点最多 **8+ N次** LLM 调用（N取决于脚本长度/单元数量/画面数量）。

### 6.3 内部工具

| 工具 | 用途 | 所在文件 |
|------|------|---------|
| `Logger` | 彩色日志输出 | `utils/logger.py` |
| `extract_json()` | 从LLM回复中提取/修复JSON | `utils/json_utils.py` |
| `repair_truncated_json()` | 修复被截断的JSON | `utils/json_utils.py` |
| `_format_specific_content()` | 列表→文本格式化 | `script_generator.py` |
| `_sync_file_status()` | 同步图片目录状态与json | `image_generator.py` |
| `_normalize_plan()` | 扁平格式→数组格式标准化 | `content_planner.py` |

---

## 7. Web 前端结构

### 7.1 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `GET /` | `index.html` | 首页/项目列表 |
| `GET /project/{book_name}` | `project.html` | 书籍概览 + KP列表 |
| `GET /project/{book_name}/kp/{kp_id}` | `kp_detail.html` | 单个KP详细数据 |
| `GET /work?book=&kp_id=` | `pipeline.html` | 工作台（主要操作界面） |

### 7.2 API 路由

| 方法 | 路由 | 功能 |
|------|------|------|
| GET | `/api/pipeline/{book}/status` | 获取Pipeline状态 |
| POST | `/api/pipeline/{book}/run/plan` | 步骤1：生成大纲 |
| POST | `/api/pipeline/{book}/run/script/{kp_id}` | 步骤2：生成脚本 |
| POST | `/api/pipeline/{book}/run/content-units/{kp_id}` | 步骤3：内容单元 |
| POST | `/api/pipeline/{book}/run/visual-beats/{kp_id}` | 步骤4：画面点 |
| POST | `/api/pipeline/{book}/run/image-prompts/{kp_id}` | 步骤5：图片提示词 |
| POST | `/api/pipeline/{book}/run/generate-images/{kp_id}` | 步骤5.5：生成图片 |
| POST | `/api/pipeline/{book}/run/generate-audio/{kp_id}` | 步骤6：生成配音 |
| POST | `/api/pipeline/{book}/run/timeline-assembly/{kp_id}` | 步骤7：时间线 |
| POST | `/api/pipeline/{book}/run/generate-subtitles/{kp_id}` | 步骤8：生成字幕 |
| POST | `/api/pipeline/{book}/run/compose-final-video/{kp_id}` | 步骤9：合成视频 |
| POST | `/api/pipeline/{book}/run/visual-pipeline/{kp_id}` | 一键步骤3-5 |
| POST | `/api/pipeline/{book}/run/full/{kp_id}` | 一键全部（1-9） |
| POST | `/api/pipeline/{book}/run/retry-images/{kp_id}` | 重试失败图片 |
| POST | `/api/pipeline/{book}/run/regenerate-all/{kp_id}` | 全量重生成 |
| POST | `/api/script-mode/{mode}` | 切换脚本模式 |
| GET | `/api/script-mode` | 获取脚本模式 |
| POST | `/api/switch-image-api/{api_num}` | 切换图片API |
| GET | `/api/image-api-info` | 获取图片API信息 |
| POST | `/api/project/{book}/kp/{kp_id}/save-script` | 保存编辑后脚本 |
| GET | `/api/pipeline/{book}/failure-report/{kp_id}` | 失败报告 |
| GET | `/api/pipeline/{book}/generate-progress/{kp_id}` | 图片生成进度 |
| GET | `/api/pipeline/{book}/compose-progress/{kp_id}` | 视频合成进度 |
| GET | `/api/project/{book}/kp/{kp_id}/video/final` | 下载视频 |
| GET | `/api/project/{book}/kp/{kp_id}/audio/{seg_name}` | 音频文件 |
| GET | `/api/project/{book}/kp/{kp_id}/json/{filename}` | JSON数据 |

### 7.3 前端文件

| 文件 | 用途 |
|------|------|
| `web/static/app.js` | 前端交互逻辑、API调用、状态轮询 |
| `web/static/style.css` | 完整CSS（oklch色彩系统） |
| `web/templates/base.html` | 布局框架 + 侧边栏导航 |
| `web/templates/index.html` | 首页/项目列表 |
| `web/templates/project.html` | 书籍详情页 |
| `web/templates/pipeline.html` | 主工作台（10步Pipeline控制台） |
| `web/templates/kp_detail.html` | KP详情（脚本预览/审核/数据） |

---

## 8. 配置体系

### 8.1 `.env` 配置项

| 分类 | 变量 | 当前值 | 说明 |
|------|------|--------|------|
| LLM | `LLM_API_KEY` | sk-c658... | DeepSeek API Key |
| LLM | `LLM_BASE_URL` | https://api.deepseek.com | API 端点 |
| LLM | `LLM_MODEL` | deepseek-chat | 模型名 |
| 图片 | `IMAGE_API1_KEY` | sk-e14b... | lk888 API Key |
| 图片 | `IMAGE_API1_URL` | https://api.lk888.ai/v1/media/generate | lk888 端点 |
| 图片 | `IMAGE_API1_SIZE` | 1920x1088 | 图片尺寸 |
| 图片 | `IMAGE_MODEL` | gpt-image-2 | 图片模型 |
| 图片 | `IMAGE_ACTIVE_API` | 1 | 当前API编号 |
| 风格 | `IMAGE_STYLE` | 温馨治愈的插画风格... | 全局风格描述 |
| TTS | `TTS_ENGINE` | volcano | 当前引擎 |
| TTS | `TTS_VOICE` | zh_male_liufei_... | 音色 |
| 火山 | `VOLCENGINE_TTS_APP_ID` | 8657464286 | 火山应用ID |
| 火山 | `VOLCENGINE_TTS_ACCESS_TOKEN` | _aNXnXZ... | 火山Token |
| 火山 | `VOLCENGINE_TTS_RESOURCE_ID` | seed-tts-2.0 | 资源ID |
| 视频 | `VIDEO_WIDTH/HEIGHT/FPS` | 1920/1080/24 | 视频参数 |

### 8.2 运行时配置

| 文件 | 内容 |
|------|------|
| `script_mode.txt` | `normal` 或 `worldcup`（脚本生成模式） |

---

## 9. 入口点与运行模式

### 9.1 CLI 入口（`main.py`）

| 模式 | 命令 | 流程 |
|------|------|------|
| 大纲规划 | `python main.py --book "书" --plan-only` | 仅步骤1 |
| 脚本生成 | `python main.py --book "书" --kp-id 1 --script-only` | 步骤1+2 |
| 完整视频 | `python main.py --book "书" --kp-id 1 --full` | 全部步骤 |

### 9.2 Web 入口（`web_app.py`）

```
python web_app.py
# 访问 http://127.0.0.1:8000
```

### 9.3 其他入口

| 文件 | 用途 |
|------|------|
| `visual_workflow.py` | 视觉层CLI（步骤3-5） |
| `_gen_cover_preview.py` | 封面预览生成工具 |
| `start.bat` | 启动Web服务（杀旧进程+启动） |

---

## 10. 完整文件清单

### 项目根目录
```
.env                          # 运行时配置
.env.example                  # 配置模板
config.py                     # 配置加载器
main.py                       # CLI主入口
web_app.py                    # FastAPI Web服务
visual_workflow.py            # 视觉层CLI
_gen_cover_preview.py         # 封面预览工具
create_shortcut.ps1           # 桌面快捷方式脚本
start.bat                     # 启动脚本
requirements.txt              # Python依赖
PRODUCT.md                    # 产品需求文档
plan_mode.txt                 # 规划模式标志
script_mode.txt               # 脚本模式标志（normal/worldcup）
```

### prompts/（14个文件）
```
planner.txt                   # 大纲规划
planner_chapter.txt           # 按章节规划（备选）
script_long.txt               # 脚本结构设计
full_script_writer.txt        # 完整讲稿撰写
full_script_writer_worldcup.txt # 世界杯模式讲稿
opening_generator.txt         # 开场白生成（新增）
content_unit_segmenter.txt    # 内容单元切分
visual_beat_extractor.txt     # 画面点提取
image_prompt_generator.txt    # 图片提示词生成
quality_check.txt             # 质量审核
safety_check.txt              # 安全审核
deep_analysis.txt             # 深度分析（模式A）
bridge_design.txt             # 教学设计（模式A）
teach_write.txt               # 概述撰写（模式A）
```

### services/（18个文件）
```
orchestrator.py               # CLI编排器（模式A/B）
pipeline_engine.py            # Pipeline引擎（10步管理）
content_planner.py            # 内容规划（步骤1）
script_generator.py           # 脚本生成（步骤2，含开场白）
content_unit_segmenter.py     # 内容单元切分（步骤3）
visual_beat_extractor.py      # 画面点提取（步骤4）
image_prompt_generator.py     # 图片提示词（步骤5）
image_generator.py            # 图片生成（步骤5.5，并发模式）
tts_generator.py              # Edge-TTS配音（步骤6）
tts_volcano.py                # 火山TTS配音（步骤6）
tts_minimax.py                # MiniMax TTS配音（步骤6）
timeline_assembler.py         # 时间线组装（步骤7）
subtitle_generator.py         # 字幕生成（步骤8）
final_video_composer.py       # 最终视频合成（步骤9）
video_composer.py             # 旧版视频合成
quality_checker.py            # 质量审核
safety_checker.py             # 安全审核
jianying_exporter.py          # 剪映导出工具
web_project_loader.py         # 只读输出目录扫描器
```

### utils/（2个文件）
```
logger.py                     # 彩色日志
json_utils.py                 # JSON提取/修复工具
```

### web/（6个文件）
```
static/app.js                 # 前端交互逻辑
static/style.css              # 完整CSS
templates/base.html           # 布局框架
templates/index.html          # 首页
templates/project.html        # 项目详情
templates/pipeline.html       # 工作台
templates/kp_detail.html      # KP详情
```

### output/（运行时生成）
```
{book}/
  ├── knowledge_plan.json     # 大纲
  ├── cover.png               # 封面图
  ├── project_state.json      # 项目状态缓存
  └── kp_XXX_{title}/
        ├── script.json       # 完整脚本（含开场白）
        ├── script_safe.json  # 安全版脚本
        ├── quality_check.json# 质量审核
        ├── safety_check.json # 安全审核
        ├── content_units.json# 内容单元
        ├── visual_beats.json # 画面点
        ├── image_prompts.json# 图片提示词
        ├── timeline.json     # 时间线
        ├── subtitles.srt     # 字幕
        ├── title_overlays.json # 标题叠加
        ├── final.mp4         # 最终视频
        ├── images/           # 图片（beat_NNN.png）
        ├── audio/            # 配音（seg_NN.mp3 + timing.json）
        └── generate_progress.json # 生成进度
```

---

## 附录：关键设计决策记录

### 🐛 已知 Bug（已修复）
1. `specific_book_content` 未传入 Step 2 prompt → 已修复（`_format_specific_content()`）
2. `quality_check.txt` 对特定书耦合 → 已通用化（16维度，含 relatability）
3. 图片风格描述不一致 → 已对齐（统一为"美式漫画风格"）
4. 内容单元切分上下文断裂 → 已加200字重叠

### 🎯 内容策略
- 每本书只做一个视频 → 通过 `_normalize_plan()` 强制
- 开场白自动前置 → 通过 `_generate_opening()` + prepend 逻辑
- 图片并发生成 → 通过 `_process_batch_concurrent()`（ThreadPool + 满载池）

---

*文档结束*
