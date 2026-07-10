"""
内容规划服务 - 生成书本视频选题大纲
只生成大纲，不生成完整脚本
"""
import json
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR, OUTPUT_DIR
from utils.logger import log
from utils.json_utils import extract_json

class ContentPlanner:
    """书本 → 视频选题大纲"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置，请先设置 .env 文件")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    def _search_book_info(self, book_name: str) -> str:
        """自动搜索书籍信息（目录、简介、核心观点）"""
        import requests as _req
        info_parts = []

        # 搜索豆瓣
        try:
            sr = _req.get(
                "https://www.douban.com/search",
                params={"q": book_name},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            if sr.status_code == 200:
                # 提取第一个结果链接
                import re
                match = re.search(r'sid=\d+[^"]*"[^>]*>([^<]+)', sr.text)
                if match:
                    info_parts.append(f"豆瓣搜索结果: {match.group(1)}")
        except Exception:
            pass

        # 搜索维基百科/百度百科
        try:
            wiki_url = f"https://zh.wikipedia.org/w/api.php?action=query&list=search&srsearch={_req.utils.quote(book_name)}&format=json"
            wr = _req.get(wiki_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if wr.status_code == 200:
                wd = wr.json()
                pages = wd.get("query", {}).get("search", [])
                if pages:
                    snippet = pages[0].get("snippet", "")
                    snippet = re.sub(r'<[^>]+>', '', snippet)
                    info_parts.append(f"百科摘要: {snippet}")
        except Exception:
            pass

        return "\n\n".join(info_parts) if info_parts else ""

    def plan(
        self,
        book_name: str,
        toc_text: str = "",
        source_text: str = "",
        focus_hint: str = "",
        agent_context_block: str = "",
    ) -> dict:
        log.info(f"正在为《{book_name}》规划选题大纲...")

        toc = self._read_input(toc_text)
        source = self._read_input(source_text)
        focus = focus_hint or "聚焦对普通人学习、工作、生活有实际帮助的思维方法和人生智慧。避免政治敏感内容。"
        context = agent_context_block or ""

        # 自动搜索书籍信息（如果用户没提供原文）
        if not source:
            auto_info = self._search_book_info(book_name)
            if auto_info:
                source = f"[自动搜索到的书籍信息]\n{auto_info}"
                log.info(f"  已自动搜索到书籍信息 ({len(auto_info)} 字)")

        prompt = self._load_prompt("planner.txt")
        prompt = prompt.replace("{book_name}", book_name)
        prompt = prompt.replace("{toc_text}", toc if toc else "（未提供目录，请根据你对本书的了解推断章节结构）")
        prompt = prompt.replace("{source_text}", source if source else "（未提供原文/笔记）")
        prompt = prompt.replace("{focus_hint}", focus)
        prompt = prompt.replace("{agent_strategy_context}", context)

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请为《{book_name}》规划视频选题大纲。只生成大纲，不生成脚本。"},
            ],
            temperature=0.7,
            max_tokens=8000,
        )

        plan = extract_json(response.choices[0].message.content)

        # 标准化：扁平格式（core_insight）→ 兼容的数组格式（content_outline[].knowledge_points[]）
        plan = self._normalize_plan(plan)

        total = len(plan.get("content_outline", []))
        kp_count = 0
        for section in plan.get("content_outline", []):
            for kp in section.get("knowledge_points", []):
                kp_count += 1
        log.success(f"大纲生成完成：{total} 个章节，{kp_count} 个知识点")
        return plan

    def _normalize_plan(self, plan: dict) -> dict:
        """
        标准化：扁平格式（core_insight 字段）→ 兼容的数组格式（content_outline[].knowledge_points[]）
        也兼容旧版数组格式（如果 LLM 仍然输出数组）
        """
        # 如果已经是数组格式且有 content_outline，直接使用（仅保留第一个 KP，确保单视频）
        if "content_outline" in plan and isinstance(plan["content_outline"], list) and len(plan["content_outline"]) > 0:
            sections = plan["content_outline"]
            # 仅保留第一个章节的第一个知识点
            first_section = sections[0]
            kps = first_section.get("knowledge_points", [])
            if len(kps) > 1:
                log.warn(f"  检测到 {len(kps)} 个知识点，仅保留第一个（单视频策略）")
                first_section["knowledge_points"] = [kps[0]]
            elif len(kps) == 0:
                log.warn("  content_outline 中 knowledge_points 为空，尝试从 plan 顶层字段恢复...")
                # 尝试从 plan 顶层或 core_insight 取数据构建
                ci = plan.get("core_insight", {})
                if ci:
                    ci["id"] = 1
                    first_section["knowledge_points"] = [ci]
                else:
                    # 用 book_name 兜底
                    first_section["knowledge_points"] = [{
                        "id": 1,
                        "title": f"《{plan.get('book_name', '')}》核心思想",
                        "original_meaning": "",
                        "core_problem": "",
                        "why_useful": "",
                        "specific_book_content": "",
                        "suggested_video_length": "8-12分钟",
                    }]
            # 重新编号 ID
            for i, kp in enumerate(first_section.get("knowledge_points", [])):
                kp["id"] = i + 1
            plan["content_outline"] = [first_section]
            plan["total_knowledge_points"] = 1
            return plan

        # 扁平格式：从 core_insight 字段构建数组
        ci = plan.get("core_insight", {})
        if not ci:
            log.warn("  未找到 core_insight 字段，尝试从顶层字段推断...")
            ci = {k: v for k, v in plan.items() if k not in ("book_name", "planning_principle", "core_insight", "content_outline")}
            ci.setdefault("title", plan.get("title", plan.get("book_name", "")))

        ci["id"] = 1
        section = {
            "chapter": ci.get("chapter", "全书核心思想"),
            "chapter_summary": ci.get("chapter_summary", ci.get("original_meaning", "")[:80]),
            "knowledge_points": [ci],
        }
        plan["content_outline"] = [section]
        plan["total_knowledge_points"] = 1
        # 标记格式已升级（从扁平 core_insight 转为数组）
        had_ci = plan.pop("core_insight", None) is not None
        plan.pop("title", None)
        if had_ci:
            plan["_format_upgraded"] = True
        return plan

    def save_plan(self, plan: dict, output_dir: Path = None):
        """保存大纲，保存前自动标准化"""
        if output_dir is None:
            output_dir = OUTPUT_DIR / self._safe_name(plan.get("book_name", "unknown"))
        output_dir.mkdir(parents=True, exist_ok=True)

        # 双重保险：保存前再标准化一次（即使 plan() 没调用 normalize）
        plan = self._normalize_plan(plan)
        plan.pop("_format_upgraded", None)

        path = output_dir / "knowledge_plan.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"大纲已保存: {path}")
        return path

    def load_plan(self, book_name: str) -> dict | None:
        """加载已有大纲，自动标准化兼容新旧格式"""
        output_dir = OUTPUT_DIR / self._safe_name(book_name)
        path = output_dir / "knowledge_plan.json"
        if path.exists():
            plan = json.loads(path.read_text(encoding="utf-8"))
            # 标准化：兼容旧版 core_insight 扁平格式
            normalized = self._normalize_plan(plan)
            # 如果文件格式被标准化过（比如从 core_insight 转为 content_outline），写回磁盘
            if normalized.get("_format_upgraded"):
                normalized.pop("_format_upgraded", None)
                path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
                log.info(f"  已自动升级大纲文件格式: {path.name}")
            return normalized
        return None

    def find_kp(self, plan: dict, kp_id: int) -> dict | None:
        """根据 ID 查找知识点"""
        for section in plan.get("content_outline", []):
            for kp in section.get("knowledge_points", []):
                if kp.get("id") == kp_id:
                    return {
                        **kp,
                        "chapter": section.get("chapter", ""),
                        "book_name": plan.get("book_name", ""),
                    }
        return None

    def print_plan(self, plan: dict):
        """打印知识点列表"""
        print(f"\n{'='*60}")
        print(f"《{plan.get('book_name', '')}》选题大纲")
        print(f"划分原则: {plan.get('planning_principle', '')}")
        print(f"{'='*60}")

        for section in plan.get("content_outline", []):
            print(f"\n  [{section.get('chapter', '')}]")
            print(f"  {section.get('chapter_summary', '')}")
            print()
            for kp in section.get("knowledge_points", []):
                kp_id = kp.get("id", "?")
                title = kp.get("title", "")
                length = kp.get("suggested_video_length", "")
                diff = kp.get("difficulty", "")
                problem = kp.get("core_problem", "")
                print(f"  [{kp_id}] {title}")
                print(f"      时长: {length}  |  难度: {diff}")
                print(f"      核心问题: {problem}")
                merge = kp.get("should_merge_with_other_points", False)
                if merge:
                    print(f"      [!] 建议: {kp.get('merge_suggestion', '')}")
                print()

        # 推荐首发
        recs = plan.get("recommended_first_videos", [])
        if recs:
            print(f"  推荐先做:")
            for r in recs:
                print(f"    → ID {r.get('knowledge_point_id', '?')}: {r.get('reason', '')}")

        print(f"\n  共 {plan.get('total_knowledge_points', sum(len(s.get('knowledge_points', [])) for s in plan.get('content_outline', [])))} 个知识点")
        print(f"{'='*60}\n")

    # ========== 工具 ==========

    def _read_input(self, text_or_path: str) -> str:
        if not text_or_path:
            return ""
        path = Path(text_or_path)
        if path.exists() and path.is_file():
            log.info(f"读取文件: {path}")
            return path.read_text(encoding="utf-8")
        alt = Path.cwd() / text_or_path
        if alt.exists() and alt.is_file():
            log.info(f"读取文件: {alt}")
            return alt.read_text(encoding="utf-8")
        return text_or_path

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        log.warn(f"未找到提示词: {filename}")
        return ""

    def _safe_name(self, name: str) -> str:
        safe = "".join(c for c in name if c.isalnum() or c in " _-()（）")
        return safe.strip() or "unnamed"
