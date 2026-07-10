"""
脚本生成服务

模式 A: generate_book_script  — 整本书概述（保留但不推荐）
模式 B: generate_knowledge_point — 单一知识点深度讲解（主要模式）
"""
import json
import re
import traceback
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR, IMAGE_STYLE
from utils.logger import log
from utils.json_utils import extract_json

# ========== 分析角度（仅模式 A 使用）==========
ANALYSIS_ANGLES = {
    "auto": "自动选择最适合的分析角度",
    "philosophy": "从哲学思辨的角度切入",
    "practical": "从实用干货的角度切入",
    "emotional": "从情感共鸣的角度切入",
    "story": "从故事驱动的角度切入",
}

class ScriptGenerator:
    """书本 → 视频脚本"""

    def __init__(self):
        self._client = None
        self.angle = "auto"

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置，请先设置 .env 文件")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    # ================================================================
    # 模式 B: 单一知识点深度讲解（主要模式）
    # ================================================================

    def generate_knowledge_point(self, kp_info: dict, mode: str = "normal",
                                  agent_context_block: str = "") -> dict:
        """
        为一个知识点生成完整的深度讲解脚本（两步法）

        Step 1: 生成 script_structure（结构 + 概要）
        Step 2: 基于结构生成 full_script（完整讲稿）

        分开两步是因为 DeepSeek 输出 token 有限，一步生成会被截断。
        """
        book_name = kp_info.get("book_name", "")
        chapter = kp_info.get("chapter", "")
        kp_title = kp_info.get("title", "")
        log.info(f"正在为「{kp_title}」生成深度讲解脚本...")

        # ====== Step 1: 生成结构 ======
        log.info("  [1/2] 生成脚本结构...")
        structure = self._generate_structure(kp_info, agent_context_block=agent_context_block)
        log.success("  结构生成完成")

        # ====== Step 2: 生成完整脚本（带自动续写） ======
        log.info("  [2/2] 撰写完整讲稿...")
        full_script_text = self._generate_full_script(kp_info, structure, mode, agent_context_block=agent_context_block)
        log.success(f"  初次撰写完成（{len(full_script_text)} 字）")

        # 字数不够则自动续写（最多续写2轮）
        MIN_TARGET = 2500
        for round_i in range(1, 3):
            if len(full_script_text) >= MIN_TARGET:
                break
            log.info(f"  字数不足({len(full_script_text)} < {MIN_TARGET})，正在第{round_i}轮续写...")
            continuation = self._generate_continuation(kp_info, full_script_text, round_i)
            if continuation and len(continuation) > 200:
                full_script_text += "\n\n" + continuation
                log.success(f"  续写后字数: {len(full_script_text)}")
            else:
                log.warn("  续写产出不足，停止")
                break

        # ====== 去掉第一段（LLM 生成的唠叨开头，用开场白替代） ======
        paragraphs = [p.strip() for p in full_script_text.split("\n\n") if p.strip()]
        if len(paragraphs) > 1:
            removed = paragraphs[0]
            full_script_text = "\n\n".join(paragraphs[1:])
            log.info(f"  去掉第一段（{len(removed)}字），从第二段开始")

        # ====== Step 2.5: 生成开场白 ======
        log.info("  [2.5/3] 生成开场白...")
        opening_data = self._generate_opening(kp_info, structure, agent_context_block=agent_context_block)
        opening_text = opening_data.get("opening", "").strip()
        if opening_text:
            full_with_opening = opening_text + "\n\n" + full_script_text
            log.success(f"  开场白生成完成（{len(opening_text)} 字）→ 已前置到正文")
        else:
            full_with_opening = full_script_text
            log.warn("  开场白生成为空，使用原始正文")

        # ====== 字数统计 ======
        char_count = len(full_with_opening)
        target = "4000-5000字（8分钟目标）"

        estimated_minutes = char_count / 230
        if estimated_minutes < 5:
            computed_length = f"约{int(estimated_minutes)}-{int(estimated_minutes) + 2}分钟"
        elif estimated_minutes < 8:
            computed_length = "5-8分钟"
        elif estimated_minutes < 12:
            computed_length = "8-12分钟"
        elif estimated_minutes < 15:
            computed_length = "12-15分钟"
        elif estimated_minutes < 20:
            computed_length = "15-20分钟"
        else:
            computed_length = "20分钟以上"

        log.success(f"脚本生成完成：full_script 共 {char_count} 字（目标{target}）→ 预计 {computed_length}")
        if char_count < 3000:
            log.warn("  字数不足3000，视频可能不到6分钟。")

        script = {
            "book_name": book_name,
            "chapter": chapter,
            "knowledge_point": kp_title,
            "source_scope": structure.get("source_scope", kp_info.get("source_scope", "")),
            "estimated_video_length": structure.get("estimated_video_length", "") or computed_length,
            "suggested_video_length": computed_length,
            "length_reason": structure.get("length_reason", kp_info.get("length_reason", "")),
            "script_structure": structure,
            "opening": opening_text,
            "opening_mode": opening_data.get("mode", ""),
            "full_script": full_with_opening,
            "paragraph_labels": getattr(self, '_last_paragraph_labels', []),
        }
        return script

    def _generate_structure(self, kp_info: dict, agent_context_block: str = "") -> dict:
        """Step 1: 生成脚本结构"""
        prompt = self._load_prompt("script_long.txt")
        book_name = kp_info.get("book_name", "")
        kp_title = kp_info.get("title", "")
        universal_context = kp_info.get("universal_relevance", "") or (
            f"这个知识与普通人的关系：{kp_info.get('why_useful', '')}"
        )
        replacements = {
            "{book_name}": book_name,
            "{chapter}": kp_info.get("chapter", ""),
            "{kp_title}": kp_title,
            "{original_meaning}": kp_info.get("original_meaning", ""),
            "{core_problem}": kp_info.get("core_problem", ""),
            "{why_useful}": kp_info.get("why_useful", ""),
            "{source_scope}": kp_info.get("source_scope", ""),
            "{relation_context}": universal_context,
            "{suggested_length}": kp_info.get("suggested_video_length", ""),
            "{length_reason}": kp_info.get("length_reason", ""),
            "{specific_book_content}": self._format_specific_content(kp_info.get("specific_book_content")),
            "{agent_strategy_context}": agent_context_block or "",
        }
        for key, val in replacements.items():
            prompt = prompt.replace(key, val)
        prompt += "\n\n## 重要提示\n本次只需要输出 script_structure 部分，full_script 字段留空字符串。只输出结构，不要输出完整脚本。"
        response = self._call_llm(
            prompt,
            f"请为知识点「{kp_title}」设计脚本结构。只需要结构，不需要写 full_script。",
            max_tokens=8000,
        )
        result = extract_json(response)
        return result.get("script_structure", result)

    def _generate_full_script(self, kp_info: dict, structure: dict, mode: str = "normal",
                              agent_context_block: str = "") -> str:
        """Step 2: 基于结构写完整讲稿"""
        self._last_paragraph_labels = []
        prompt_file = "full_script_writer_worldcup.txt" if mode == "worldcup" else "full_script_writer.txt"
        prompt = self._load_prompt(prompt_file)
        prompt = prompt.replace("{book_name}", kp_info.get("book_name", ""))
        prompt = prompt.replace("{kp_title}", kp_info.get("title", ""))
        prompt = prompt.replace("{suggested_length}", kp_info.get("suggested_video_length", ""))
        prompt = prompt.replace("{structure_json}", json.dumps(structure, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{agent_strategy_context}", agent_context_block or "")
        specific_content = kp_info.get("specific_book_content", "")
        if specific_content:
            prompt = prompt.replace("{specific_book_content}", self._format_specific_content(specific_content))
        else:
            backup_content = structure.get("specific_book_content", kp_info.get("original_meaning", ""))
            prompt = prompt.replace("{specific_book_content}", self._format_specific_content(backup_content))
        response = self._call_llm(
            prompt,
            f"请根据上面的结构，写出完整的讲解稿。只输出 JSON，full_script 字段中包含完整讲稿，paragraph_labels 中标注每段目的。",
            max_tokens=8000,
        )
        result = extract_json(response)
        full_script = result.get("full_script", "")
        paragraph_labels = result.get("paragraph_labels", [])
        if paragraph_labels:
            self._last_paragraph_labels = paragraph_labels
            log.info(f"  段落标签: {len(paragraph_labels)} 段")
        return full_script

    def _generate_continuation(self, kp_info, existing_text, round_num, agent_context_block=""):
        """字数不足时续写讲稿"""
        book_name = kp_info.get("book_name", "")
        kp_title = kp_info.get("title", "")
        prompt = (
            "你正在为书籍《" + book_name + "》的知识点「" + kp_title + "」撰写讲稿。\n\n"
            "当前的讲稿已有 " + str(len(existing_text)) + " 字，但还不够（目标是4000字以上）。\n\n"
            "请继续往下写，在现有内容的基础上深入展开：\n"
            "1. 增加更多的推理细节和论证过程\n"
            "2. 补充更多书中的具体案例、故事、数据\n"
            "3. 把已有的观点展开得更充分\n"
            "4. 如果有省略的推理过程，补全它\n\n"
            "不要重复已有的内容，直接续写新段落。\n"
            "用「我们」口吻，保持风格一致。\n\n"
            "前面已经写到的内容（供参考，不要重复）：\n" + existing_text[-500:]
        )
        try:
            response = self._call_llm(
                "你是一个讲稿续写专家。请续写讲稿，增加深度和细节。直接输出续写内容，不要JSON包裹。",
                prompt,
                max_tokens=6000,
            )
            text = response.strip()
            if text.startswith("{"):
                try:
                    parsed = json.loads(text)
                    text = parsed.get("full_script", parsed.get("continuation", parsed.get("text", text)))
                except Exception:
                    pass
            return text.strip().strip("\"'")
        except Exception as e:
            log.warn("  续写失败: " + str(e))
            return ""

    # ================================================================
    # 模式 A: 整本书概述（保留）
    # ================================================================

    def generate_book_script(
        self, book_name: str, num_segments: int = 8, image_style: str = "", angle: str = "auto"
    ) -> dict:
        """整本书概述模式"""
        self.angle = angle
        style = image_style or IMAGE_STYLE
        log.info(f"[1/3] 深度分析《{book_name}》...")
        analysis = self._deep_analysis(book_name)
        log.info("[2/3] 教学设计...")
        bridge = self._bridge_design(book_name, analysis)
        log.info("[3/3] 撰写脚本...")
        script = self._teach_write(book_name, analysis, bridge, num_segments, style)
        script["_analysis"] = analysis
        script["_bridge"] = bridge
        log.success(f"脚本完成：{len(script.get('segments', []))} 段")
        return script

    def _deep_analysis(self, book_name: str) -> dict:
        prompt = self._load_prompt("book_deep_analysis.txt")
        prompt = prompt.replace("{book_name}", book_name)
        return extract_json(self._call_llm(prompt, f"请深度分析《{book_name}》。"))

    def _bridge_design(self, book_name: str, analysis: dict) -> dict:
        prompt = self._load_prompt("bridge_design.txt")
        prompt = prompt.replace("{book_name}", book_name)
        prompt = prompt.replace("{analysis}", json.dumps(analysis, ensure_ascii=False, indent=2))
        return extract_json(self._call_llm(prompt, f"请为《{book_name}》设计教学策略。"))

    def _teach_write(self, book_name: str, analysis: dict, bridge: dict, num_segments: int, style: str) -> dict:
        prompt = self._load_prompt("teach_write.txt")
        prompt = prompt.replace("{book_name}", book_name)
        prompt = prompt.replace("{num_segments}", str(num_segments))
        prompt = prompt.replace("{image_style}", style)
        prompt = prompt.replace("{analysis}", json.dumps(analysis, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{bridge}", json.dumps(bridge, ensure_ascii=False, indent=2))
        script = extract_json(self._call_llm(prompt, f"请撰写脚本。"))
        return script

    def _generate_opening(self, kp_info: dict, structure: dict,
                           agent_context_block: str = "") -> dict:
        """为脚本生成开场白（可选的第三步）"""
        try:
            prompt_template = self._load_prompt("opening_writer.txt")
            if not prompt_template.strip():
                return {"opening": "", "mode": ""}
            prompt = prompt_template.replace("{book_name}", kp_info.get("book_name", ""))
            kp_title = kp_info.get("title", "")
            prompt = prompt.replace("{kp_title}", kp_title)
            full_script = structure if isinstance(structure, str) else json.dumps(structure, ensure_ascii=False, indent=2)
            prompt = prompt.replace("{full_script}", full_script[:3000])
            response = self._call_llm(prompt, f"请为「{kp_title}」生成开场白。", max_tokens=2000)
            return extract_json(response)
        except Exception as e:
            log.warn(f"开场白生成失败: {e}")
            return {"opening": "", "mode": ""}

    def _format_specific_content(self, content) -> str:
        if not content:
            return "无"
        if isinstance(content, str):
            return content[:2000]
        if isinstance(content, list):
            items = []
            for c in content:
                if isinstance(c, dict):
                    items.append(json.dumps(c, ensure_ascii=False))
                else:
                    items.append(str(c))
            return "\n".join(items)[:2000]
        return str(content)[:2000]

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Prompt 文件不存在: {filename}")

    def _call_llm(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content

    def _extract_json(self, text: str) -> dict:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, TypeError):
                pass
        result = self._repair_truncated_json(text)
        if result:
            log.warn("JSON 被截断，已自动修复")
            return result
        raise ValueError(f"无法解析 JSON:\n{text[:500]}")

    def _repair_truncated_json(self, text: str) -> dict | None:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            text = match.group(1)
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            match = re.search(r"\{[\s\S]*", text)
        if not match:
            return None
        truncated = match.group(0)
        open_braces = truncated.count("{") - truncated.count("}")
        open_brackets = truncated.count("[") - truncated.count("]")
        in_string = False
        i = len(truncated) - 1
        while i >= 0 and truncated[i] != "\n":
            if truncated[i] == '"' and (i == 0 or truncated[i-1] != "\\"):
                in_string = not in_string
            i -= 1
        if in_string:
            last_quote = truncated.rfind('"')
            if last_quote > 0:
                truncated = truncated[:last_quote] + '"'
        truncated += "]" * open_brackets
        truncated += "}" * open_braces
        try:
            return json.loads(truncated)
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    def save_script(self, script: dict, output_dir: Path):
        """保存脚本文件"""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "script.json"
        path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"脚本已保存: {path}")
        return str(path)
