"""
Pipeline 引擎 — 管理完整工作流的分步执行

7 步 Pipeline:
  1. plan_book       → knowledge_plan.json
  2. generate_script → script.json + quality_check.json + safety_check.json
  3. content_units   → content_units.json
  4. visual_beats    → visual_beats.json
  5. image_prompts   → image_prompts.json
"""
import json
import time
import traceback
from pathlib import Path
from datetime import datetime

from config import OUTPUT_DIR, IMAGE_STYLE
from utils.logger import log

# ---- Pipeline 状态常量 ----
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# ---- 步骤进度记录 ----
def write_step_progress(kp_dir: Path, step_id: str, progress: int, message: str):
    """写入步骤实时进度（供前端轮询）"""
    import json as _json
    from datetime import datetime as _dt
    if not kp_dir:
        return
    try:
        kp_dir = Path(kp_dir)
        kp_dir.mkdir(parents=True, exist_ok=True)
        prog_path = kp_dir / "_step_progress.json"
        data = {}
        if prog_path.exists():
            try: data = _json.loads(prog_path.read_text("utf-8"))
            except: data = {}
        data[step_id] = {
            "progress": min(100, max(0, progress)),
            "message": message[:200],
            "updated_at": _dt.now().isoformat(),
        }
        prog_path.write_text(_json.dumps(data, ensure_ascii=False), "utf-8")
    except Exception:
        pass  # 进度记录不应该阻塞任务

# ---- 步骤定义 ----
PIPELINE_STEPS = [
    {
        "id": "plan_book",
        "name": "生成选题大纲",
        "description": "将书本拆解为知识点结构",
        "output_file": "../knowledge_plan.json",
        "depends_on": [],
    },
    {
        "id": "generate_hooks",
        "name": "生成钩子候选",
        "description": "量产10条钩子→选定主钩子（前3秒留人）",
        "output_file": "hook_candidates.json",
        "depends_on": ["plan_book"],
    },
    {
        "id": "generate_script",
        "name": "生成知识点脚本",
        "description": "深度讲解脚本 + 质量审核 + 安全审核",
        "output_files": ["script.json", "quality_check.json", "safety_check.json"],
        "depends_on": ["plan_book"],
    },
    {
        "id": "content_units",
        "name": "内容单元切分",
        "description": "将完整脚本切分为内容单元",
        "output_file": "content_units.json",
        "depends_on": ["generate_script"],
    },
    {
        "id": "visual_beats",
        "name": "画面点提取",
        "description": "基于内容单元判断哪里需要画面",
        "output_file": "visual_beats.json",
        "depends_on": ["content_units"],
    },
    {
        "id": "image_prompts",
        "name": "图片提示词生成",
        "description": "为每个画面节点生成图片提示词",
        "output_file": "image_prompts.json",
        "depends_on": ["visual_beats"],
    },
    {
        "id": "generate_images",
        "name": "生成图片",
        "description": "调用 GPT-Image API 生成配图 (16:9)",
        "output_file": "images/beat_001.png",
        "depends_on": ["image_prompts"],
    },
    {
        "id": "generate_audio",
        "name": "生成配音",
        "description": "将脚本转为语音 MP3",
        "output_file": "audio/seg_01.mp3",
        "depends_on": ["generate_script"],
    },
    {
        "id": "timeline_assembly",
        "name": "时间线组装",
        "description": "将音频段与画面点按时间对齐",
        "output_file": "timeline.json",
        "depends_on": ["visual_beats", "generate_audio"],
    },
    {
        "id": "generate_subtitles",
        "name": "生成字幕",
        "description": "从脚本+音频时间生成观众字幕 SRT + 标题叠加",
        "output_file": "subtitles.srt",
        "depends_on": ["timeline_assembly"],
    },
    {
        "id": "compose_final_video",
        "name": "合成最终视频",
        "description": "图片+音频+字幕+标题 → 最终 MP4",
        "output_file": "final.mp4",
        "depends_on": ["generate_subtitles", "generate_images"],
    },
]


