"""
讲书工作流 — Web 工作台
运行: python web_app.py  →  http://127.0.0.1:8000
"""
import os
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

import asyncio
import concurrent.futures
import json
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from jinja2 import Environment, FileSystemLoader

from config import OUTPUT_DIR, PROJECT_ROOT, DATA_WAREHOUSE_DIR
from utils.logger import log
from services.web_project_loader import loader
from services.pipeline_engine import engine, PIPELINE_STEPS

# 确保数据仓库目录存在
DATA_WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="讲书工作流 — Web 工作台")
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")
jinja_env = Environment(loader=FileSystemLoader(str(BASE_DIR / "web" / "templates")))

# 全局异常处理器
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc.detail)[:300]})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    return JSONResponse(status_code=500, content={"success": False, "error": f"服务器内部错误: {str(exc)[:300]}", "traceback": tb[-2000:]})

async def _run_in_background(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, lambda: func(*args, **kwargs))

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)

def render(name: str, **kw) -> HTMLResponse:
    tpl = jinja_env.get_template(name)
    return HTMLResponse(tpl.render(**kw))


# ============================================================
# 页面路由
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    books = loader.list_books()
    return render("index.html", books=books, has_output=(BASE_DIR / "output").exists())

@app.get("/project/{book_name}", response_class=HTMLResponse)
async def project(request: Request, book_name: str):
    summary = loader.book_summary(book_name)
    return render("project.html", summary=summary, book_name=book_name)

@app.get("/project/{book_name}/kp/{kp_id}", response_class=HTMLResponse)
async def kp_detail(request: Request, book_name: str, kp_id: int):
    try:
        detail = loader.kp_detail(book_name, kp_id)
        if "error" in detail:
            return render("base.html", content=f"<h2>错误</h2><p>{detail['error']}</p>", title="错误")
        return render("kp_detail.html", detail=detail, book_name=book_name, kp_id=kp_id)
    except Exception as e:
        import traceback
        return render("base.html", content=f"<h2>服务器错误</h2><pre>{traceback.format_exc()}</pre>", title="错误")

@app.get("/work", response_class=HTMLResponse)
async def work_page(request: Request, book: str = "__new__", kp_id: int = 0):
    from urllib.parse import unquote
    book = unquote(book).strip()
    import html as _html
    book_safe = _html.escape(book)
    initial_status = {}
    file_previews = {}
    all_kps = []

    if book and book != "__new__":
        try:
            initial_status = engine.detect_file_status(book, kp_id)
        except Exception:
            pass

        if book:
            plan_path = OUTPUT_DIR / engine._safe_name(book) / "knowledge_plan.json"
            if plan_path.exists():
                try:
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                    all_kps = engine._extract_kp_list(plan)
                except Exception:
                    pass

        if kp_id > 0:
            kp_dir = engine._find_kp_dir(book, kp_id)
            if kp_dir:
                for fname in ["script.json", "script_safe.json", "script_edited.json",
                              "content_units.json", "visual_beats.json", "image_prompts.json", "timeline.json"]:
                    path = kp_dir / fname
                    if path.exists():
                        try:
                            data = json.loads(path.read_text(encoding="utf-8"))
                            file_previews[fname] = data
                        except Exception:
                            pass

    return render("pipeline.html", book_name=book, kp_id=kp_id,
                  initial_status=initial_status, file_previews=file_previews,
                  all_kps=all_kps)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    review = agent.review()
    return render("dashboard.html", review=review, has_memory=bool(review.get("total_produced", 0) > 0))

@app.get("/growth", response_class=HTMLResponse)
async def growth_page(request: Request):
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    data = agent.growth_summary()
    return render("growth.html", data=data)

@app.get("/feedback", response_class=HTMLResponse)
async def feedback_page(request: Request):
    return render("feedback.html")


# ============================================================
# Agent API
# ============================================================

@app.post("/api/agent/produce")
async def api_agent_produce(request: Request):
    try:
        raw = await request.body()
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {"success": False, "error": "请求体不是有效的 JSON"}
    book_name = body.get("book_name", "")
    if not book_name:
        return {"success": False, "error": "缺少 book_name"}

    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    try:
        result = agent.produce(book_name=book_name, toc=body.get("toc", ""), source=body.get("source", ""), focus=body.get("focus", ""))
        return {"success": True, "data": result}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/agent/confirm-topic")
