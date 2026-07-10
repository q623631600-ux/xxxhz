"""
BookGrowthAgent — 讲书增长 Agent（V1 单Agent架构）

职责范围（两个阶段）:
  Phase 1 - 内容生产前决策:
    classify()        书籍分类
    extract_insights()核心观点提炼
    select_strategy() 内容策略选择

  Phase 2 - 发布后分析:
    import_data()     数据导入 (Excel/CSV → VideoData[])
    diagnose()        单视频诊断
    batch_analyze()   批量复盘（最近N条视频）
    attribute()       爆款归因
    advise()          增长建议

流程入口:
    produce()         内容生产：分类 → 提炼 → 策略 → 调用Workflow
    analyze()         数据分析：导入 → 诊断/复盘 → 归因 → 建议
    review()          增长复盘：查询记忆 → 综合输出
"""
import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR, PROJECT_ROOT
from utils.logger import log
from utils.json_utils import extract_json
from services.signal_detector import ContentStructureAnalyzer
from services.content_attribution import ContentAttributor
from services.strategy_validator import StrategyValidator


# ================================================================
# 数据结构
# ================================================================

@dataclass
class VideoData:
    """单条视频数据"""
    title: str = ""
    plays: int = 0
    likes: int = 0
    collects: int = 0
    comments: int = 0
    shares: int = 0
    publish_time: str = ""
    cover_desc: str = ""
    content_desc: str = ""
    duration: str = ""
    # 附加标记（分析后填充）
    performance_rating: str = ""  # top / normal / bottom


# ================================================================
# 书籍分类枚举（用于结构化输出约束）
# ================================================================

BOOK_CATEGORIES = {
    "cognitive_enhancement": "认知提升（思维方式、心智模型、认知科学）",
    "tool_method": "工具方法（实用技能、工作效率、学习方法）",
    "literature_fiction": "文学小说（经典文学、流行小说、故事集）",
    "history_biography": "历史传记（历史研究、人物传记、文明史）",
    "business_economics": "商业经济（商业思维、经济学、管理）",
    "popular_science": "科普新知（自然科学、前沿科技、心理学）",
    "self_help": "自我成长（心理自助、习惯养成、情绪管理）",
    "society_culture": "社会文化（社会学、文化研究、人类学）",
}


# ================================================================
# Agent 核心
# ================================================================