class PipelineEngine:
    """管理 Pipeline 执行"""

    def __init__(self):
        self._state = {}  # key: "book_name/kp_id/step_id" → status dict

    # ================================================================
    # 状态管理
    # ================================================================

    def get_state(self, book_name: str, kp_id: int = 0, step_id: str = "") -> dict:
        """获取步骤状态"""
        key = f"{book_name}/{kp_id}/{step_id}" if step_id else f"{book_name}/{kp_id}"
        return self._state.get(key, {
            "status": STATUS_PENDING,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "output": None,
        })

    def _set_state(self, book_name: str, kp_id: int, step_id: str, **kwargs):
        key = f"{book_name}/{kp_id}/{step_id}"
        if key not in self._state:
            self._state[key] = {"status": STATUS_PENDING, "started_at": None, "finished_at": None, "error": None, "output": None}
        self._state[key].update(kwargs)

    def get_pipeline_status(self, book_name: str, kp_id: int = 0) -> list[dict]:
        """获取完整 Pipeline 状态"""
        result = []
        for step in PIPELINE_STEPS:
            state = self.get_state(book_name, kp_id, step["id"])
            result.append({**step, **state})
        return result

    # ================================================================
    # 步骤1: 规划大纲
    # ================================================================

    def run_plan_book(self, book_name: str, toc: str = "", source: str = "",
                       focus: str = "") -> dict:
        """执行：生成选题大纲（每本书3-4个知识点），自动注入增长信号"""
        step_id = "plan_book"
        kp_dir = OUTPUT_DIR / self._safe_name(book_name)
        write_step_progress(kp_dir, step_id, 0, "正在加载增长信号...")
        self._set_state(book_name, 0, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            from services.content_planner import ContentPlanner
            from services.hook_generator import HookGenerator

            # 读取增长信号并注入到 focus
            growth_signals = HookGenerator.build_growth_signals()
            growth_context = ""
            if growth_signals and "暂无" not in growth_signals:
                growth_context = (
                    "\n\n## 📈 增长信号（历史验证的高表现策略）\n"
                    + growth_signals
                    + "\n\n请参考以上历史数据进行选题规划，优先使用已验证的高表现结构和开场类型。"
                )
                log.info(f"  已注入增长信号到规划阶段 ({len(growth_signals)} 字符)")
                write_step_progress(kp_dir, step_id, 5, "增长信号已加载")

            enhanced_focus = focus
            if growth_context:
                enhanced_focus = (focus + growth_context) if focus else growth_context

            write_step_progress(kp_dir, step_id, 10, "正在调用 LLM 生成大纲...")
            planner = ContentPlanner()
            plan = planner.plan(book_name, toc_text=toc, source_text=source,
                               focus_hint=enhanced_focus,
                               agent_context_block=growth_context)
            write_step_progress(kp_dir, step_id, 70, "大纲已生成，正在保存...")

            output_dir = OUTPUT_DIR / self._safe_name(book_name)
            planner.save_plan(plan, output_dir)

            total = plan.get("total_knowledge_points", sum(
                len(s.get("knowledge_points", [])) for s in plan.get("content_outline", [])
            ))

            result = {
                "success": True,
                "total_kps": total,
                "sections": len(plan.get("content_outline", [])),
                "output_file": str(output_dir / "knowledge_plan.json"),
                "kps": self._extract_kp_list(plan),
            }
            write_step_progress(kp_dir, step_id, 100, "大纲生成完成")
            self._set_state(book_name, 0, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result

        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            write_step_progress(kp_dir, step_id, 0, f"失败: {str(e)[:100]}")
            self._set_state(book_name, 0, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    # ================================================================
    # 步骤1.5: 生成钩子候选
    # ================================================================

    def run_generate_hooks(self, book_name: str, kp_id: int) -> dict:
        """执行：生成 10 条钩子候选 + 自动选最佳"""
        step_id = "generate_hooks"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            from services.hook_generator import HookGenerator
            from services.content_planner import ContentPlanner

            # 加载大纲 + 查找 KP
            planner = ContentPlanner()
            plan = planner.load_plan(book_name)
            if not plan:
                raise ValueError("未找到大纲，请先运行第1步")

            kp_info = planner.find_kp(plan, kp_id)
            if not kp_info:
                raise ValueError(f"未找到知识点 #{kp_id}")

            kp_dir = self._find_kp_dir(book_name, kp_id) or (
                OUTPUT_DIR / self._safe_name(book_name)
                / f"kp_{kp_id:03d}_{self._safe_name(kp_info.get('title', ''))[:50]}"
            )
            kp_dir.mkdir(parents=True, exist_ok=True)
            write_step_progress(kp_dir, step_id, 10, "正在生成 10 条候选钩子...")

            gen = HookGenerator()

            # 读取增长信号
            growth_signals = HookGenerator.build_growth_signals()
            if growth_signals:
                log.info(f"  已加载增长信号 ({len(growth_signals)} 字符)")

            # 幂等检查：已生成则跳过
            existing = gen.load_candidates(kp_dir)
            if existing.get("candidates") and len(existing["candidates"]) >= 5:
                hooks = existing["candidates"]
                log.info(f"  幂等跳过：已有 {len(hooks)} 条候选钩子")
                write_step_progress(kp_dir, step_id, 50, f"已有 {len(hooks)} 条候选钩子，跳过生成")
            else:
                hooks = gen.generate_hooks(kp_info, growth_signals=growth_signals)
                if not hooks:
                    raise RuntimeError("钩子生成为空")
                gen.save_candidates(hooks, kp_dir, kp_info)
                write_step_progress(kp_dir, step_id, 60, f"已生成 {len(hooks)} 条候选钩子")

            # 自动评分选最佳（如果没有选定过）
            if not existing.get("primary_hook"):
                write_step_progress(kp_dir, step_id, 70, "正在评分并选定最佳钩子...")
                result = gen.auto_select(kp_dir, kp_info)
                primary = result.get("primary_hook", hooks[0] if hooks else "")
            else:
                primary = existing["primary_hook"]
                write_step_progress(kp_dir, step_id, 70, "已有选定钩子，跳过评分")

            result = {
                "success": True,
                "kp_id": kp_id,
                "total_candidates": len(hooks),
                "primary_hook": primary[:100] if primary else "",
                "has_selected": bool(primary),
                "kp_dir": str(kp_dir),
            }
            write_step_progress(kp_dir, step_id, 100, "钩子生成完成")
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result

        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if kp_dir:
                write_step_progress(kp_dir, step_id, 0, f"失败: {str(e)[:100]}")
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    # ================================================================
    # 步骤2: 生成脚本 + 审核
    # ================================================================

    def run_generate_script(self, book_name: str, kp_id: int, mode: str = "normal") -> dict:
        """执行：生成知识点脚本。mode: normal | worldcup"""
        step_id = "generate_script"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            from services.script_generator import ScriptGenerator
            from services.quality_checker import QualityChecker
            from services.safety_checker import SafetyChecker
            from services.content_planner import ContentPlanner

            # 加载大纲 + 查找 KP
            planner = ContentPlanner()
            plan = planner.load_plan(book_name)
            if not plan:
                raise ValueError("未找到大纲，请先运行第1步")

            kp_info = planner.find_kp(plan, kp_id)
            if not kp_info:
                raise ValueError(f"未找到知识点 #{kp_id}")

            kp_dir = self._find_kp_dir(book_name, kp_id) or (OUTPUT_DIR / self._safe_name(book_name) / f"kp_{kp_id:03d}_{self._safe_name(kp_info.get('title', ''))[:50]}")
            kp_dir.mkdir(parents=True, exist_ok=True)
            write_step_progress(kp_dir, step_id, 5, "正在生成脚本结构...")

            # 加载主钩子（如有）
            primary_hook = ""
            try:
                from services.hook_generator import HookGenerator
                hg = HookGenerator()
                primary_hook = hg.get_primary_hook(kp_dir)
                if primary_hook:
                    kp_info["primary_hook"] = primary_hook
                    log.info(f"  已注入主钩子: {primary_hook[:80]}...")
                    write_step_progress(kp_dir, step_id, 8, f"主钩子已注入")
            except Exception as e:
                log.warn(f"  钩子加载失败（跳过）: {e}")

            # 生成脚本（深度注入 Agent Strategy Context + 主钩子）
            agent_context_block = plan.get("_agent_context_block", "")
            gen = ScriptGenerator()
            write_step_progress(kp_dir, step_id, 15, "正在调用 LLM 撰写脚本（可能需要1-3分钟）...")
            script = gen.generate_knowledge_point(kp_info, mode=mode,
                                                  agent_context_block=agent_context_block)

            # 在脚本中记录主钩子
            if primary_hook and "primary_hook" not in script:
                script["primary_hook"] = primary_hook

            # 保存目录
            kp_dir.mkdir(parents=True, exist_ok=True)
            gen.save_script(script, kp_dir)
            write_step_progress(kp_dir, step_id, 60, "脚本已生成，正在质量审核...")

            # 质量审核
            qc = QualityChecker()
            qc_result = qc.check(script)
            qc.save_result(qc_result, kp_dir)
            write_step_progress(kp_dir, step_id, 80, "质量审核完成，正在安全审核...")

            qc_passed = qc_result.get("passed", True)
            qc_score = qc_result.get("overall_score", 0)

            # 安全审核
            sc_result = {"passed": True, "risk_level": "skipped"}
            if qc_passed and qc_score >= 60:
                sc = SafetyChecker()
                sc_result = sc.check(script)
                sc_path = kp_dir / "safety_check.json"
                sc_path.write_text(json.dumps(sc_result, ensure_ascii=False, indent=2), encoding="utf-8")

            result = {
                "success": True,
                "kp_id": kp_id,
                "script_words": len(script.get("full_script", "")),
                "estimated_length": script.get("estimated_video_length", ""),
                "qc_passed": qc_passed,
                "qc_score": qc_score,
                "sc_risk": sc_result.get("risk_level", "?"),
                "kp_dir": str(kp_dir),
                "output_files": {
                    "script": str(kp_dir / "script.json"),
                    "quality_check": str(kp_dir / "quality_check.json"),
                    "safety_check": str(kp_dir / "safety_check.json") if qc_passed else None,
                },
            }
            write_step_progress(kp_dir, step_id, 100, "脚本生成完成")
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result

        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            write_step_progress(kp_dir, step_id, 0, f"失败: {str(e)[:100]}")
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    # ================================================================
    # 步骤3-5: 视觉工作流（合并执行）
    # ================================================================

    def run_content_units(self, book_name: str, kp_id: int) -> dict:
        """执行：内容单元切分"""
        kp_dir = self._find_kp_dir(book_name, kp_id)
        write_step_progress(kp_dir, step_id:="content_units", 30, "正在切分内容单元...")
        result = self._run_visual_layer(book_name, kp_id, "content_units", "ContentUnitSegmenter")
        write_step_progress(kp_dir, step_id, 100 if result.get("success") else 0,
                            "内容单元切分完成" if result.get("success") else f"失败: {result.get('error','')[:100]}")
        return result

    def run_content_units_from_draft(self, book_name: str, draft_dir_str: str) -> dict:
        """在草稿目录上运行内容单元切分"""
        from services.content_unit_segmenter import ContentUnitSegmenter
        from pathlib import Path
        step_id = "content_units"
        kp_dir = Path(draft_dir_str)
        self._set_state(book_name, 999, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())
        try:
            seg = ContentUnitSegmenter()
            result_data = seg.run(kp_dir)
            result = {"success": True, "output_file": str(result_data) if result_data else "", "kp_dir": str(kp_dir)}
            self._set_state(book_name, 999, step_id, status=STATUS_COMPLETED, finished_at=datetime.now().isoformat(), output=result)
            return result
        except Exception as e:
            error = str(e) + chr(10) + traceback.format_exc()
            self._set_state(book_name, 999, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_visual_beats(self, book_name: str, kp_id: int) -> dict:
        """执行：画面点提取"""
        return self._run_visual_layer(book_name, kp_id, "visual_beats", "VisualBeatExtractor")

    def run_image_prompts(self, book_name: str, kp_id: int) -> dict:
        """执行：图片提示词生成"""
        return self._run_visual_layer(book_name, kp_id, "image_prompts", "ImagePromptGenerator")

    def run_generate_images(self, book_name: str, kp_id: int, max_images: int = 0) -> dict:
        """执行：生成图片 — generate_images() 内部已处理所有重试

        规则（由 ImageGenerator.generate_images 执行）：
          - 第一轮生成全部图片
          - 后续每轮只重试失败图片，跳过已成功的
          - 每张图片连续失败 4 次 → 标记 failed_permanent，停止重试
          - Hard Error → 立即终止
        """
        step_id = "generate_images"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError("未找到知识点目录")

            from services.image_generator import ImageGenerator
            gen = ImageGenerator()

            result = gen.generate_images(kp_dir, max_images=max_images)

            if not result.get("success"):
                raise RuntimeError(result.get("error", "未知错误"))

            total = result.get("total", 0)
            perm = result.get("permanent_failed", 0)
            failed = result.get("failed", 0)
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result

        except Exception as e:
            import traceback
            error = f"{e}\n{traceback.format_exc()}"
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_retry_images_until_done(self, book_name: str, kp_id: int) -> dict:
        """「重试失败图片」按钮 — 仅重试可重试的失败图片，跳过 permanently failed"""
        kp_id = int(kp_id)
        kp_dir = self._find_kp_dir(book_name, kp_id)
        if not kp_dir:
            return {"success": False, "error": "未找到知识点目录"}

        from services.image_generator import ImageGenerator
        gen = ImageGenerator()
        result = gen.retry_failed_only(kp_dir)
        return result

    async def run_generate_audio(self, book_name: str, kp_id: int) -> dict:
        """执行：生成配音"""
        step_id = "generate_audio"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError(f"未找到知识点目录")
            write_step_progress(kp_dir, step_id, 10, "正在读取脚本...")

            # 读脚本
            script = None
            for n in ["script_edited.json", "script_safe.json", "script.json"]:
                script = self._read_json(kp_dir / n)
                if script:
                    break
            if not script:
                raise ValueError("未找到脚本文件")

            full_text = script.get("full_script", "")
            if not full_text:
                raise ValueError("脚本中无 full_script")
            write_step_progress(kp_dir, step_id, 20, "正在拆分段落...")

            # 按自然段拆分
            raw_paras = [p.strip() for p in full_text.split("\n\n") if p.strip()]
            MAX_SEGMENTS = 50
            if len(raw_paras) > MAX_SEGMENTS:
                total_chars = sum(len(p) for p in raw_paras)
                target = total_chars / MAX_SEGMENTS
                paragraphs = []
                buf = ""
                for p in raw_paras:
                    if buf and len(buf) + len(p) > target * 1.3:
                        paragraphs.append(buf.strip())
                        buf = p
                    else:
                        buf = (buf + "\n" + p) if buf else p
                if buf:
                    paragraphs.append(buf.strip())
                log.info(f"段落合并: {len(raw_paras)} → {len(paragraphs)} 段")
            else:
                paragraphs = raw_paras
            segments = [{"index": i+1, "text": p} for i, p in enumerate(paragraphs)]

            # 清理旧音频
            import shutil
            old_audio = kp_dir / "audio"
            if old_audio.exists():
                shutil.rmtree(old_audio)

            # 生成配音（根据配置选引擎）
            tts_engine = self._tts_engine()
            write_step_progress(kp_dir, step_id, 30, f"正在生成配音（共{len(segments)}段）...")
            segments = await tts_engine.generate(segments, kp_dir)
            write_step_progress(kp_dir, step_id, 100, "配音生成完成")

            total_duration = sum(s.get("duration", 0) for s in segments)
            result = {
                "success": True,
                "kp_id": kp_id,
                "segments": len(segments),
                "total_duration_seconds": round(total_duration, 1),
                "total_duration": f"{int(total_duration // 60)}分{int(total_duration % 60)}秒",
                "output_dir": str(kp_dir / "audio"),
            }
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result

        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if kp_dir: write_step_progress(kp_dir, step_id, 0, f"失败: {str(e)[:100]}")
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_timeline_assembly(self, book_name: str, kp_id: int) -> dict:
        """执行：时间线组装"""
        step_id = "timeline_assembly"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError("未找到知识点目录")
            from services.timeline_assembler import TimelineAssembler
            ta = TimelineAssembler()
            data = ta.assemble(kp_dir)
            ta.save(data, kp_dir)
            result = {
                "success": True, "kp_id": kp_id,
                "beats": data["total_beats"],
                "audio_segs": data["total_audio_segments"],
                "total_duration": data["total_duration"],
            }
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result
        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_export_jianying(self, book_name: str, kp_id: int) -> dict:
        """执行：剪映导出（保留为可选工具，不在主 pipeline 中）"""
        step_id = "export_jianying"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError("未找到知识点目录")
            from services.jianying_exporter import JianyingExporter
            je = JianyingExporter()
            result_data = je.run(kp_dir)
            result = {"success": True, "kp_id": kp_id, **result_data}
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result
        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_generate_subtitles(self, book_name: str, kp_id: int) -> dict:
        """执行：生成字幕"""
        step_id = "generate_subtitles"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError("未找到知识点目录")
            from services.subtitle_generator import SubtitleGenerator
            sg = SubtitleGenerator()
            result_data = sg.generate(kp_dir)
            result = {
                "success": True,
                "kp_id": kp_id,
                "subtitles_count": result_data.get("subtitles_count", 0),
                "title_overlays_count": result_data.get("title_overlays_count", 0),
                "srt_path": result_data.get("srt_path", ""),
                "title_overlays_path": result_data.get("title_overlays_path", ""),
            }
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result
        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_compose_final_video(self, book_name: str, kp_id: int) -> dict:
        """执行：合成最终视频"""
        step_id = "compose_final_video"
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError("未找到知识点目录")
            write_step_progress(kp_dir, step_id, 10, "正在加载视频素材...")
            from services.final_video_composer import FinalVideoComposer
            fvc = FinalVideoComposer()
            write_step_progress(kp_dir, step_id, 30, "正在合成视频（图片+配音+字幕）可能需要几分钟...")
            output_path = fvc.compose(kp_dir)
            write_step_progress(kp_dir, step_id, 100, "视频合成完成")
            file_size_mb = round(output_path.stat().st_size / (1024 * 1024), 1)
            result = {
                "success": True,
                "kp_id": kp_id,
                "output_path": str(output_path),
                "file_size_mb": file_size_mb,
            }
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result
        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if kp_dir: write_step_progress(kp_dir, step_id, 0, f"失败: {str(e)[:100]}")
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def run_visual_pipeline(self, book_name: str, kp_id: int) -> dict:
        """一键执行视觉链路（步骤3-5）"""
        results = {}
        for step_key, method in [("content_units", self.run_content_units),
                                  ("visual_beats", self.run_visual_beats),
                                  ("image_prompts", self.run_image_prompts),
                                  ("generate_images", self.run_generate_images)]:
            r = method(book_name, kp_id)
            results[step_key] = r
            if not r.get("success"):
                break
        return {"success": all(r.get("success") for r in results.values()), "steps": results}

    # ================================================================
    # 全部 Pipeline（步骤1-9）
    # ================================================================

    async def run_full_pipeline(self, book_name: str, kp_id: int = 0) -> dict:
        """一键执行完整 Pipeline（步骤1-9），已完成的自动跳过"""
        import asyncio
        results = {}

        # 扫描各步骤当前文件状态
        file_status = self.detect_file_status(book_name, kp_id)

        def _done(step_id):
            return file_status.get(step_id, {}).get("status") == STATUS_COMPLETED

        # 第1步：规划
        if not _done("plan_book"):
            r1 = self.run_plan_book(book_name)
            results["plan_book"] = r1
            if not r1.get("success"):
                return {"success": False, "steps": results, "error": "规划失败"}
        else:
            results["plan_book"] = {"success": True, "skipped": True, "reason": "已存在"}

        if kp_id == 0:
            results["_action"] = "请选择知识点 ID 继续"
            return {"success": True, "steps": results}

        # 第1.5步：生成钩子
        if not _done("generate_hooks"):
            r_hook = self.run_generate_hooks(book_name, kp_id)
            results["generate_hooks"] = r_hook
            if not r_hook.get("success"):
                # 钩子失败不阻塞流程（有默认开场白兜底）
                results["generate_hooks"]["_warning"] = "钩子生成失败，将使用默认开场白"
        else:
            results["generate_hooks"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第2步：生成脚本
        if not _done("generate_script"):
            from pathlib import Path as _P
            mode_path = _P(__file__).parent.parent / "script_mode.txt"
            mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "normal"
            r2 = self.run_generate_script(book_name, kp_id, mode=mode)
            results["generate_script"] = r2
            if not r2.get("success"):
                return {"success": False, "steps": results}
        else:
            results["generate_script"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第3步：内容单元
        if not _done("content_units"):
            r3 = self.run_content_units(book_name, kp_id)
            results["content_units"] = r3
            if not r3.get("success"):
                return {"success": False, "steps": results}
        else:
            results["content_units"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第4步：画面点
        if not _done("visual_beats"):
            r4 = self.run_visual_beats(book_name, kp_id)
            results["visual_beats"] = r4
            if not r4.get("success"):
                return {"success": False, "steps": results}
        else:
            results["visual_beats"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第5步：图片提示词
        if not _done("image_prompts"):
            r5 = self.run_image_prompts(book_name, kp_id)
            results["image_prompts"] = r5
            if not r5.get("success"):
                return {"success": False, "steps": results}
        else:
            results["image_prompts"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第5.5步：生成图片
        if not _done("generate_images"):
            r55 = self.run_generate_images(book_name, kp_id)
            results["generate_images"] = r55
            if not r55.get("success"):
                return {"success": False, "steps": results}
        else:
            results["generate_images"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第6步：生成配音
        if not _done("generate_audio"):
            r6 = await self.run_generate_audio(book_name, kp_id)
            results["generate_audio"] = r6
            if not r6.get("success"):
                results["_warning"] = "配音生成失败，后续步骤已跳过"
                return {"success": False, "steps": results}
        else:
            results["generate_audio"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第7步：时间线组装
        if not _done("timeline_assembly"):
            r7 = self.run_timeline_assembly(book_name, kp_id)
            results["timeline_assembly"] = r7
            if not r7.get("success"):
                results["_warning"] = "时间线组装失败，后续步骤已跳过"
                return {"success": False, "steps": results}
        else:
            results["timeline_assembly"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第8步：生成字幕
        if not _done("generate_subtitles"):
            r8 = self.run_generate_subtitles(book_name, kp_id)
            results["generate_subtitles"] = r8
            if not r8.get("success"):
                results["_warning"] = "字幕生成失败，后续步骤已跳过"
                return {"success": False, "steps": results}
        else:
            results["generate_subtitles"] = {"success": True, "skipped": True, "reason": "已存在"}

        # 第9步：合成最终视频
        if not _done("compose_final_video"):
            r9 = self.run_compose_final_video(book_name, kp_id)
            results["compose_final_video"] = r9
        else:
            results["compose_final_video"] = {"success": True, "skipped": True, "reason": "已存在"}

        all_ok = all(r.get("success") for r in results.values())
        return {"success": all_ok, "steps": results}

    # ================================================================
    # 工具
    # ================================================================

    def _run_visual_layer(self, book_name: str, kp_id: int, step_id: str, class_name: str) -> dict:
        """通用视觉层执行"""
        kp_id = int(kp_id)
        self._set_state(book_name, kp_id, step_id, status=STATUS_RUNNING, started_at=datetime.now().isoformat())

        try:
            module = __import__(f"services.{self._snake_case(class_name)}", fromlist=[class_name])
            cls = getattr(module, class_name)
            instance = cls()

            kp_dir = self._find_kp_dir(book_name, kp_id)
            if not kp_dir:
                raise ValueError(f"未找到知识点目录 kp_{kp_id:03d}")

            step_labels = {"content_units": "正在切分内容单元", "visual_beats": "正在提取画面点",
                          "image_prompts": "正在生成图片提示词"}
            write_step_progress(kp_dir, step_id, 30, step_labels.get(step_id, "正在执行..."))
            path = instance.run(kp_dir)
            write_step_progress(kp_dir, step_id, 100, f"{step_labels.get(step_id, '步骤')}完成")

            result = {
                "success": True,
                "output_file": str(path),
                "kp_dir": str(kp_dir),
            }
            self._set_state(book_name, kp_id, step_id, status=STATUS_COMPLETED,
                            finished_at=datetime.now().isoformat(), output=result)
            return result

        except Exception as e:
            error = f"{e}\n{traceback.format_exc()}"
            kp_dir = self._find_kp_dir(book_name, kp_id)
            if kp_dir:
                write_step_progress(kp_dir, step_id, 0, f"失败: {str(e)[:100]}")
            self._set_state(book_name, kp_id, step_id, status=STATUS_FAILED, error=error)
            return {"success": False, "error": str(e)}

    def _find_kp_dir(self, book_name: str, kp_id: int) -> Path | None:
        """查找知识点目录（优先用 knowledge_plan.json 中的 kp_dir）"""
        book_dir = OUTPUT_DIR / self._safe_name(book_name)
        if not book_dir.exists():
            return None

        # 从 knowledge_plan.json 读取精确 kp_dir（统一数据源）
        plan_path = book_dir / "knowledge_plan.json"
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                for sec in plan.get("content_outline", []):
                    for kp in sec.get("knowledge_points", []):
                        if kp.get("id") == kp_id:
                            kp_dir = kp.get("kp_dir", "")
                            if kp_dir and Path(kp_dir).exists():
                                return Path(kp_dir)
            except Exception:
                pass
        prefix = f"kp_{int(kp_id):03d}"
        matches = sorted(book_dir.glob(f"{prefix}*"))
        if matches:
            return matches[0]

        # Agent KP 兼容：kp_id=101 → agent_kp_01_*（优先选有 script.json 的）
        if kp_id >= 100:
            topic_id = kp_id - 100
            alt_prefix = f"agent_kp_{topic_id:02d}_"
            alt_matches = sorted(book_dir.glob(f"{alt_prefix}*"))
            if alt_matches:
                # 优先返回有 script.json 的目录，跳过空目录
                for m in alt_matches:
                    if (m / "script.json").exists():
                        return m
                return alt_matches[0]

        return None

    def detect_file_status(self, book_name: str, kp_id: int = 0) -> dict:
        """
        根据 output 目录已有文件推断每个步骤的状态。
        文件存在 = completed，文件不存在 = pending。
        """
        steps_status = {}

        # 步骤1: plan_book → knowledge_plan.json（在 book 目录）
        plan_path = OUTPUT_DIR / self._safe_name(book_name) / "knowledge_plan.json"
        steps_status["plan_book"] = {
            "status": STATUS_COMPLETED if plan_path.exists() else STATUS_PENDING,
            "output_file": str(plan_path) if plan_path.exists() else None,
        }
        if plan_path.exists():
            try:
                # 使用 ContentPlanner.load_plan 而非 json.loads，确保 core_insight 格式被标准化
                from services.content_planner import ContentPlanner
                planner = ContentPlanner()
                plan = planner.load_plan(book_name)
                if plan:
                    steps_status["plan_book"]["kps"] = self._extract_kp_list(plan)
                    steps_status["plan_book"]["total_kps"] = plan.get("total_knowledge_points", 1)
            except Exception:
                pass

        if kp_id <= 0:
            return steps_status

        # 查找 KP 目录
        kp_dir = self._find_kp_dir(book_name, kp_id)
        if not kp_dir:
            for step_id in ["generate_hooks", "generate_script", "content_units", "visual_beats", "image_prompts"]:
                steps_status[step_id] = {"status": STATUS_PENDING}
            return steps_status

        def _exists(*names):
            return any((kp_dir / n).exists() for n in names)

        # 步骤1.5: generate_hooks → hook_candidates.json
        hooks_exists = (kp_dir / "hook_candidates.json").exists()
        has_primary = False
        hook_text = ""
        if hooks_exists:
            try:
                hc = json.loads((kp_dir / "hook_candidates.json").read_text("utf-8"))
                has_primary = bool(hc.get("primary_hook"))
                hook_text = (hc.get("primary_hook") or "")[:80]
            except Exception:
                pass
        steps_status["generate_hooks"] = {
            "status": STATUS_COMPLETED if hooks_exists and has_primary else (STATUS_RUNNING if hooks_exists else STATUS_PENDING),
            "has_hooks": hooks_exists,
            "has_primary": has_primary,
            "primary_hook": hook_text,
        }

        # 步骤2: generate_script → script.json / script_safe.json / script_edited.json
        script_exists = _exists("script.json", "script_safe.json", "script_edited.json")
        qc_exists = (kp_dir / "quality_check.json").exists()
        sc_exists = (kp_dir / "safety_check.json").exists()
        steps_status["generate_script"] = {
            "status": STATUS_COMPLETED if script_exists else STATUS_PENDING,
            "has_script": script_exists,
            "has_qc": qc_exists,
            "has_sc": sc_exists,
        }
        if script_exists:
            for n in ["script_edited.json", "script_safe.json", "script.json"]:
                s = self._read_json(kp_dir / n)
                if s:
                    steps_status["generate_script"]["script_words"] = len(s.get("full_script", ""))
                    steps_status["generate_script"]["script_title"] = s.get("knowledge_point", "")
                    break

        # 步骤3-5: 视觉层
        for step_id, filename in [("content_units", "content_units.json"),
                                   ("visual_beats", "visual_beats.json"),
                                   ("image_prompts", "image_prompts.json")]:
            path = kp_dir / filename
            if path.exists():
                steps_status[step_id] = {"status": STATUS_COMPLETED, "output_file": str(path)}
                # 检查 image_prompts 的 API 状态
                if step_id == "image_prompts":
                    ip = self._read_json(path)
                    if ip:
                        items = ip.get("items", [])
                        waiting = sum(1 for i in items if i.get("image_status") == "waiting_api")
                        generated = sum(1 for i in items if i.get("image_status") == "generated")
                        steps_status[step_id]["total_prompts"] = ip.get("total_prompts", 0)
                        steps_status[step_id]["waiting_api"] = waiting
                        steps_status[step_id]["generated"] = generated
                        if waiting > 0 and generated == 0:
                            steps_status[step_id]["api_status"] = "waiting_api"
            else:
                steps_status[step_id] = {"status": STATUS_PENDING}

        # 步骤5.5: 图片生成（检查文件存在 + 比例匹配 + waiting_api 数量）
        images_dir = kp_dir / "images"
        img_files = []
        if images_dir.exists():
            img_files = list(images_dir.glob("beat_*.png")) or list(images_dir.glob("beat_*.jpg"))
        imgs_exist = len(img_files) > 0

        step_status = STATUS_PENDING
        if imgs_exist:
            # 检查 image_prompts.json 中 waiting_api 的比例
            ip_path = kp_dir / "image_prompts.json"
            if ip_path.exists():
                try:
                    ip_data = json.loads(ip_path.read_text(encoding="utf-8"))
                    all_items = ip_data.get("items", [])
                    total = len(all_items)
                    waiting = sum(1 for i in all_items if i.get("image_status") == "waiting_api")
                    waiting_pct = waiting / max(total, 1)
                    # 超过 20% 待生成 → 不跳过
                    if waiting_pct > 0.2:
                        step_status = STATUS_PENDING
                    else:
                        step_status = STATUS_COMPLETED
                except Exception:
                    step_status = STATUS_COMPLETED  # 无法读取则保守按完成处理

            # 检测比例：抽查第一张图
            if step_status == STATUS_COMPLETED:
                try:
                    from PIL import Image
                    sample = img_files[0]
                    img = Image.open(str(sample))
                    ratio = img.size[0] / img.size[1]
                    img.close()
                    expected = 1920 / 1080
                    if abs(ratio - expected) > 0.05:
                        step_status = STATUS_PENDING  # 比例不对，需重生成
                except Exception:
                    pass

        steps_status["generate_images"] = {
            "status": step_status,
            "has_images": imgs_exist,
        }
        if imgs_exist:
            steps_status["generate_images"]["generated_count"] = len(img_files)

        # 步骤6: 配音
        audio_dir = kp_dir / "audio"
        audio_exists = audio_dir.exists() and any(audio_dir.glob("*.mp3"))
        steps_status["generate_audio"] = {
            "status": STATUS_COMPLETED if audio_exists else STATUS_PENDING,
            "has_audio": audio_exists,
        }

        # 步骤7: 时间线组装
        tl_exists = (kp_dir / "timeline.json").exists()
        steps_status["timeline_assembly"] = {
            "status": STATUS_COMPLETED if tl_exists else STATUS_PENDING,
        }

        # 步骤8: 字幕生成
        srt_exists = (kp_dir / "subtitles.srt").exists()
        title_overlays_exists = (kp_dir / "title_overlays.json").exists()
        steps_status["generate_subtitles"] = {
            "status": STATUS_COMPLETED if srt_exists else STATUS_PENDING,
            "has_srt": srt_exists,
            "has_title_overlays": title_overlays_exists,
        }

        # 步骤9: 最终视频合成
        video_exists = (kp_dir / "final.mp4").exists()
        steps_status["compose_final_video"] = {
            "status": STATUS_COMPLETED if video_exists else STATUS_PENDING,
            "has_video": video_exists,
        }
        if video_exists:
            try:
                video_size = (kp_dir / "final.mp4").stat().st_size
                steps_status["compose_final_video"]["file_size_mb"] = round(video_size / (1024 * 1024), 1)
            except Exception:
                pass

        steps_status["kp_dir"] = str(kp_dir)
        return steps_status

    def _tts_engine(self):
        """根据 .env 配置选择 TTS 引擎"""
        import os
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
        engine_type = os.getenv("TTS_ENGINE", "edge")
        voice = os.getenv("TTS_VOICE", "audiobook_male")

        if engine_type == "minimax":
            api_key = os.getenv("MINIMAX_API_KEY", "")
            if not api_key:
                raise RuntimeError("MiniMax TTS 未配置。请在 .env 中设置 MINIMAX_API_KEY")
            from services.tts_minimax import MinimaxTTS
            return MinimaxTTS(api_key=api_key, voice=voice)

        elif engine_type == "volcano":
            app_id = os.getenv("VOLCENGINE_TTS_APP_ID", "")
            token = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN", "")
            speaker = os.getenv("VOLCENGINE_TTS_SPEAKER", "")
            resource = os.getenv("VOLCENGINE_TTS_RESOURCE_ID", "seed-tts-2.0")
            if not app_id or not token or not speaker:
                raise RuntimeError("火山引擎 TTS 未配置")
            from services.tts_volcano import VolcanoTTS
            return VolcanoTTS(app_id=app_id, access_token=token,
                              speaker=speaker, resource_id=resource)

        else:
            from services.tts_generator import TTSGenerator
            return TTSGenerator()

    def _read_json(self, path: Path) -> dict | None:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def save_project_state(self, book_name: str, kp_id: int = 0):
        """保存 project_state.json 缓存运行记录"""
        book_dir = OUTPUT_DIR / self._safe_name(book_name)
        book_dir.mkdir(parents=True, exist_ok=True)
        state_path = book_dir / "project_state.json"

        # 读取旧状态
        state = self._read_json(state_path) or {"book_name": book_name, "runs": {}}

        # 更新运行记录
        status = self.detect_file_status(book_name, kp_id)
        state["last_scan"] = datetime.now().isoformat()
        state["steps"] = {k: v for k, v in status.items() if k != "kp_dir"}

        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state

    def _snake_case(self, name: str) -> str:
        """驼峰转下划线"""
        import re
        return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

    def _safe_name(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in " _-()（）")
        return safe.strip() or "unnamed"

    def _extract_kp_list(self, plan: dict) -> list[dict]:
        """提取 KP 列表"""
        kps = []
        for section in plan.get("content_outline", []):
            for kp in section.get("knowledge_points", []):
                kp_id = kp.get("id")
                kp_dir = kp.get("kp_dir", "")
                # 检查是否有钩子
                has_hooks = False
                has_primary = False
                if kp_dir:
                    try:
                        hc_path = Path(kp_dir) / "hook_candidates.json"
                        if hc_path.exists():
                            hc = json.loads(hc_path.read_text("utf-8"))
                            has_hooks = bool(hc.get("candidates"))
                            has_primary = bool(hc.get("primary_hook"))
                    except Exception:
                        pass
                kps.append({
                    "id": kp_id,
                    "title": kp.get("title", ""),
                    "chapter": section.get("chapter", ""),
                    "length": kp.get("suggested_video_length", ""),
                    "has_script": kp.get("has_script", False),
                    "has_hooks": has_hooks,
                    "has_primary_hook": has_primary,
                    "kp_dir": kp_dir,
                })
        return kps


# 全局单例
engine = PipelineEngine()