async def api_agent_confirm_topic(request: Request):
    """保存选题到 knowledge_plan.json（统一数据源）"""
    try:
        raw = await request.body()
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {"success": False, "error": "请求体不是有效的 JSON"}
    book_name = body.get("book_name", "")
    topic_ids = body.get("topic_ids", [])
    subjects = body.get("topics", [])
    strategy_params = body.get("strategy_params", {})

    if not book_name or not topic_ids:
        return {"success": False, "error": "缺少 book_name 或 topic_ids"}

    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    safe_book = agent._safe_name(book_name)
    book_output_dir = OUTPUT_DIR / safe_book
    book_output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = book_output_dir / "knowledge_plan.json"

    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        plan = {"book_name": book_name, "planning_principle": "Agent 自动选题", "content_outline": []}

    agent_section = None
    for sec in plan.get("content_outline", []):
        if sec.get("chapter") == "Agent 选题":
            agent_section = sec
            break
    if not agent_section:
        agent_section = {"chapter": "Agent 选题", "chapter_summary": "由 Book Growth Agent 智能生成的选题", "knowledge_points": []}
        plan.setdefault("content_outline", []).append(agent_section)

    existing_ids = {kp["id"] for kp in agent_section.get("knowledge_points", [])}
    selected = [t for t in subjects if t.get("topic_id") in topic_ids]
    saved = []

    for t in selected:
        tid = t.get("topic_id", 0)
        title = t.get("topic_title", f"draft_{tid}")
        safe_title = agent._safe_name(title)[:40]
        kp_id_val = 100 + tid
        dir_name = f"kp_{kp_id_val:03d}_{safe_title}"
        topic_dir = book_output_dir / dir_name
        # 不在这里创建目录！等用户真正点"生成讲稿"时再创建

        # Check if KP already exists in knowledge_plan.json
        kp_exists = None
        for kp in agent_section.get("knowledge_points", []):
            if kp["id"] == kp_id_val:
                kp_exists = kp
                break
        
        entry = {"topic_id": tid, "topic_title": title, "score": t.get("score", 0), "dir_name": dir_name, "kp_id": kp_id_val, "kp_dir": str(topic_dir).replace(chr(92), "/"), "has_script": (topic_dir / "script.json").exists()}

        if kp_exists:
            # Update existing KP
            kp_exists["title"] = title
            kp_exists["kp_dir"] = str(topic_dir).replace(chr(92), "/")
            kp_exists["score"] = t.get("score", 0)
            kp_exists["hook_type"] = t.get("hook_type", "")
            kp_exists["target_audience"] = t.get("target_audience", "")
            kp_exists["content_angle"] = t.get("content_angle", "")
            kp_exists["tone"] = t.get("tone", "")
            kp_exists["visual_style"] = t.get("visual_style", "")
            kp_exists["platform_safety_note"] = t.get("platform_safety_note", "")
            kp_exists["core_insight"] = t.get("core_insight", "")
            kp_exists["why_attractive"] = t.get("why_attractive", "")
            kp_exists["original_meaning"] = t.get("core_insight", "")
            kp_exists["core_problem"] = t.get("content_angle", "")
            kp_exists["why_useful"] = t.get("why_attractive", t.get("target_audience", ""))
            kp_exists["universal_relevance"] = t.get("target_audience", "")
            kp_exists["presentation_approach"] = t.get("content_angle", "")
        else:
            # Create new KP
            new_kp = {"id": kp_id_val, "title": title, "chapter": "Agent 选题", "source_scope": "整书分析", "original_meaning": t.get("core_insight", ""), "core_problem": t.get("content_angle", ""), "why_useful": t.get("why_attractive", t.get("target_audience", "")), "universal_relevance": t.get("target_audience", ""), "presentation_approach": t.get("content_angle", ""), "specific_book_content": [], "suggested_video_length": "8-12分钟", "hook_idea": t.get("hook_type", ""), "has_script": False, "kp_dir": str(topic_dir).replace(chr(92), "/"), "score": t.get("score", 0), "hook_type": t.get("hook_type", ""), "target_audience": t.get("target_audience", ""), "content_angle": t.get("content_angle", ""), "tone": t.get("tone", ""), "visual_style": t.get("visual_style", ""), "platform_safety_note": t.get("platform_safety_note", ""), "why_attractive": t.get("why_attractive", ""), "core_insight": t.get("core_insight", "")}
            agent_section["knowledge_points"].append(new_kp)

        saved.append(entry)

    # 保留已有讲稿的旧选题（重新生成选题池时不覆盖已生成讲稿的）
    kept_old = 0
    for existing_kp in list(agent_section.get("knowledge_points", [])):
        kp_dir = existing_kp.get("kp_dir", "")
        if kp_dir and Path(kp_dir).exists():
            raw_kp_id = existing_kp["id"] - 100  # convert kp_id back to topic_id
            new_kp_ids = set(body.get("topic_ids", []))
            has_script = (Path(kp_dir) / "script.json").exists()
            # 保留已有讲稿的选题，即使不在新生成的选题池中
            if has_script and raw_kp_id not in new_kp_ids:
                # 这个旧选题已经有讲稿了但不在新生成的选题池中 → 保留
                kept_old += 1
                # 确保不重复添加
                already_in_new = False
                for new_kp in agent_section.get("knowledge_points", []):
                    if new_kp["id"] == existing_kp["id"]:
                        already_in_new = True
                        break
                if not already_in_new:
                    agent_section["knowledge_points"].append(existing_kp)

    plan["total_knowledge_points"] = sum(len(s.get("knowledge_points", [])) for s in plan.get("content_outline", []))
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"选题池保存完成: {len(saved)} 个新选题, 保留 {kept_old} 个已有讲稿的旧选题")
    return {"success": True, "data": {"saved": saved, "count": len(saved), "kept_old": kept_old}}

@app.get("/api/agent/drafts")
async def api_agent_drafts(book_name: str = ""):
    """从 knowledge_plan.json 读取 Agent 选题（统一数据源）"""
    if not book_name:
        return {"success": False, "error": "缺少 book_name"}

    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    safe_book = agent._safe_name(book_name)
    book_dir = OUTPUT_DIR / safe_book
    plan_path = book_dir / "knowledge_plan.json"

    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for sec in plan.get("content_outline", []):
            if sec.get("chapter") == "Agent 选题":
                kps = sec.get("knowledge_points", [])
                saved = []
                for kp in kps:
                    kp_dir = kp.get("kp_dir", "")
                    has_script = False
                    if kp_dir:
                        has_script = (Path(kp_dir) / "script.json").exists()
                    saved.append({"topic_id": kp.get("id", 0) - 100, "topic_title": kp.get("title", ""), "score": kp.get("score", 0), "has_script": has_script, "kp_id": kp.get("id"), "kp_dir": kp_dir, "hook_type": kp.get("hook_type", ""), "target_audience": kp.get("target_audience", ""), "content_angle": kp.get("content_angle", ""), "why_attractive": kp.get("why_attractive", "")})
                return {"success": True, "data": {"saved": saved, "count": len(saved)}}

    return {"success": True, "data": {"saved": [], "count": 0}}


@app.post("/api/agent/generate-script")
async def api_agent_generate_script(request: Request):
    """为单个选题生成讲稿（在选题目录原地工作，不复制）"""
    try:
        raw = await request.body()
        body = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return {"success": False, "error": "请求体不是有效的 JSON"}

    book_name = (body.get("book_name") or "").strip()
    topic_id = body.get("topic_id")

    if not book_name or topic_id is None:
        return {"success": False, "error": "缺少 book_name 或 topic_id"}

    return await _run_in_background(_do_generate_script, book_name, topic_id)