class BookGrowthAgent:
    """讲书增长单Agent — 统一决策入口"""

    def __init__(self, memory_dir: Optional[Path] = None):
        self._client = None
        self.memory_dir = memory_dir or (PROJECT_ROOT / "memory")
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        # Content Growth Agent 服务
        self.structure_analyzer = ContentStructureAnalyzer()
        self.attributor = ContentAttributor(llm_client=self._call_llm)
        self.strategy_validator = StrategyValidator(self.memory_dir)

    # ---- LLM 封装 ----

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置，请先设置 .env 文件")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    def _call_llm(self, system_prompt: str, user_prompt: str,
                  temperature: float = 0.3, max_tokens: int = 4000) -> dict:
        """统一LLM调用 + JSON提取"""
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        reply = response.choices[0].message.content
        try:
            return extract_json(reply)
        except ValueError as e:
            log.error(f"LLM回复JSON解析失败: {e}")
            log.debug(f"前300字符: {reply[:300]}")
            raise

    def _load_prompt(self, filename: str) -> str:
        """加载 Prompt 文件"""
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Prompt 文件不存在: {filename}")

    def _safe_name(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in " _-()（）")
        return safe.strip() or "unnamed"

    # ================================================================
    # Phase 1: 内容生产前决策
    # ================================================================

    def classify(self, book_name: str, toc: str = "",
                 source: str = "", focus: str = "") -> dict:
        """
        书籍分类决策。
        根据书名+可选素材判断品类、受众和内容方向。
        """
        log.info(f"[Agent] 正在对《{book_name}》进行书籍分类...")

        prompt_template = self._load_prompt("book_classifier.txt")
        categories_desc = "\n".join(f"  - {k}: {v}" for k, v in BOOK_CATEGORIES.items())

        system_prompt = prompt_template.replace("{categories}", categories_desc)
        user_prompt = (
            f"书名:《{book_name}》\n"
            f"目录摘要: {toc[:2000] if toc else '未提供'}\n"
            f"原文/笔记摘要: {source[:3000] if source else '未提供'}\n"
            f"聚焦方向: {focus or '未指定'}"
        )

        result = self._call_llm(system_prompt, user_prompt, temperature=0.4, max_tokens=2000)
        log.success(f"[Agent] 分类完成: {result.get('category', '?')} → {result.get('sub_category', '')}")
        return result

    def extract_insights(self, book_name: str, category: str,
                         toc: str = "", source: str = "", focus: str = "") -> dict:
        """
        核心观点提炼。
        基于分类结果，从书中提炼1-3个最能打动目标受众的核心观点。
        """
        log.info(f"[Agent] 正在提炼《{book_name}》核心观点...")

        prompt_template = self._load_prompt("insight_extractor.txt")
        system_prompt = prompt_template.replace("{category}", category)

        user_prompt = (
            f"书名:《{book_name}》\n"
            f"目录摘要: {toc[:2000] if toc else '未提供'}\n"
            f"原文/笔记摘要: {source[:3000] if source else '未提供'}\n"
            f"聚焦方向: {focus or '未指定'}"
        )

        result = self._call_llm(system_prompt, user_prompt, temperature=0.5, max_tokens=3000)
        count = len(result.get("insights", []))
        log.success(f"[Agent] 提炼完成: {count} 个核心观点")
        return result

    def select_strategy(self, category: str, insights: list,
                        strategy_history: Optional[list] = None) -> dict:
        """
        内容策略选择。
        根据书籍品类和核心观点，选择最适合的讲书策略和风格参数。
        可选传入历史策略效果供参考。
        """
        log.info(f"[Agent] 正在选择内容策略 (品类: {category})...")

        prompt_template = self._load_prompt("strategy_selector.txt")
        system_prompt = prompt_template.replace("{category}", category)

        insights_text = json.dumps(insights, ensure_ascii=False, indent=2) if insights else "暂无"
        history_text = ""
        if strategy_history:
            history_text = "\n历史策略效果参考:\n"
            for h in strategy_history[-5:]:
                history_text += json.dumps(h, ensure_ascii=False) + "\n"

        user_prompt = (
            f"书籍品类: {category}\n"
            f"核心观点:\n{insights_text}\n"
            f"{history_text}"
        )

        result = self._call_llm(system_prompt, user_prompt, temperature=0.4, max_tokens=2000)
        log.success(f"[Agent] 策略选择完成: {result.get('strategy_name', '?')}")
        return result

    @staticmethod
    def format_agent_context(topic: dict) -> str:
        """将选中的 topic 格式化为标准 Agent Strategy Context 文本块，用于注入到各Prompt"""
        lines = [
            "## 🎯 Agent Strategy Context",
            "以下是由 Book Growth Agent 生成的内容策略。请严格遵循这些指导来生成内容。",
            "",
        ]
        field_map = [
            ("Selected Topic", "topic_title"),
            ("Core Insight", "core_insight"),
            ("Target Audience", "target_audience"),
            ("Content Angle", "content_angle"),
            ("Recommended Hook Type", "hook_type"),
            ("Tone", "tone"),
            ("Structure Emphasis", "structure_emphasis"),
            ("Visual Style", "visual_style"),
            ("Platform Safety Note", "platform_safety_note"),
        ]
        for label, key in field_map:
            val = topic.get(key, "")
            if val:
                lines.append(f"- **{label}**: {val}")
        lines.append("")
        lines.append("以上策略决定了下游所有内容的风格、结构和表达方式，请勿偏离。")
        return "\n".join(lines)

    def generate_topic_pool(self, book_name: str, category: str,
                            insights: list, strategy: dict,
                            toc: str = "", source: str = "",
                            target_audience: str = "",
                            focus: str = "") -> dict:
        """
        生成 Top5 高潜力选题池。
        从整本书中扫描，输出5个评分选题候选。
        """
        log.info(f"[Agent] 正在生成 Top5 选题池...")

        prompt_template = self._load_prompt("topic_pool_generator.txt")
        system_prompt = (
            prompt_template
            .replace("{book_name}", book_name)
            .replace("{category}", category)
            .replace("{strategy_name}", strategy.get("strategy_name", ""))
            .replace("{tone}", strategy.get("tone", ""))
            .replace("{hook_type}", strategy.get("hook_type", ""))
            .replace("{growth_signals}", focus or "")
        )
        target_audience_text = target_audience or strategy.get("target_audience", "普通读者")
        system_prompt = system_prompt.replace("{target_audience}", target_audience_text)

        insights_text = json.dumps(insights, ensure_ascii=False, indent=2) if insights else "暂无"
        system_prompt = system_prompt.replace("{insights}", insights_text)

        source_text = (toc + "\n\n" + source) if toc and source else (toc or source or "未提供")
        system_prompt = system_prompt.replace("{source_text}", source_text[:3000])

        user_prompt = f"请为《{book_name}》生成5个高潜力短视频选题。必须严格遵循平台表达规则。"

        result = self._call_llm(system_prompt, user_prompt, temperature=0.6, max_tokens=5000)
        topics = result.get("topics", [])
        log.success(f"[Agent] 选题池生成完成: {len(topics)} 个候选选题")
        return result

    def produce(self, book_name: str, toc: str = "",
                source: str = "", focus: str = "") -> dict:
        """
        Phase 1 第一阶段：生成选题池（不调用Workflow）。

        流程：classify() → extract_insights() → select_strategy() → generate_topic_pool()

        返回 Top5 选题池供用户选择。
        用户选择后调用 produce_with_topic() 进行深度生产。

        Content Growth 增强：
          读取 self_growth_memory + strategy_pool → 注入内容信号 → 过滤已废弃策略
        """
        log.title(f"[Agent 生产] 《{book_name}》")
        start_time = datetime.now()

        # === Content Growth Phase 0: 读取增长信号和策略 ===
        self_growth = self._read_self_growth()
        validated_strategies = self.strategy_validator.get_validated_strategies()
        banned_strategies = self.strategy_validator.get_rejected_strategies()
        growth_context = self._build_growth_context(
            self_growth, validated_strategies, banned_strategies
        )
        log.info(f"[Agent 增长] 已读取: {len(validated_strategies)} 个已验证策略, "
                 f"{len(banned_strategies)} 个已废弃策略")

        # 将增长上下文注入 focus（供下游所有步骤使用）
        if growth_context:
            focus = (focus + '\n\n' + growth_context) if focus else growth_context

        # Step 1: 书籍分类
        classification = self.classify(book_name, toc=toc, source=source, focus=focus)
        category = classification.get("category", "cognitive_enhancement")
        target_audience = classification.get("target_audience", "")

        # Step 2: 核心观点提炼
        insights_result = self.extract_insights(
            book_name, category, toc=toc, source=source, focus=focus
        )
        insights = insights_result.get("insights", [])

        # Step 3: 策略选择（参考历史效果 + 已验证策略优先）
        strategy_history = self._read_memory("strategy_effectiveness").get("mappings", [])
        relevant_history = [m for m in strategy_history if m.get("category") == category]

        # 从已验证策略池中推荐最优策略
        best_from_pool = self.strategy_validator.select_best_strategies(
            {"category": category}, top_n=3
        )
        if best_from_pool:
            validated_hint = "已验证策略推荐（优先采用）:\n"
            for bs in best_from_pool:
                s = bs["strategy"]
                validated_hint += f"  - {s['name']} (置信度: {s['confidence']})\n"
            focus_with_pool = (focus or "") + "\n\n" + validated_hint
            strategy = self.select_strategy(category, insights,
                                            strategy_history=relevant_history)
            # 尝试用 focus_with_pool 重新生成——将已验证策略注入
            if "validated_hint" not in str(focus):
                focus += "\n\n" + validated_hint
        else:
            strategy = self.select_strategy(category, insights,
                                            strategy_history=relevant_history)

        # 读取反馈记忆，注入用户偏好
        feedback_hint = ''
        try:
            fb_path = self.memory_dir / 'feedback_memory.json'
            if fb_path.exists():
                import json as _json
                fb_data = _json.loads(fb_path.read_text(encoding='utf-8'))
                prefs = fb_data.get('preferences', {})
                liked = prefs.get('liked_styles', [])
                disliked = prefs.get('disliked_styles', [])
                if liked or disliked:
                    parts = []
                    if liked: parts.append('用户喜欢的风格：' + '、'.join(liked))
                    if disliked: parts.append('用户不喜欢的风格：' + '、'.join(disliked))
                    feedback_hint = '；'.join(parts) + '。生成选题时请参考这些偏好。'
        except Exception:
            pass
        if feedback_hint:
            focus = (focus + ' ' + feedback_hint) if focus else feedback_hint

        # Step 4: 生成 Top5 选题池（注入增长上下文）
        topic_pool = self.generate_topic_pool(
            book_name=book_name,
            category=category,
            insights=insights,
            strategy=strategy,
            toc=toc,
            source=source,
            target_audience=target_audience,
            focus=focus,
        )
        topics = topic_pool.get("topics", [])

        # 保存到 memory（暂存，用户选择后再更新）
        memory_entry = {
            "book_name": book_name,
            "category": category,
            "target_audience": target_audience,
            "strategy_name": strategy.get("strategy_name", ""),
            "strategy_detail": strategy,
            "insights": insights,
            "topics": topics,
            "produced_at": datetime.now().isoformat(),
            "growth_context_used": bool(growth_context),
            "validated_strategies_available": len(validated_strategies),
            "selected_topic": None,
        }
        self._append_memory_entry("book_strategy_memory", memory_entry)

        elapsed = (datetime.now() - start_time).total_seconds()
        log.success(f"[Agent 生产] 选题池生成完成，耗时 {elapsed:.0f}s "
                     f"(增长模式: {'启用' if growth_context else '无数据'})")

        return {
            "book_name": book_name,
            "classification": classification,
            "insights": insights_result,
            "strategy": strategy,
            "topics": topics,
            "total_topics": len(topics),
            "phase": "topic_pool",
            "growth_context_used": bool(growth_context),
            "validated_strategies_available": len(validated_strategies),
        }

    def produce_with_topic(self, book_name: str, topic: dict,
                           strategy_params: dict,
                           toc: str = "", source: str = "",
                           focus: str = "") -> dict:
        """
        Phase 1 第二阶段：单个选题深度生产（保留兼容）。
        调用 Workflow 生成 knowledge_plan.json + 深度注入 agent_context。
        """
        log.title(f"[Agent 深度生产] 《{book_name}》→ {topic.get('topic_title', '')}")
        start_time = datetime.now()

        # 构建完整的 agent_context（包含 topic + strategy）
        agent_context = {
            "topic_title": topic.get("topic_title", ""),
            "core_insight": topic.get("core_insight", ""),
            "target_audience": topic.get("target_audience", ""),
            "content_angle": topic.get("content_angle", ""),
            "hook_type": topic.get("hook_type", ""),
            "tone": topic.get("tone", ""),
            "structure_emphasis": topic.get("structure_emphasis", ""),
            "visual_style": topic.get("visual_style", ""),
            "platform_safety_note": topic.get("platform_safety_note", ""),
            "strategy_name": strategy_params.get("strategy_name", ""),
        }

        # 生成标准 Agent Strategy Context 文本块
        agent_context_block = self.format_agent_context(agent_context)

        # 调用 Workflow：深度注入 agent_context
        from services.orchestrator import Orchestrator
        orch = Orchestrator()
        plan = orch.plan_book(
            book_name=book_name,
            toc=toc,
            source=source,
            focus=focus,
            strategy_params=strategy_params,
            agent_context=agent_context_block,
        )

        # 保存选题信息到 knowledge_plan.json 供下游 ScriptGenerator 读取
        plan["_agent_context"] = agent_context
        plan["_agent_context_block"] = agent_context_block
        from services.content_planner import ContentPlanner
        planner = ContentPlanner()
        output_dir = Path.cwd() / "output" / self._safe_name(book_name)
        planner.save_plan(plan, output_dir)

        # 更新 memory：记录用户选择的选题
        strategy_mem = self._read_memory("book_strategy_memory")
        for entry in reversed(strategy_mem.get("entries", [])):
            if entry.get("book_name") == book_name and entry.get("selected_topic") is None:
                entry["selected_topic"] = topic
                entry["plan_generated"] = True
                self._write_memory("book_strategy_memory", strategy_mem)
                break

        # 统计知识点数量
        total_kps = 0
        for section in plan.get("content_outline", []):
            total_kps += len(section.get("knowledge_points", []))

        elapsed = (datetime.now() - start_time).total_seconds()
        log.success(f"[Agent 深度生产] 完成，耗时 {elapsed:.0f}s")

        return {
            "book_name": book_name,
            "selected_topic": topic,
            "agent_context": agent_context,
            "plan": plan,
            "total_kps": total_kps,
            "phase": "completed",
        }

    def produce_topics(self, book_name: str, topics: list,
                       count: int, strategy_params: dict,
                       toc: str = "", source: str = "",
                       focus: str = "") -> dict:
        """
        Phase 1 批量生产：用户选择多个选题后，每个选题独立生成视频。
        不走 plan_book()，直接为每个 topic 创建独立 kp_info，调用 Workflow 生成脚本。

        Args:
            book_name: 书名
            topics: 选题列表（从 produce() 的返回中获取）
            count: 用户选择的选题数量（取前 count 个）
            strategy_params: 策略参数（来自 produce()）
            toc, source, focus: 原始输入

        Returns:
            {"success": True, "results": [...], "success_count": N, "fail_count": N}
        """
        selected = topics[:count]
        log.title(f"[Agent 批量生产] 《{book_name}》→ 共 {len(selected)} 个选题")

        from services.orchestrator import Orchestrator
        orch = Orchestrator()

        # 为每个 topic 构建 agent_context_block
        topic_configs = []
        for t in selected:
            ctx = {
                "topic_title": t.get("topic_title", ""),
                "core_insight": t.get("core_insight", ""),
                "target_audience": t.get("target_audience", ""),
                "content_angle": t.get("content_angle", ""),
                "hook_type": t.get("hook_type", ""),
                "tone": t.get("tone", ""),
                "structure_emphasis": t.get("structure_emphasis", ""),
                "visual_style": t.get("visual_style", ""),
                "platform_safety_note": t.get("platform_safety_note", ""),
                "strategy_name": strategy_params.get("strategy_name", ""),
            }
            ctx_block = self.format_agent_context(ctx)
            topic_configs.append((t, ctx, ctx_block))

        # 调用批量编排
        results = orch.batch_run_knowledge_points(
            book_name=book_name,
            topic_configs=topic_configs,
        )

        success_count = sum(1 for r in results if r.get("success"))
        fail_count = sum(1 for r in results if not r.get("success"))

        log.success(f"[Agent 批量生产] 完成: {success_count} 成功, {fail_count} 失败")
        return {
            "book_name": book_name,
            "total_selected": len(selected),
            "results": results,
            "success_count": success_count,
            "fail_count": fail_count,
            "phase": "batch_completed",
        }

    # ================================================================
    # Phase 2: 发布后分析
    # ================================================================

    def import_data(self, file_path: str) -> list:
        """
        数据导入。
        支持 Excel (.xlsx) 和 CSV (.csv) 格式。
        返回 VideoData[] 列表。
        """
        from services.data_loader import load_video_data
        log.info(f"[Agent] 导入数据: {file_path}")
        videos = load_video_data(file_path)
        log.success(f"[Agent] 导入完成: {len(videos)} 条视频数据")
        return [asdict(v) if hasattr(v, "__dataclass_fields__") else v for v in videos]

    def diagnose(self, video: dict) -> dict:
        """
        单视频诊断。
        分析：标题、封面、内容结构、发布时长的逐项评分。
        """
        log.info(f"[Agent] 单视频诊断: {video.get('title', '未知')[:30]}...")

        prompt_template = self._load_prompt("single_diagnosis.txt")
        system_prompt = prompt_template

        video_json = json.dumps(video, ensure_ascii=False, indent=2)
        user_prompt = f"请分析以下视频数据:\n\n{video_json}"

        result = self._call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=3000)
        log.success(f"[Agent] 诊断完成: 综合评分 {result.get('overall_score', '?')}")
        return result

    def batch_analyze(self, videos: list) -> dict:
        """
        批量复盘。
        分析最近N条视频 → 分组高/低表现 → 提取标题/封面/内容规律。
        """
        count = len(videos)
        log.info(f"[Agent] 批量复盘: {count} 条视频")

        prompt_template = self._load_prompt("batch_analysis.txt")
        system_prompt = prompt_template

        videos_json = json.dumps(videos, ensure_ascii=False, indent=2)
        user_prompt = f"请复盘以下 {count} 条视频数据:\n\n{videos_json}"

        result = self._call_llm(system_prompt, user_prompt, temperature=0.3, max_tokens=5000)
        log.success(f"[Agent] 复盘完成: 发现 {len(result.get('patterns', {}))} 类规律")
        return result

    def attribute(self, top_videos: list, bottom_videos: list, patterns: dict) -> dict:
        """
        爆款归因。
        对比高/低表现视频，结合规律，输出归因结论。
        """
        log.info(f"[Agent] 爆款归因: Top {len(top_videos)} vs Bottom {len(bottom_videos)}")

        prompt_template = self._load_prompt("attribution_analysis.txt")
        system_prompt = prompt_template

        user_prompt = (
            f"高表现视频:\n{json.dumps(top_videos, ensure_ascii=False, indent=2)}\n\n"
            f"低表现视频:\n{json.dumps(bottom_videos, ensure_ascii=False, indent=2)}\n\n"
            f"提取到的规律:\n{json.dumps(patterns, ensure_ascii=False, indent=2)}"
        )

        result = self._call_llm(system_prompt, user_prompt, temperature=0.4, max_tokens=3000)
        log.success(f"[Agent] 归因完成: {len(result.get('key_drivers', []))} 个关键驱动因素")
        return result

    def advise(self, analysis: dict, attribution: dict) -> dict:
        """
        增长建议。
        综合分析和归因结果，输出可执行的优化建议。
        """
        log.info(f"[Agent] 生成增长建议...")

        prompt_template = self._load_prompt("growth_advisor.txt")
        system_prompt = prompt_template

        user_prompt = (
            f"分析结果:\n{json.dumps(analysis, ensure_ascii=False, indent=2)}\n\n"
            f"归因结果:\n{json.dumps(attribution, ensure_ascii=False, indent=2)}"
        )

        result = self._call_llm(system_prompt, user_prompt, temperature=0.4, max_tokens=3000)
        log.success(f"[Agent] 建议生成完成: {len(result.get('priorities', []))} 个优先事项")
        return result

    def analyze(self, file_path: str, mode: str = "auto",
                book_name: str = "") -> dict:
        """
        完整数据分析流程（Phase 2完整链路）：
          import_data() → (diagnose | batch_analyze) → attribute() → advise()
        """
        log.title(f"[Agent 分析] {file_path}")

        # Step 1: 导入数据
        videos = self.import_data(file_path)
        if not videos:
            return {"success": False, "error": "无有效数据", "file_path": file_path}

        # 自动判断模式
        if mode == "auto":
            mode = "single" if len(videos) == 1 else "batch"
        log.info(f"[Agent] 分析模式: {mode} ({len(videos)} 条视频)")

        # Step 2: 分析
        if mode == "single":
            analysis_result = self.diagnose(videos[0])
            # 单视频模式：没有归因，直接给建议
            attribution_result = {
                "key_drivers": [{"factor": "N/A (单视频)", "evidence": "单条视频不足以归因对比", "impact": "low"}],
                "key_problems": analysis_result.get("weaknesses", []),
                "summary": "单视频诊断，建议积累更多数据后做批量复盘",
            }
            advice_result = self.advise(analysis_result, attribution_result)

            result = {
                "success": True,
                "mode": "single",
                "video_count": 1,
                "diagnosis": analysis_result,
                "attribution": attribution_result,
                "advice": advice_result,
            }

        else:
            analysis_result = self.batch_analyze(videos)
            top_videos = analysis_result.get("top_videos", [])
            bottom_videos = analysis_result.get("bottom_videos", [])
            patterns = analysis_result.get("patterns", {})
            attribution_result = self.attribute(top_videos, bottom_videos, patterns)
            advice_result = self.advise(analysis_result, attribution_result)

            result = {
                "success": True,
                "mode": "batch",
                "video_count": len(videos),
                "analysis": analysis_result,
                "attribution": attribution_result,
                "advice": advice_result,
            }

        # Step 3: 保存分析记忆
        analysis_entry = {
            "date": datetime.now().isoformat(),
            "mode": mode,
            "video_count": len(videos),
            "file_path": file_path,
            "book_name": book_name or "",
            "key_findings": attribution_result.get("key_drivers", []),
            "recommendations": [a.get("action", "") for a in advice_result.get("priorities", [])],
            "tracked": False,
        }
        self._append_memory_entry("analysis_memory", analysis_entry)

        # Step 4: 如果书名校对匹配，更新策略记忆的 metrics
        if book_name:
            strategy_mem = self._read_memory("book_strategy_memory")
            for entry in reversed(strategy_mem.get("entries", [])):
                if entry.get("book_name") == book_name and not entry.get("metrics"):
                    entry["metrics"] = {
                        "total_videos": len(videos),
                        "avg_plays": sum(v.get("plays", 0) for v in videos) / max(len(videos), 1),
                        "avg_likes": sum(v.get("likes", 0) for v in videos) / max(len(videos), 1),
                        "top_play": max((v.get("plays", 0) for v in videos), default=0),
                    }
                    entry["attribution"] = attribution_result
                    entry["advice_given"] = advice_result
                    self._write_memory("book_strategy_memory", strategy_mem)
                    break

        log.success(f"[Agent 分析] 完成")
        return result

    def review(self, book_name: str = "") -> dict:
        """
        增长复盘。
        查询记忆 → 回顾策略→效果追踪 → 综合输出。
        """
        log.title(f"[Agent 复盘] {book_name or '全部记录'}")

        strategy_mem = self._read_memory("book_strategy_memory")
        analysis_mem = self._read_memory("analysis_memory")
        effectiveness = self._read_memory("strategy_effectiveness")

        # 过滤指定书籍
        if book_name:
            strategy_entries = [e for e in strategy_mem.get("entries", [])
                               if e.get("book_name") == book_name]
            analysis_entries = [e for e in analysis_mem.get("entries", [])
                               if e.get("book_name") == book_name]
        else:
            strategy_entries = strategy_mem.get("entries", [])
            analysis_entries = analysis_mem.get("entries", [])

        # 统计效果
        total_produced = len(strategy_entries)
        total_analyzed = len(analysis_entries)

        # 策略效果汇总
        strategy_summary = {}
        for e in strategy_entries:
            cat = e.get("category", "unknown")
            strat = e.get("strategy_name", "unknown")
            key = f"{cat}/{strat}"
            if key not in strategy_summary:
                strategy_summary[key] = {"count": 0, "with_metrics": 0}
            strategy_summary[key]["count"] += 1
            if e.get("metrics"):
                strategy_summary[key]["with_metrics"] += 1

        # Content Growth: 加入策略池摘要
        strategy_pool_summary = self.strategy_validator.get_summary()
        self_growth = self._read_self_growth()

        return {
            "book_name": book_name or "全部",
            "total_produced": total_produced,
            "total_analyzed": total_analyzed,
            "strategy_summary": strategy_summary,
            "recent_strategies": strategy_entries[-5:],
            "recent_analyses": analysis_entries[-5:],
            "effectiveness": effectiveness.get("mappings", []),
            # Content Growth 增强
            "strategy_pool": strategy_pool_summary,
            "self_growth_videos_analyzed": self_growth.get("total_videos_analyzed", 0),
            "growth_enabled": True,
        }

    # ================================================================
    # Memory 管理
    # ================================================================

    def _read_memory(self, name: str) -> dict:
        """读取记忆文件"""
        path = self.memory_dir / f"{name}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                log.warn(f"记忆文件损坏: {name}.json，重置为空")
                return {}
        return {}

    def _write_memory(self, name: str, data: dict):
        """写入记忆文件"""
        path = self.memory_dir / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_memory_entry(self, name: str, entry: dict):
        """追加记忆条目"""
        data = self._read_memory(name)
        if "entries" not in data:
            data["entries"] = []
        data["entries"].append(entry)
        self._write_memory(name, data)

    # ================================================================
    # Content Growth Agent 六级学习体系
    # ================================================================

    def _read_self_growth(self) -> dict:
        """读取自身账号增长记忆（五层结构）"""
        data = self._read_memory("self_growth_memory")
        if not data or "content_structures" not in data:
            return {
                "total_videos_analyzed": 0,
                "content_structures": {"rankings": [], "best": "", "worst": ""},
                "openings": {"rankings": [], "best": ""},
                "content_models": {"self": [], "competitors": {}},
                "topics": {"rankings": []},
                "audience": {"interests": [], "similar_authors": [], "search_keywords": []},
            }
        return data

    def _write_self_growth(self, data: dict):
        self._write_memory("self_growth_memory", data)

    def _read_competitor_growth(self) -> dict:
        data = self._read_memory("competitor_growth_memory")
        if not data:
            return {"competitors": {}, "industry_aggregate": {"total_videos_analyzed": 0}}
        return data

    def _write_competitor_growth(self, data: dict):
        self._write_memory("competitor_growth_memory", data)

    # ================================================================
    # 上下文构建（结构/开场/模型 → Prompt 注入）
    # ================================================================

    def _build_growth_context(self, self_growth: dict,
                               validated: list,
                               rejected: list) -> str:
        """
        构建增长上下文文本块，注入到内容生成Prompt。

        核心改变：从关键词信号 → 内容结构/开场/模型 规则。
        """
        parts = ["## 📈 Content Growth Rules"]

        # 内容结构排行榜
        structures = self_growth.get("content_structures", {}).get("rankings", [])
        if structures:
            parts.append("")
            parts.append("🏆 内容结构排行榜（前三）:")
            for s in structures[:3]:
                parts.append(
                    f"   #{structures.index(s)+1} {s['structure']}: "
                    f"平均播放 {s['avg_metric']}, "
                    f"样本 {s['sample_count']}, "
                    f"较均值 {s.get('pct_better_than_average', 0)}%"
                )

        # 开场排行榜
        openings = self_growth.get("openings", {}).get("rankings", [])
        if openings:
            parts.append("")
            parts.append("🎬 开场排行榜（前三）:")
            for o in openings[:3]:
                parts.append(
                    f"   #{openings.index(o)+1} {o['opening']}: "
                    f"平均播放 {o['avg_metric']}, "
                    f"样本 {o['sample_count']}"
                )

        # 已验证策略规则（从 strategy_memory）
        validated_rules = self.strategy_validator.get_validated_rules()
        if validated_rules:
            parts.append("")
            parts.append("✅ 已验证策略规则（优先使用）:")
            for r in validated_rules[:5]:
                parts.append(
                    f"  - {r['rule']}: "
                    f"平均提升 {r['avg_play_increase']}%, "
                    f"置信度 {r['confidence']}"
                )

        # 已淘汰规则
        if rejected:
            parts.append("")
            parts.append("⛔ 淘汰策略（避免使用）:")
            for s in rejected[:3]:
                parts.append(f"  - {s['name']}")

        parts.append("")
        parts.append("请根据以上已验证规则和排行榜生成内容。")
        return "\n".join(parts)

    def _build_decision_trace(self, topic: dict,
                               self_growth: dict,
                               validated_rules: list) -> str:
        """
        构建决策透明化文本："Agent 为什么推荐这个选题"

        Returns:
            markdown 格式的决策原因文本
        """
        parts = ["🎯 Agent 推荐原因", ""]

        # 结构匹配
        title = topic.get("topic_title", "")
        structures = self.structure_analyzer._detect_structures(title)
        if structures:
            parts.append(f"✓ 匹配内容结构: {' + '.join(structures)}")
            for s in structures:
                rankings = self_growth.get("content_structures", {}).get("rankings", [])
                for r in rankings:
                    if r["structure"] == s:
                        parts.append(f"  此结构平均播放 {r['avg_metric']}, "
                                     f"较均值提升 {r.get('pct_better_than_average', 0)}%")
                        break

        # 开场匹配
        opening = self.structure_analyzer._detect_opening(title)
        if opening:
            parts.append(f"✓ 使用开场类型: {opening}")

        # 已验证策略匹配
        for rule in validated_rules[:3]:
            if any(kw in title for kw in rule.get("rule", "")):
                parts.append(f"✓ 采用已验证策略: {rule['rule']} "
                             f"(置信度 {rule['confidence']})")
                break

        parts.append("")
        parts.append("以上决策基于历史数据分析结果。")
        return "\n".join(parts)

    # ================================================================
    # Content Growth: 增强分析（六级学习体系）
    # ================================================================

    def analyze_with_growth(self, file_path: str, book_name: str = "") -> dict:
        """
        增强版分析：六级学习体系

        1. 标准分析 (analyze)
        2. 内容结构分析 (full_structure_analysis)
        3. 更新 self_growth_memory（五层）
        4. 自动归因
        5. 学习策略规则 (learn_from_analysis → strategy_memory)
        """
        log.title(f"[Content Growth 分析] {file_path}")
        start_time = datetime.now()

        # Step 1: 标准分析
        analysis_result = self.analyze(file_path, book_name=book_name)
        if not analysis_result.get("success", False):
            return analysis_result

        videos = self.import_data(file_path)
        if not videos:
            return {**analysis_result, "growth_analysis": None,
                    "error": "无视频数据用于增长分析"}

        # Step 2: 六级结构分析
        log.info("[Growth] 正在分析内容结构/开场/模型/主题...")
        structure_result = self.structure_analyzer.full_structure_analysis(videos)

        # Step 3: 更新 self_growth_memory（五层）
        log.info("[Growth] 正在更新自身记忆库...")
        self_growth = self._read_self_growth()
        self_growth = self.structure_analyzer.update_self_growth_memory(
            self_growth, structure_result
        )
        self._write_self_growth(self_growth)

        # Step 4: 自动归因
        log.info("[Growth] 正在运行自动归因...")
        sorted_by_plays = sorted(videos, key=lambda v: float(v.get("plays", 0) or 0), reverse=True)
        top_video = sorted_by_plays[0] if sorted_by_plays else None
        bottom_video = sorted_by_plays[-1] if len(sorted_by_plays) > 1 else None

        signal_result = structure_result.get("signals", {})
        top_attribution = self.attributor.full_attribution(top_video, signal_result) if top_video else None
        bottom_attribution = self.attributor.full_attribution(bottom_video, signal_result) if bottom_video and bottom_video != top_video else None

        # Step 5: 学习策略规则 → strategy_memory.json
        log.info("[Growth] 正在学习策略规则...")
        self.strategy_validator.learn_from_analysis(
            structure_result.get("content_structures", {}),
            structure_result.get("openings", {}),
            structure_result.get("content_models", {}),
            structure_result.get("topics", {}),
        )

        # 记录到 strategy_pool（向后兼容）
        for s in structure_result.get("content_structures", {}).get("rankings", [])[:3]:
            self.strategy_validator.record_strategy_outcome(
                f"结构_{s['structure']}", success=s.get("pct_better_than_average", 0) >= 0,
                context={"category": "content_structure", "structure": s["structure"],
                         "avg_metric": s["avg_metric"]}
            )

        strategy_summary = self.strategy_validator.get_summary()
        learning_center = self.strategy_validator.get_learning_center_data()

        elapsed = (datetime.now() - start_time).total_seconds()
        log.success(f"[Content Growth 分析] 完成，耗时 {elapsed:.0f}s")

        return {
            **analysis_result,
            "growth_analysis": {
                "content_structures": structure_result.get("content_structures"),
                "openings": structure_result.get("openings"),
                "content_models": structure_result.get("content_models"),
                "topics": structure_result.get("topics"),
                "top_video_attribution": top_attribution,
                "bottom_video_attribution": bottom_attribution,
                "strategy_pool": strategy_summary,
                "learning_center": learning_center,
                "total_videos_analyzed": self_growth.get("total_videos_analyzed", 0),
            },
            "growth_enabled": True,
        }

    def update_competitor_growth(self, competitor_name: str,
                                  file_path: str) -> dict:
        """分析竞品数据并更新 competitor_growth_memory（使用结构分析）"""
        log.info(f"[Growth] 正在分析竞品: {competitor_name}")
        videos = self.import_data(file_path)
        if not videos:
            return {"success": False, "error": "无有效数据"}

        result = self.structure_analyzer.full_structure_analysis(videos)

        comp_data = self._read_competitor_growth()
        comp_data.setdefault("competitors", {})[competitor_name] = {
            "total_videos": len(videos),
            "analyzed_at": datetime.now().isoformat(),
            "content_structures": result.get("content_structures"),
            "openings": result.get("openings"),
            "content_models": result.get("content_models"),
            "topics": result.get("topics"),
        }

        agg = comp_data.setdefault("industry_aggregate", {})
        agg["total_videos_analyzed"] = agg.get("total_videos_analyzed", 0) + len(videos)
        agg["last_updated"] = datetime.now().isoformat()

        self._write_competitor_growth(comp_data)
        log.success(f"[Growth] 竞品 {competitor_name} 分析完成 ({len(videos)}条)")

        return {
            "success": True,
            "competitor": competitor_name,
            "video_count": len(videos),
            "structure_analysis": result,
        }

    def growth_summary(self) -> dict:
        """返回增长结果摘要（供 /growth 学习中心使用）"""
        self_growth = self._read_self_growth()
        comp_growth = self._read_competitor_growth()
        strategy_summary = self.strategy_validator.get_summary()
        learning_center = self.strategy_validator.get_learning_center_data()

        return {
            "total_videos_analyzed": self_growth.get("total_videos_analyzed", 0),
            "total_competitors": len(comp_growth.get("competitors", {})),
            "total_competitor_videos": comp_growth.get("industry_aggregate", {}).get("total_videos_analyzed", 0),
            # 五层学习数据
            "content_structures": self_growth.get("content_structures", {}),
            "openings": self_growth.get("openings", {}),
            "content_models": self_growth.get("content_models", {}),
            "topics": self_growth.get("topics", {}),
            "audience": self_growth.get("audience", {}),
            # 策略数据
            "strategy_pool": strategy_summary,
            "learning_center": learning_center,
            "last_updated": self_growth.get("last_updated", ""),
        }
