"""
编排器

模式 1: plan_book       — 只生成大纲（可选接收 Agent strategy_params）
模式 2: run_knowledge_point — 只生成指定知识点的完整脚本
模式 3: run_book_script — 整本书概述（保留）
"""
import json
import time
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR
from utils.logger import log
from services.content_planner import ContentPlanner
from services.script_generator import ScriptGenerator
from services.quality_checker import QualityChecker
from services.safety_checker import SafetyChecker


class Orchestrator:
    """工作流编排器"""

    def __init__(self):
        self.planner = ContentPlanner()
        self.script_gen = ScriptGenerator()
        self.quality = QualityChecker()
        self.safety = SafetyChecker()

    # ================================================================
    # 模式 1: 只生成大纲（Agent 增强版）
    # ================================================================

    def plan_book(
        self,
        book_name: str,
        toc: str = "",
        source: str = "",
        focus: str = "",
        strategy_params: Optional[dict] = None,
        agent_context: str = "",
    ) -> dict:
        """
        生成视频选题大纲。

        当传入 strategy_params（来自 Agent 决策）时，自动将其注入到规划提示中。
        当传入 agent_context（Agent Strategy Context 文本块）时，深度注入到 planner.txt 的
        {agent_strategy_context} 占位符。
        不传参数时行为完全不变（向后兼容）。
        """
        log.title(f"[大纲规划] 《{book_name}》")
        if toc:
            log.info(f"目录: {toc}")
        if source:
            log.info(f"素材: {source}")

        # 如果提供了 Agent 策略参数，增强 focus_hint
        enhanced_focus = focus
        if strategy_params:
            strategy_hint = (
                f"\n\n[Agent 策略注入]\n"
                f"书籍分类: {strategy_params.get('category', '')}\n"
                f"推荐策略: {strategy_params.get('strategy_name', '')}\n"
                f"推荐语调: {strategy_params.get('tone', '')}\n"
                f"推荐钩子类型: {strategy_params.get('hook_type', '')}\n"
                f"结构重心: {strategy_params.get('structure_emphasis', '')}\n"
                f"视觉风格: {strategy_params.get('visual_style', '')}\n"
                f"请在规划大纲时参考以上策略，确保知识点选择与策略方向一致。"
            )
            enhanced_focus = (focus + strategy_hint) if focus else strategy_hint
            log.info(f"  已注入 Agent 策略: {strategy_params.get('strategy_name', '')}")

        if agent_context:
            log.info(f"  [OK] 已深度注入 Agent Strategy Context")

        plan = self.planner.plan(book_name, toc_text=toc, source_text=source,
                                 focus_hint=enhanced_focus,
                                 agent_context_block=agent_context)
        output_dir = OUTPUT_DIR / self._safe_name(book_name)
        self.planner.save_plan(plan, output_dir)
        self.planner.print_plan(plan)

        print(f"下一步: python main.py --book \"{book_name}\" --kp-id <ID> --script-only")
        return plan

    # ================================================================
    # 模式 2: 只生成指定知识点的完整脚本
    # ================================================================

    def run_knowledge_point(
        self,
        book_name: str,
        kp_id: int,
        full_pipeline: bool = False,
    ) -> Optional[dict]:
        """
        生成指定知识点的完整深度讲解脚本。

        流程: 加载大纲 → 查找KP → 生成脚本 → 质量审核 → 安全审核 → 保存

        Args:
            book_name: 书名
            kp_id: 知识点 ID
            full_pipeline: 如果 True，生成视频；默认 False（只生成脚本）

        用法:
          python main.py --book "毛选" --kp-id 1 --script-only
          python main.py --book "毛选" --kp-id 1 --full
        """
        # 加载大纲
        plan = self.planner.load_plan(book_name)
        if not plan:
            log.error(f"未找到大纲。请先运行: python main.py --book \"{book_name}\" --plan-only")
            return None

        # 查找知识点
        kp_info = self.planner.find_kp(plan, kp_id)
        if not kp_info:
            log.error(f"未找到知识点 #{kp_id}，请检查 ID 是否正确")
            log.info(f"可运行 python main.py --book \"{book_name}\" --plan-only 查看可选 ID")
            return None

        kp_title = kp_info.get("title", f"知识点{kp_id}")
        safe_kp_name = self._safe_name(f"kp_{kp_id:03d}_{kp_title}")[:80]
        kp_dir = OUTPUT_DIR / self._safe_name(book_name) / safe_kp_name

        log.title(f"[脚本生成] #{kp_id} {kp_title}")

        # Step 1: 生成脚本（深度注入 Agent Strategy Context）
        log.step(1, 4, "生成深度讲解脚本")
        agent_context_block = plan.get("_agent_context_block", "")
        if agent_context_block:
            log.info(f"  [OK] 已注入 Agent Strategy Context")
        script = self.script_gen.generate_knowledge_point(
            kp_info,
            agent_context_block=agent_context_block,
        )
        self.script_gen.save_script(script, kp_dir)

        full_text = script.get("full_script", "")
        log.info(f"脚本字数: {len(full_text)}")

        # Step 2: 质量审核
        log.step(2, 4, "质量审核")
        quality_result = self.quality.check(script)
        self.quality.save_result(quality_result, kp_dir)

        if not quality_result.get("passed", True):
            log.error("质量审核未通过。请检查 quality_check.json，修改后重新生成。")
            log.info(f"脚本已保存到 {kp_dir / 'script.json'}（不含安全审核版本）")
            return None

        # Step 3: 安全审核
        log.step(3, 4, "安全审核")
        safety_result = self.safety.check(script)
        safety_path = kp_dir / "safety_check.json"
        safety_path.write_text(json.dumps(safety_result, ensure_ascii=False, indent=2), encoding="utf-8")

        if safety_result.get("risk_level") in ("high", "blocked"):
            log.warn("安全审核发现问题，已记录。脚本仍然保存。")

        # Step 4: 保存安全版
        log.step(4, 4, "保存")
        safe_script = self.safety.apply_revisions(script, safety_result)
        safe_path = kp_dir / "script_safe.json"
        safe_path.write_text(json.dumps(safe_script, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"安全版脚本已保存: {safe_path}")

        # 完成
        estimated = script.get("suggested_video_length", "未知")
        log.title(f"[完成] #{kp_id} {kp_title}")
        print(f"  脚本字数: {len(full_text)}")
        print(f"  预估时长: {estimated}")
        print(f"  输出目录: {kp_dir}")
        print(f"  脚本文件: script.json")
        print(f"  安全版本: script_safe.json")
        print(f"  质量审核: quality_check.json")
        print(f"  安全审核: safety_check.json")

        if not full_pipeline:
            print(f"\n  [提示] 当前为 script_only 模式。如需生成完整视频请使用 --full。")
            print(f"  [提示] 当前脚本为长文讲解结构，如果 --full 需要先开发 script_segmenter 切分配图/配音。")

        return script

    # ================================================================
    # 模式 2.5: 批量生成知识点（Agent 多选题）
    # ================================================================

    def batch_run_knowledge_points(
        self,
        book_name: str,
        topic_configs: list,
    ) -> list:
        """
        批量生成多个知识点的脚本。

        不走 plan_book()，不依赖 knowledge_plan.json。
        每个 topic 独立创建 kp_info，独立调用 ScriptGenerator。

        Args:
            book_name: 书名
            topic_configs: [(topic_dict, agent_context_dict, agent_context_block_str), ...]
                           topic_dict 来自 TopicPool 的选题对象

        Returns:
            [{"success": True/False, "topic_id": N, "topic_title": "...",
              "kp_dir": "路径", "script": script/None, "error": "错误信息"}]
        """
        log.title(f"[批量生产] 《{book_name}》→ {len(topic_configs)} 个选题")
        results = []

        for idx, (topic, agent_context, agent_context_block) in enumerate(topic_configs, 1):
            topic_id = topic.get("topic_id", idx)
            topic_title = topic.get("topic_title", f"选题{idx}")

            log.step(idx, len(topic_configs), f"[{topic_id}] {topic_title[:40]}")

            try:
                # 构建 kp_info（映射 topic 字段到 ScriptGenerator 所需字段）
                kp_info = self._topic_to_kp_info(book_name, topic, topic_id)
                safe_kp_name = self._safe_name(f"agent_kp_{topic_id:02d}_{topic_title}")[:80]
                kp_dir = OUTPUT_DIR / self._safe_name(book_name) / safe_kp_name
                kp_dir.mkdir(parents=True, exist_ok=True)

                # 生成脚本（深度注入 Agent Strategy Context）
                if agent_context_block:
                    log.info(f"  [OK] 已注入 Agent Strategy Context")
                script = self.script_gen.generate_knowledge_point(
                    kp_info,
                    agent_context_block=agent_context_block,
                )
                self.script_gen.save_script(script, kp_dir)

                # 质量审核
                quality_result = self.quality.check(script)
                self.quality.save_result(quality_result, kp_dir)

                qc_passed = quality_result.get("passed", True)

                # 安全审核
                if qc_passed:
                    safety_result = self.safety.check(script)
                    safety_path = kp_dir / "safety_check.json"
                    safety_path.write_text(json.dumps(safety_result, ensure_ascii=False, indent=2), encoding="utf-8")

                    if safety_result.get("risk_level") not in ("high", "blocked"):
                        safe_script = self.safety.apply_revisions(script, safety_result)
                        safe_path = kp_dir / "script_safe.json"
                        safe_path.write_text(json.dumps(safe_script, ensure_ascii=False, indent=2), encoding="utf-8")

                # 保存 agent_context 到 kp 目录
                ctx_path = kp_dir / "_agent_context.json"
                ctx_path.write_text(json.dumps(agent_context, ensure_ascii=False, indent=2), encoding="utf-8")

                results.append({
                    "success": True,
                    "topic_id": topic_id,
                    "topic_title": topic_title,
                    "kp_dir": str(kp_dir),
                    "script_words": len(script.get("full_script", "")),
                    "qc_passed": qc_passed,
                })

                log.success(f"  [OK] 完成: {topic_title[:40]} → {kp_dir}")

            except Exception as e:
                import traceback
                error_msg = f"{e}\n{traceback.format_exc()[:200]}"
                log.error(f"  [FAIL] 失败: {topic_title[:40]} → {str(e)[:60]}")
                results.append({
                    "success": False,
                    "topic_id": topic_id,
                    "topic_title": topic_title,
                    "kp_dir": "",
                    "error": str(e)[:200],
                })
                # 一个选题失败，继续下一个

        success_count = sum(1 for r in results if r.get("success"))
        log.title(f"[批量生产] 完成: {success_count}/{len(topic_configs)} 成功")
        return results

    def _topic_to_kp_info(self, book_name: str, topic: dict, topic_id: int) -> dict:
        """将选题池中的 topic 转换为 ScriptGenerator 可用的 kp_info 格式"""
        return {
            "id": topic_id,
            "book_name": book_name,
            "chapter": "Agent选题",
            "chapter_summary": f"Agent高潜力选题 #{topic_id}",
            "title": topic.get("topic_title", f"选题{topic_id}"),
            "original_meaning": topic.get("core_insight", ""),
            "core_problem": (topic.get("core_insight", "")[:100] or "一个值得了解的认知"),
            "why_useful": topic.get("why_attractive", topic.get("target_audience", "")),
            "universal_relevance": topic.get("target_audience", topic.get("why_attractive", "")),
            "source_scope": "整书分析",
            "suggested_video_length": "8-12分钟",
            "length_reason": "中等长度，适合深入讲解一个核心观点",
            "specific_book_content": [],
            "hook_idea": topic.get("hook_type", ""),
            "presentation_approach": topic.get("content_angle", ""),
        }

    # ================================================================
    # 模式 3: 整本书概述（保留）
    # ================================================================

    def run_book_script(
        self,
        book_name: str,
        num_segments: int = 8,
        image_style: str = "",
        angle: str = "auto",
        dry_run: bool = False,
        skip_safety: bool = False,
    ) -> Optional[Path]:
        """
        整本书概述模式。不推荐用于知识点深度讲解。

        用法: python main.py --book "三体"
        """
        log.title(f"[概述] 《{book_name}》")
        output_dir = OUTPUT_DIR / self._safe_name(book_name)

        log.step(1, 2, "生成概述脚本")
        script = self.script_gen.generate_book_script(book_name, num_segments, image_style, angle)
        self.script_gen.save_script(script, output_dir)

        if dry_run:
            log.success("脚本生成完毕（dry-run）")
            return None

        if not skip_safety:
            log.step(2, 2, "安全审核")
            check = self.safety.check(script)
            risk = check.get("risk_level", "safe")
            if risk in ("high", "blocked"):
                log.warn(f"安全风险: {risk}")

        log.success("概述脚本完成")
        return None

    # ================================================================
    # 工具
    # ================================================================

    def _safe_name(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in " _-()（）")
        return safe.strip() or "unnamed"