def _do_generate_script(book_name: str, topic_id: int) -> dict:
    """在后台线程执行讲稿生成（同步函数）"""
    from agent import BookGrowthAgent
    agent_instance = BookGrowthAgent()
    safe_book = agent_instance._safe_name(book_name)
    book_output_dir = OUTPUT_DIR / safe_book
    plan_path = book_output_dir / "knowledge_plan.json"

    if not plan_path.exists():
        return {"success": False, "error": "未找到选题信息，请先保存选题"}

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    agent_kp_id = 100 + (topic_id or 0)
    draft_dir = None
    draft = None
    for sec in plan.get("content_outline", []):
        if sec.get("chapter") == "Agent 选题":
            for kp in sec.get("knowledge_points", []):
                if kp.get("id") == agent_kp_id:
                    kp_dir = kp.get("kp_dir", "")
                    if kp_dir:
                        draft_dir = Path(kp_dir)
                    break
            break

    if not draft_dir:
        return {"success": False, "error": f"未找到选题 #{topic_id} 的目录"}

    draft_dir.mkdir(parents=True, exist_ok=True)

    draft_path = draft_dir / "_topic_draft.json"
    if draft_path.exists():
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    else:
        draft = {"topic_id": topic_id, "topic_title": "", "core_insight": "", "content_angle": "", "hook_type": "", "tone": "", "visual_style": "", "platform_safety_note": "", "score": 0, "why_attractive": "", "target_audience": ""}
        for sec in plan.get("content_outline", []):
            if sec.get("chapter") == "Agent 选题":
                for kp in sec.get("knowledge_points", []):
                    if kp.get("id") == agent_kp_id:
                        draft["topic_title"] = kp.get("title", "")
                        draft["core_insight"] = kp.get("core_insight", "")
                        draft["content_angle"] = kp.get("content_angle", "")
                        draft["hook_type"] = kp.get("hook_type", "")
                        draft["tone"] = kp.get("tone", "")
                        draft["visual_style"] = kp.get("visual_style", "")
                        draft["score"] = kp.get("score", 0)
                        draft["why_attractive"] = kp.get("why_attractive", "")
                        draft["target_audience"] = kp.get("target_audience", "")
                        break
                break

    from services.orchestrator import Orchestrator
    orch = Orchestrator()
    kp_info = orch._topic_to_kp_info(book_name, draft, draft.get("topic_id", topic_id))

    agent_context = {k: v for k, v in draft.items() if v and isinstance(v, str)}
    agent_context_block = agent_instance.format_agent_context(agent_context)

    from services.script_generator import ScriptGenerator
    gen = ScriptGenerator()
    try:
        script = gen.generate_knowledge_point(kp_info, agent_context_block=agent_context_block)
    except Exception as script_err:
        log.error(f"generate_knowledge_point failed: {script_err}")
        import traceback as tb
        log.error(tb.format_exc())
        return {"success": False, "error": f"LLM error: {str(script_err)[:300]}"}
    if not script or not isinstance(script, dict) or not script.get("full_script"):
        return {"success": False, "error": "LLM output is empty - check prompt format"}
    gen.save_script(script, draft_dir)

    from services.quality_checker import QualityChecker
    qc = QualityChecker()
    qc_result = qc.check(script)
    qc.save_result(qc_result, draft_dir)

    log.info("  自动运行内容单元切分...")
    from services.content_unit_segmenter import ContentUnitSegmenter
    try:
        seg = ContentUnitSegmenter()
        seg.run(draft_dir)
        log.success("  内容单元切分完成")
    except Exception as e:
        log.warn(f"  内容单元切分失败（可在 Pipeline 中重试）: {e}")

        agent_kp_id = 100 + (draft.get("topic_id", topic_id) or 0)
        plan_path = book_output_dir / "knowledge_plan.json"
        if plan_path.exists():
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        else:
            plan = {"book_name": book_name, "planning_principle": "Agent 自动选题", "content_outline": []}

        agent_section = None
        for sec in plan.get("content_outline", []):
            if sec.get("chapter") == "Agent 选题":
                agent_section = sec
                break
        if not agent_section:
            agent_section = {"chapter": "Agent 选题", "chapter_summary": "由 Book Growth Agent 智能生成的选题", "knowledge_points": []}
            plan.setdefault("content_outline", []).append(agent_section)

        kp_exists = False
        for kp in agent_section.get("knowledge_points", []):
            if kp.get("id") == agent_kp_id:
                kp_exists = True
                break

        if not kp_exists:
            agent_section["knowledge_points"].append({
                "id": agent_kp_id, "title": draft.get("topic_title", ""), "chapter": "Agent 选题",
                "source_scope": "整书分析", "original_meaning": draft.get("core_insight", ""),
                "core_problem": draft.get("content_angle", ""),
                "why_useful": draft.get("why_attractive", draft.get("target_audience", "")),
                "universal_relevance": draft.get("target_audience", ""),
                "presentation_approach": draft.get("content_angle", ""),
                "specific_book_content": [], "suggested_video_length": "8-12分钟",
                "hook_idea": draft.get("hook_type", ""),
            })

        plan.setdefault("total_knowledge_points", sum(len(s.get("knowledge_points", [])) for s in plan.get("content_outline", [])))
        plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"  已注册到 knowledge_plan.json (kp_id={agent_kp_id})")


        return {
            "success": True,
            "data": {
                "topic_id": draft.get("topic_id"),
                "topic_title": draft.get("topic_title", ""),
                "script_words": len(script.get("full_script", "")),
                "estimated_length": script.get("estimated_video_length", script.get("suggested_video_length", "")),
                "kp_id": agent_kp_id,
                "kp_dir": str(draft_dir).replace('\\', '/'),
            }
        }
    except Exception as e:
        import traceback
        log.error(f"generate-script 失败: {e}")
        return {"success": False, "error": str(e)[:500]}



@app.post("/api/agent/think")
async def api_agent_think(request: Request):
    """Agent 思维过程问答"""
    try:
        body = await request.json()
        book_name = (body.get("book_name") or "").strip()
        user_question = (body.get("question") or "").strip()
        context = body.get("context", {})
        
        if not book_name:
            return {"success": False, "error": "缺少 book_name"}
        
        from agent import BookGrowthAgent
        agent = BookGrowthAgent()
        
        # 构造 prompt 上下文
        status = context.get("pipeline_status", {})
        def s(key):
            return status.get(key, {}).get("status", "pending") if isinstance(status.get(key), dict) else "pending"
        
        reasoning_text = context.get("reasoning", "")
        topic_reasons = context.get("topic_reasons", "")
        generated_topics = context.get("generated_topics", 0)
        script_status = context.get("script_status", "")
        selected_topic = context.get("selected_topic", "")
        
        prompt_template = agent._load_prompt("agent_advisor.txt")
        system_prompt = prompt_template.replace("{book_name}", book_name)
        system_prompt = system_prompt.replace("{kp_id}", str(context.get("kp_id", "")))
        system_prompt = system_prompt.replace("{selected_topic}", selected_topic)
        system_prompt = system_prompt.replace("{generated_topics}", str(generated_topics))
        system_prompt = system_prompt.replace("{script_status}", script_status)
        system_prompt = system_prompt.replace("{cu_status}", s("content_units"))
        system_prompt = system_prompt.replace("{vb_status}", s("visual_beats"))
        system_prompt = system_prompt.replace("{ip_status}", s("image_prompts"))
        system_prompt = system_prompt.replace("{gi_status}", s("generate_images"))
        system_prompt = system_prompt.replace("{ga_status}", s("generate_audio"))
        system_prompt = system_prompt.replace("{tl_status}", s("timeline_assembly"))
        system_prompt = system_prompt.replace("{gs_status}", s("generate_subtitles"))
        system_prompt = system_prompt.replace("{cfv_status}", s("compose_final_video"))
        system_prompt = system_prompt.replace("{reasoning_text}", reasoning_text[:500])
        system_prompt = system_prompt.replace("{topic_reasons}", topic_reasons[:500])
        system_prompt = system_prompt.replace("{user_question}", user_question or "展示当前分析状态和建议")
        
        result = agent._call_llm(system_prompt, "请回答用户问题: " + user_question, temperature=0.3, max_tokens=2000)
        return {"success": True, "data": {"answer": result.get("answer", ""), "next_step": result.get("next_step", "")}}
    except Exception as e:
        import traceback
        log.error(f"think 失败: {e}")
        return {"success": False, "error": str(e)[:300]}

@app.get("/api/agent/draft-script")
async def api_agent_draft_script(book_name: str = "", topic_id: int = 0):
    """获取草稿讲稿内容"""
    if not book_name or not topic_id:
        return {"success": False, "error": "缺少 book_name 或 topic_id"}

    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    safe_book = agent._safe_name(book_name)
    book_dir = OUTPUT_DIR / safe_book
    plan_path = book_dir / "knowledge_plan.json"

    if not plan_path.exists():
        return {"success": False, "error": "未找到选题信息"}

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    agent_kp_id = 100 + (topic_id or 0)
    draft_dir = None
    for sec in plan.get("content_outline", []):
        if sec.get("chapter") == "Agent 选题":
            for kp in sec.get("knowledge_points", []):
                if kp.get("id") == agent_kp_id:
                    kp_dir = kp.get("kp_dir", "")
                    if kp_dir:
                        candidate = Path(kp_dir)
                        if candidate.exists():
                            draft_dir = candidate
                            break
            break

    if not draft_dir:
        return {"success": False, "error": f"未找到选题 #{topic_id}"}

    script_path = draft_dir / "script.json"
    if not script_path.exists():
        return {"success": False, "error": "讲稿尚未生成"}

    script_data = json.loads(script_path.read_text(encoding="utf-8"))
    return {
        "success": True,
        "data": {
            "topic_id": topic_id,
            "full_script": script_data.get("full_script", ""),
            "opening": script_data.get("opening", ""),
            "script_words": len(script_data.get("full_script", "")),
            "quality_check": (draft_dir / "quality_check.json").exists(),
        }
    }


@app.post("/api/agent/generate-script/next-step")
async def api_agent_next_step(request: Request):
    body = await request.json()
    book_name = (body.get("book_name") or "").strip()
    draft_dir = body.get("draft_dir", "")
    if not book_name or not draft_dir:
        return {"success": False, "error": "缺少参数"}
    from services.pipeline_engine import engine
    result = engine.run_content_units_from_draft(book_name, draft_dir)
    return result


@app.post("/api/agent/analyze")
async def api_agent_analyze(request: Request):
    from agent import BookGrowthAgent
    form = await request.form()
    book_name = form.get("book_name", "")
    file = form.get("file")
    if not file:
        return {"success": False, "error": "缺少文件"}
    tmp_dir = BASE_DIR / "output" / "_agent_uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / file.filename
    content = await file.read()
    tmp_path.write_bytes(content)
    agent = BookGrowthAgent()
    try:
        result = agent.analyze(file_path=str(tmp_path), book_name=book_name)
        return {"success": True, "data": result} if result.get("success") else result
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/agent/diagnose")
async def api_agent_diagnose(request: Request):
    body = await request.json()
    video = body.get("video", {})
    if not video:
        return {"success": False, "error": "缺少 video 数据"}
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    try:
        result = agent.diagnose(video)
        return {"success": True, "data": result}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/agent/review")
async def api_agent_review(request: Request):
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    book_name = body.get("book_name", "") if isinstance(body, dict) else ""
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    try:
        result = agent.review(book_name=book_name)
        return {"success": True, "data": result}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.get("/api/agent/memory")
async def api_agent_memory(type: str = "all", book: str = ""):
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    result_data = {"book_strategy": [], "analysis": [], "effectiveness": []}
    strategy_mem = agent._read_memory("book_strategy_memory")
    entries = strategy_mem.get("entries", [])
    if book:
        entries = [e for e in entries if e.get("book_name") == book]
    result_data["book_strategy"] = entries
    analysis_mem = agent._read_memory("analysis_memory")
    analysis_entries = analysis_mem.get("entries", [])
    if book:
        analysis_entries = [s for s in analysis_entries if s.get("book_name") == book]
    result_data["analysis"] = analysis_entries
    effectiveness = agent._read_memory("strategy_effectiveness")
    result_data["effectiveness"] = effectiveness.get("mappings", [])
    if type == "strategy":
        return {"data": result_data["book_strategy"]}
    elif type == "analysis":
        return {"data": result_data["analysis"]}
    elif type == "effectiveness":
        return {"data": result_data["effectiveness"]}
    return {"data": result_data}


# ============================================================
# Content Growth API
# ============================================================

@app.get("/api/growth/data")
async def api_growth_data():
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    data = agent.growth_summary()
    return {"success": True, "data": data}

@app.get("/api/learning/center")
async def api_learning_center():
    """学习中心完整数据"""
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    return {
        "success": True,
        "data": {
            "growth_summary": agent.growth_summary(),
            "rules": agent.strategy_validator.get_learning_center_data(),
            "strategy_pool": agent.strategy_validator.get_summary(),
        }
    }

@app.get("/api/strategies/rules")
async def api_strategies_rules(category: str = ""):
    """策略规则列表"""
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    rules = agent.strategy_validator.get_rules(category=category)
    return {"success": True, "data": {"rules": rules, "count": len(rules)}}

@app.post("/api/signals/analyze")
async def api_signals_analyze(request: Request):
    """运行信号检测"""
    body = await request.json()
    file_path = body.get("file_path", "")
    if not file_path:
        return {"success": False, "error": "缺少 file_path"}
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    videos = agent.import_data(file_path)
    if not videos:
        return {"success": False, "error": "无有效数据"}
    signal_result = agent.structure_analyzer.analyze_signals(videos)
    high = agent.structure_analyzer.find_high_performing_patterns(videos, "plays", top_n=5)
    low = agent.structure_analyzer.find_low_performing_patterns(videos, "plays", top_n=5)
    return {"success": True, "data": {
        "signal_analysis": signal_result,
        "high_performing": high,
        "low_performing": low,
        "total_videos": len(videos),
    }}

@app.get("/api/signals/self")
async def api_signals_self():
    """获取自身增长信号"""
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    self_growth = agent._read_self_growth()
    return {"success": True, "data": self_growth}

@app.get("/api/strategies")
async def api_strategies(status: str = "all"):
    """列出策略池，可按状态筛选"""
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    if status == "validated":
        strategies = agent.strategy_validator.get_validated_strategies()
    elif status == "testing":
        strategies = agent.strategy_validator.get_testing_strategies()
    elif status == "deprecated":
        strategies = agent.strategy_validator.get_rejected_strategies()
    else:
        pool = agent.strategy_validator._load_pool()
        strategies = pool.get("strategies", [])
    return {"success": True, "data": {"strategies": strategies, "count": len(strategies)}}

@app.post("/api/strategies/record")
async def api_strategies_record(request: Request):
    """记录策略结果"""
    body = await request.json()
    strategy_name = body.get("strategy_name", "")
    success = body.get("success", True)
    if not strategy_name:
        return {"success": False, "error": "缺少 strategy_name"}
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    entry = agent.strategy_validator.record_strategy_outcome(
        strategy_name, success, context=body.get("context", {})
    )
    return {"success": True, "data": {"entry": entry}}

@app.get("/api/strategies/summary")
async def api_strategies_summary():
    """策略池摘要统计"""
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    summary = agent.strategy_validator.get_summary()
    return {"success": True, "data": summary}

@app.post("/api/agent/analyze-with-growth")
async def api_agent_analyze_with_growth(request: Request):
    """增强版分析：信号检测 + 归因 + 策略记录"""
    body = await request.json()
    file_path = body.get("file_path", "")
    book_name = body.get("book_name", "")
    if not file_path:
        return {"success": False, "error": "缺少 file_path"}
    from agent import BookGrowthAgent
    agent = BookGrowthAgent()
    try:
        # 检查文件是否存在
        path_obj = Path(file_path)
        if not path_obj.exists():
            return {"success": False, "error": f"文件不存在: {file_path}"}
        result = agent.analyze_with_growth(file_path, book_name=book_name)
        return {"success": True, "data": result}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# ============================================================
# 抖音数据分析 API（基于 undoom-douyin-data-analysis）
# ============================================================

from services.douyin_analyzer import DouyinAnalyzer, DRISSION_AVAILABLE

_analyzer = DouyinAnalyzer()


@app.post("/api/douyin/search")
async def api_douyin_search(request: Request):
    """搜索抖音视频并分析"""
    body = await request.json()
    keyword = body.get("keyword", "")
    scroll_count = body.get("scroll_count", 8)
    if not keyword:
        return {"success": False, "error": "缺少关键词"}

    analyzer = DouyinAnalyzer()
    try:
        videos = await _run_in_background(analyzer.search_videos, keyword, scroll_count)
        result = analyzer.full_analysis()
        result["videos"] = videos[:20]
        return {"success": True, "data": result}
    except RuntimeError as e:
        return {"success": False, "error": str(e), "needs_drission": True}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/douyin/analyze-upload")
async def api_douyin_analyze_upload(request: Request):
    """上传 Excel/CSV — 保存到数据仓库并分析（含增长分析）"""
    form = await request.form()
    file = form.get("file")
    if not file:
        return {"success": False, "error": "缺少文件"}
    content = await file.read()

    # 先保存一份到数据仓库（永久存档）
    warehouse_path = DATA_WAREHOUSE_DIR / file.filename
    # 避免重名覆盖
    if warehouse_path.exists():
        from time import time
        name, ext = file.filename.rsplit(".", 1) if "." in file.filename else (file.filename, "")
        warehouse_path = DATA_WAREHOUSE_DIR / f"{name}_{int(time())}.{ext}"
    warehouse_path.write_bytes(content)

    analyzer = DouyinAnalyzer()
    try:
        count = analyzer.load_from_file(str(warehouse_path))
        result = analyzer.full_analysis()
        result["imported_count"] = count
        result["saved_to"] = str(warehouse_path.name)

        # === Content Growth: 增强分析 ===
        try:
            from agent import BookGrowthAgent
            agent = BookGrowthAgent()
            growth_result = agent.analyze_with_growth(str(warehouse_path))
            growth_data = growth_result.get("growth_analysis")
            if growth_data:
                result["growth_analysis"] = growth_data
                result["growth_enabled"] = True
        except Exception as ge:
            result["growth_analysis"] = {"error": str(ge), "growth_enabled": False}
            result["growth_enabled"] = False

        return {"success": True, "data": result, "growth_enabled": result.get("growth_enabled", False)}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


# ─── 数据仓库 API ──────────────────────────────────────


@app.get("/api/douyin/warehouse")
async def api_douyin_warehouse():
    """列出数据仓库中的所有数据文件"""
    files = []
    if DATA_WAREHOUSE_DIR.exists():
        for f in sorted(DATA_WAREHOUSE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.suffix.lower() in (".xlsx", ".xls", ".csv") and not f.name.startswith("~"):
                size = f.stat().st_size
                mtime = f.stat().st_mtime
                from datetime import datetime
                files.append({
                    "name": f.name,
                    "size": _human_size(size),
                    "mtime": datetime.fromtimestamp(mtime).isoformat()[:19],
                    "analyzed": (DATA_WAREHOUSE_DIR / f"{f.name}.analysis.json").exists(),
                })
    return {"success": True, "data": {"dir": str(DATA_WAREHOUSE_DIR), "files": files}}


@app.post("/api/douyin/warehouse/analyze")
async def api_douyin_warehouse_analyze(request: Request):
    """从数据仓库选择文件进行分析（含增长分析：信号检测 + 归因 + 策略记录）"""
    body = await request.json()
    filename = body.get("filename", "")
    if not filename:
        return {"success": False, "error": "缺少文件名"}
    filepath = DATA_WAREHOUSE_DIR / filename
    if not filepath.exists():
        return {"success": False, "error": f"文件不存在: {filename}"}

    analyzer = DouyinAnalyzer()
    try:
        count = analyzer.load_from_file(str(filepath))
        result = analyzer.full_analysis()
        result["imported_count"] = count

        # 缓存标准分析结果
        cache_path = DATA_WAREHOUSE_DIR / f"{filename}.analysis.json"
        cache_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        # === Content Growth: 增强分析（信号检测 + 归因 + 策略记录） ===
        growth_data = None
        try:
            from agent import BookGrowthAgent
            from services.signal_detector import ContentStructureAnalyzer
            from services.content_attribution import ContentAttributor
            import copy

            agent = BookGrowthAgent()
            # 从已加载的 analyzer 获取视频数据（字段格式已标准化）
            raw = analyzer.videos if hasattr(analyzer, 'videos') else []
            videos = []
            for v in raw:
                item = {
                    "title": v.get("title", "") or "",
                    "plays": v.get("plays", 0) or 0,
                    "likes": v.get("likes", 0) or 0,
                    "favorites": v.get("collects", v.get("favorites", 0)) or 0,
                    "comments": v.get("comments", 0) or 0,
                    "shares": v.get("shares", 0) or 0,
                    "completion_rate": v.get("completion_rate", 0) or 0,
                    "follows": v.get("follower_growth", v.get("follows", 0)) or 0,
                    "drop_off_rate": v.get("drop_off_rate", v.get("comp_2s", 0)) or 0,
                }
                if item["title"]:
                    videos.append(item)

            if videos:
                detector = ContentStructureAnalyzer()
                attributor = ContentAttributor()

                # 六级结构分析
                structure_result = detector.full_structure_analysis(videos)
                signal_result = structure_result.get("signals", {})

                # 更新 self_growth_memory（五层结构）
                self_growth = agent._read_self_growth()
                self_growth = detector.update_self_growth_memory(
                    self_growth, structure_result
                )
                agent._write_self_growth(self_growth)

                # 归因（最高和最低播放的视频）
                sorted_videos = sorted(videos, key=lambda v: float(v.get("plays", 0) or 0), reverse=True)
                top_attr = attributor.full_attribution(sorted_videos[0], signal_result) if sorted_videos else None
                bottom_attr = attributor.full_attribution(sorted_videos[-1], signal_result) if len(sorted_videos) > 1 else None

                # 学习策略规则 → strategy_memory.json
                agent.strategy_validator.learn_from_analysis(
                    structure_result.get("content_structures", {}),
                    structure_result.get("openings", {}),
                    structure_result.get("content_models", {}),
                    structure_result.get("topics", {}),
                )

                growth_data = {
                    "signal_analysis": {
                        "summary": signal_result.get("summary"),
                        "total_videos": signal_result.get("total_videos"),
                        "videos_with_signals": signal_result.get("videos_with_signals"),
                        "multi_signal_videos": signal_result.get("multi_signal_videos"),
                    },
                    "content_structures": structure_result.get("content_structures"),
                    "openings": structure_result.get("openings"),
                    "content_models": structure_result.get("content_models"),
                    "topics": structure_result.get("topics"),
                    "top_video_attribution": top_attr,
                    "bottom_video_attribution": bottom_attr,
                    "strategy_pool": agent.strategy_validator.get_summary(),
                    "learning_center": agent.strategy_validator.get_learning_center_data(),
                    "total_videos_analyzed": self_growth.get("total_videos_analyzed"),
                    "growth_enabled": True,
                }
                result["growth_analysis"] = growth_data
                result["growth_enabled"] = True

                # 追加缓存
                cache_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        except Exception as ge:
            import traceback as _tb
            result["growth_analysis"] = {"error": str(ge) + " | " + _tb.format_exc()[-500:], "growth_enabled": False}
            result["growth_enabled"] = False

        return {"success": True, "data": result, "growth_enabled": result.get("growth_enabled", False)}
    except Exception as e:
        import traceback
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.post("/api/douyin/warehouse/delete")
async def api_douyin_warehouse_delete(request: Request):
    """删除数据仓库中的文件"""
    body = await request.json()
    filename = body.get("filename", "")
    if not filename:
        return {"success": False, "error": "缺少文件名"}
    filepath = DATA_WAREHOUSE_DIR / filename
    if filepath.exists():
        filepath.unlink()
    # 也删除缓存的分析结果
    cache_path = DATA_WAREHOUSE_DIR / f"{filename}.analysis.json"
    if cache_path.exists():
        cache_path.unlink()
    return {"success": True}


@app.get("/api/douyin/status")
async def api_douyin_status():
    return {
        "success": True,
        "data": {
            "drission_available": DRISSION_AVAILABLE,
            "warehouse_dir": str(DATA_WAREHOUSE_DIR),
            "warehouse_count": sum(1 for f in DATA_WAREHOUSE_DIR.iterdir()
                                   if f.suffix.lower() in (".xlsx", ".xls", ".csv"))
            if DATA_WAREHOUSE_DIR.exists() else 0,
        }
    }


@app.get("/api/douyin/template")
async def api_douyin_template():
    """下载分析模板 Excel — 含抖音创作者后台完整导出列"""
    import io
    import pandas as pd

    sample = [
        {
            "视频标题": "为什么你总是拖延？",
            "作者": "认知觉醒",
            "播放量": 85200,
            "点赞": 15200,
            "评论": 843,
            "分享": 2100,
            "收藏": 3200,
            "完播率": "18.5%",
            "平均播放时长(秒)": 42,
            "3秒完播率": "62.3%",
            "粉丝播放占比": "35.2%",
            "粉丝增长": 128,
        },
        {
            "视频标题": "三个方法让你早起",
            "作者": "自律人生",
            "播放量": 43000,
            "点赞": 8700,
            "评论": 412,
            "分享": 980,
            "收藏": 1500,
            "完播率": "22.1%",
            "平均播放时长(秒)": 55,
            "3秒完播率": "68.7%",
            "粉丝播放占比": "28.6%",
            "粉丝增长": 65,
        },
        {
            "视频标题": "高手都在用的思维模型",
            "作者": "思维实验室",
            "播放量": 128000,
            "点赞": 23500,
            "评论": 1560,
            "分享": 4500,
            "收藏": 6800,
            "完播率": "12.4%",
            "平均播放时长(秒)": 38,
            "3秒完播率": "55.1%",
            "粉丝播放占比": "41.3%",
            "粉丝增长": 256,
        },
    ]
    df = pd.DataFrame(sample)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="抖音数据")
    docs = pd.DataFrame([
        {"字段": col, "说明": desc}
        for col, desc in [
            ("视频标题", "视频的标题文本（必填）"),
            ("作者", "博主名称（可选）"),
            ("播放量", "视频总播放次数"),
            ("点赞", "点赞数"),
            ("评论", "评论数"),
            ("分享", "分享数"),
            ("收藏", "收藏数"),
            ("完播率", "完整播放率，如 18.5%（必填，用于完播率分析）"),
            ("平均播放时长(秒)", "用户平均观看时长，单位秒"),
            ("3秒完播率", "前3秒未划走的比例"),
            ("粉丝播放占比", "来自粉丝的播放量占比"),
            ("粉丝增长", "该视频带来的粉丝增长数"),
        ]
    ])
    docs.to_excel(writer, sheet_name="字段说明", index=False)

    buf.seek(0)

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=douyin_template.xlsx"}
    )


def _human_size(bytes: int) -> str:
    if bytes < 1024:
        return f"{bytes}B"
    elif bytes < 1024 * 1024:
        return f"{bytes/1024:.1f}KB"
    else:
        return f"{bytes/1024/1024:.1f}MB"


# ============================================================
# Feedback API
# ============================================================

FEEDBACK_PATH = PROJECT_ROOT / "memory" / "feedback_memory.json"

def _load_feedback() -> dict:
    if FEEDBACK_PATH.exists():
        try:
            return json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"topic_feedback": [], "strategy_feedback": [], "preferences": {"liked_styles": [], "disliked_styles": [], "preferred_strategies": [], "preferred_tone": None, "preferred_hook_types": []}}

def _save_feedback(data: dict):
    FEEDBACK_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def _update_preferences():
    data = _load_feedback()
    likes = [f for f in data.get("topic_feedback", []) if f.get("feedback") == "like"]
    dislikes = [f for f in data.get("topic_feedback", []) if f.get("feedback") == "dislike"]
    prefs = {"liked_styles": [], "disliked_styles": [], "preferred_strategies": [], "preferred_tone": None, "preferred_hook_types": []}
    style_kw = {"问题式": "问题式标题", "为什么": "问题式标题", "普通人": "普通人视角", "反常识": "反常识冲击", "标题党": "标题党", "夸张": "标题党", "学术": "学术表达", "故事": "故事驱动", "场景": "场景代入"}
    liked_r = " ".join([f.get("reason", "") for f in likes])
    disliked_r = " ".join([f.get("reason", "") for f in dislikes])
    for kw, style in style_kw.items():
        if kw in liked_r and style not in prefs["liked_styles"]:
            prefs["liked_styles"].append(style)
        if kw in disliked_r and style not in prefs["disliked_styles"]:
            prefs["disliked_styles"].append(style)
    s_counts = {}
    for f in data.get("strategy_feedback", []):
        s = f.get("strategy_name", "")
        if s:
            s_counts[s] = s_counts.get(s, 0) + 1
    prefs["preferred_strategies"] = sorted(s_counts, key=s_counts.get, reverse=True)[:3]
    data["preferences"] = prefs
    _save_feedback(data)
    return prefs

@app.post("/api/feedback/topic")
async def api_feedback_topic(request: Request):
    try:
        body = await request.json()
        tid = body.get("topic_id"); fb = body.get("feedback"); reason = (body.get("reason") or "").strip()
        bn = (body.get("book_name") or "").strip(); tt = (body.get("topic_title") or "").strip()
        if not tid or not fb:
            return {"success": False, "error": "缺少参数"}
        data = _load_feedback()
        data.setdefault("topic_feedback", []).append({"topic_id": tid, "topic_title": tt, "feedback": fb, "reason": reason, "book_name": bn, "created_at": __import__("datetime").datetime.now().isoformat()})
        _save_feedback(data); _update_preferences()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

@app.get("/api/feedback/memory")
async def api_feedback_memory():
    try:
        data = _load_feedback(); prefs = _update_preferences()
        return {"success": True, "data": {"preferences": prefs, "total_feedback": len(data.get("topic_feedback", [])), "recent_feedback": data.get("topic_feedback", [])[-20:]}}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

@app.post("/api/feedback/clear")
async def api_feedback_clear():
    try:
        clr = {"topic_feedback": [], "strategy_feedback": [], "preferences": {"liked_styles": [], "disliked_styles": [], "preferred_strategies": [], "preferred_tone": None, "preferred_hook_types": []}}
        _save_feedback(clr)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


# ============================================================
# Pipeline API
# ============================================================

@app.get("/api/pipeline/{book_name}/status")
async def api_pipeline_status(book_name: str, kp_id: int = 0):
    return engine.detect_file_status(book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/plan")
async def api_run_plan(book_name: str):
    return await _run_in_background(engine.run_plan_book, book_name)


@app.post("/api/script-mode/{mode}")
async def api_set_script_mode(mode: str):
    mode_path = BASE_DIR / "script_mode.txt"
    mode_path.write_text(mode, encoding="utf-8")
    return {"success": True, "mode": mode}


@app.get("/api/script-mode")
async def api_get_script_mode():
    mode_path = BASE_DIR / "script_mode.txt"
    mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "normal"
    return {"mode": mode}


@app.post("/api/pipeline/{book_name}/run/script/{kp_id}")
async def api_run_script(book_name: str, kp_id: int):
    mode_path = BASE_DIR / "script_mode.txt"
    mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "normal"
    return await _run_in_background(engine.run_generate_script, book_name, kp_id, mode=mode)


@app.post("/api/pipeline/{book_name}/run/content-units/{kp_id}")
async def api_run_content_units(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_content_units, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/visual-beats/{kp_id}")
async def api_run_visual_beats(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_visual_beats, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/image-prompts/{kp_id}")
async def api_run_image_prompts(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_image_prompts, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/generate-images/{kp_id}")
async def api_run_generate_images(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_generate_images, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/retry-images/{kp_id}")
async def api_run_retry_images(book_name: str, kp_id: int):
    """重试失败图片 — 自动循环直到全部成功"""
    return await _run_in_background(engine.run_retry_images_until_done, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/regenerate-all/{kp_id}")
async def api_run_regenerate_all(book_name: str, kp_id: int):
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    from services.image_generator import ImageGenerator
    gen = ImageGenerator()
    return await _run_in_background(gen.regenerate_all, kp_dir)


@app.post("/api/pipeline/{book_name}/pause-images/{kp_id}")
async def api_pause_images(book_name: str, kp_id: int):
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    flag = kp_dir / "pause.flag"
    from datetime import datetime
    flag.write_text(json.dumps({"paused_at": datetime.now().isoformat()}), encoding="utf-8")
    return {"success": True, "message": "暂停标志已设置"}


@app.get("/api/pipeline/{book_name}/generate-progress/{kp_id}")
async def api_generate_progress(book_name: str, kp_id: int):
    """轮询图片生成进度"""
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    if kp_dir:
        progress_path = kp_dir / "generate_progress.json"
        if progress_path.exists():
            try:
                return json.loads(progress_path.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {"stage": "unknown", "total": 0, "current": 0, "generated": 0, "failed": 0}


@app.get("/api/pipeline/{book_name}/step-progress/{kp_id}")
async def api_step_progress(book_name: str, kp_id: int):
    """轮询步骤实时进度"""
    from urllib.parse import unquote
    book_name = unquote(book_name)
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    if not kp_dir:
        return {"success": True, "data": {}}
    prog_path = Path(kp_dir) / "_step_progress.json"
    if not prog_path.exists():
        return {"success": True, "data": {}}
    try:
        data = json.loads(prog_path.read_text(encoding="utf-8"))
        return {"success": True, "data": data}
    except Exception:
        return {"success": True, "data": {}}


@app.get("/api/pipeline/{book_name}/pause-status/{kp_id}")
async def api_pause_status(book_name: str, kp_id: int):
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    flag = kp_dir / "pause.flag"
    return {"paused": flag.exists()}


@app.post("/api/switch-image-api/{api_num}")
async def api_switch_image_api(api_num: int):
    from services.image_generator import ImageGenerator
    gen = ImageGenerator()
    gen.switch_api(api_num)
    info = gen.get_active_api_info()
    return {"success": True, "active": info["active"], "name": info["name"], "size": info["size"]}


@app.get("/api/image-api-info")
async def api_get_image_api_info():
    from services.image_generator import ImageGenerator
    gen = ImageGenerator()
    return gen.get_active_api_info()


@app.get("/api/pipeline/{book_name}/failure-report/{kp_id}")
async def api_get_failure_report(book_name: str, kp_id: int):
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    report_path = kp_dir / "failure_report.json"
    if report_path.exists():
        return FileResponse(report_path, media_type="application/json")
    return {"error": "暂无失败报告"}


@app.post("/api/pipeline/{book_name}/run/generate-audio/{kp_id}")
async def api_run_generate_audio(book_name: str, kp_id: int):
    return await engine.run_generate_audio(book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/timeline-assembly/{kp_id}")
async def api_run_timeline_assembly(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_timeline_assembly, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/export-jianying/{kp_id}")
async def api_run_export_jianying(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_export_jianying, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/generate-subtitles/{kp_id}")
async def api_run_generate_subtitles(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_generate_subtitles, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/compose-final-video/{kp_id}")
async def api_run_compose_final_video(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_compose_final_video, book_name, kp_id)


@app.get("/api/pipeline/{book_name}/generate-progress/{kp_id}")
async def api_generate_progress(book_name: str, kp_id: int):
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    if not kp_dir:
        return {"error": "未找到目录"}
    progress_path = kp_dir / "generate_progress.json"
    if not progress_path.exists():
        return {"stage": "waiting", "message": "等待开始..."}
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return {"stage": "unknown", "message": "读取进度失败"}


@app.get("/api/pipeline/{book_name}/compose-progress/{kp_id}")
async def api_compose_progress(book_name: str, kp_id: int):
    kp_dir = engine._find_kp_dir(book_name, kp_id)
    if not kp_dir:
        return {"error": "未找到目录"}
    progress_path = kp_dir / "compose_progress.json"
    if not progress_path.exists():
        return {"stage": "waiting", "message": "等待开始..."}
    try:
        return json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return {"stage": "unknown", "message": "读取进度失败"}


@app.post("/api/restart-server")
async def api_restart_server():
    import subprocess, sys, os, time, threading
    subprocess.Popen([sys.executable, "web_app.py"], cwd=BASE_DIR, creationflags=subprocess.CREATE_NEW_CONSOLE)
    def _kill():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_kill, daemon=True).start()
    return {"success": True, "message": "服务正在重启"}


@app.post("/api/pipeline/{book_name}/run/visual-pipeline/{kp_id}")
async def api_run_visual_pipeline(book_name: str, kp_id: int):
    return await _run_in_background(engine.run_visual_pipeline, book_name, kp_id)


@app.post("/api/pipeline/{book_name}/run/full/{kp_id}")
async def api_run_full(book_name: str, kp_id: int):
    async def _run():
        return await engine.run_full_pipeline(book_name, kp_id)
    return await _run_in_background(lambda: asyncio.run(_run()))


# ============================================================
# 文件服务
# ============================================================

@app.get("/api/project/{book_name}/kp/{kp_id}/audio/{seg_name}")
async def api_get_audio(book_name: str, kp_id: int, seg_name: str):
    kp_dir = loader.kp_dir_path(book_name, kp_id)
    if not kp_dir:
        return JSONResponse({"error": "未找到目录"}, status_code=404)
    audio_path = kp_dir / "audio" / seg_name
    if not audio_path.exists():
        return JSONResponse({"error": "音频不存在"}, status_code=404)
    return FileResponse(str(audio_path), media_type="audio/mpeg")


@app.get("/api/project/{book_name}/kp/{kp_id}/video/final")
async def api_get_final_video(book_name: str, kp_id: int):
    kp_dir = loader.kp_dir_path(book_name, kp_id)
    if not kp_dir:
        return JSONResponse({"error": "未找到目录"}, status_code=404)
    video_path = kp_dir / "final.mp4"
    if not video_path.exists():
        return JSONResponse({"error": "视频不存在，请先生成"}, status_code=404)
    from urllib.parse import quote
    safe_name = f"{book_name}_kp{kp_id}.mp4"
    return FileResponse(str(video_path), media_type="video/mp4", filename=safe_name,
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(safe_name)}"})


@app.get("/api/project/{book_name}/kp/{kp_id}/json/{filename}")
async def api_get_json(book_name: str, kp_id: int, filename: str):
    data = loader.read_json(book_name, kp_id, filename)
    if data is None:
        return JSONResponse({"error": f"文件不存在: {filename}"}, status_code=404)
    return data


@app.post("/api/project/{book_name}/kp/{kp_id}/save-script")
async def api_save_script(request: Request):
    try:
        body = await request.json()
        kp_dir = loader.kp_dir_path(body.get("book_name", ""), body.get("kp_id", 0))
        if not kp_dir:
            return {"success": False, "error": "未找到知识点目录"}
        script, _ = loader.read_script(body.get("book_name", ""), body.get("kp_id", 0))
        if not script:
            script = {}
        script["full_script"] = body.get("full_script", "")
        path = kp_dir / "script_edited.json"
        path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"success": True, "path": str(path)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================================
if __name__ == "__main__":
    import uvicorn
    from fastapi.routing import APIRoute
    dy_routes = [r.path for r in app.routes if isinstance(r, APIRoute) and 'douyin' in r.path]
    print(f"\n  讲书升级Agent Web 工作台")
    if dy_routes:
        print(f"  抖音数据分析: 已加载 ({len(dy_routes)} 个API路由)")
    print(f"  访问: http://127.0.0.1:8001\n")
    uvicorn.run(app, host="127.0.0.1", port=8001)
