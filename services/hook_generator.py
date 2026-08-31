"""
钩子生成服务 — 量产 10 条候选钩子 → 选 1 条主钩子

流程:
  1. generate_hooks()     高温度(0.7) 生成 10 条候选
  2. rank_hooks()         低温度(0.3) 评分排序（可选）
  3. select_hook()        选定主钩子
  4. get_primary_hook()   下游消费
"""
import json
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR
from utils.logger import log
from utils.json_utils import extract_json


HOOK_CANDIDATES_FILE = "hook_candidates.json"


class HookGenerator:
    """图书知识点 → 10 条候选钩子 → 选定主钩子"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    # ================================================================
    # 公共接口
    # ================================================================

    def generate_hooks(self, kp_info: dict, growth_signals: str = "") -> list[str]:
        """
        为一本书的知识点生成 10 条候选钩子。

        幂等：同一 kp_dir 已有 hook_candidates.json 且 primary_hook 已选定 → 跳过生成。
        """
        book_name = kp_info.get("book_name", "")
        kp_title = kp_info.get("title", "")
        log.info(f"正在为「{kp_title}」生成 10 条候选钩子...")

        prompt = self._load_prompt("hook_generator.txt")
        prompt = prompt.replace("{book_name}", book_name)
        prompt = prompt.replace("{author}", kp_info.get("author", ""))
        prompt = prompt.replace("{category}", kp_info.get("category", "认知"))
        prompt = prompt.replace("{content_summary}", self._build_summary(kp_info))
        prompt = prompt.replace("{core_problem}", kp_info.get("core_problem", ""))
        prompt = prompt.replace("{universal_relevance}",
                                kp_info.get("universal_relevance", kp_info.get("why_useful", "")))
        prompt = prompt.replace("{growth_signals}", growth_signals or self._default_growth_message())

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一位资深短视频文案专家。只输出 JSON 数组，不要任何其他文字。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=2000,
        )

        raw = response.choices[0].message.content or "[]"
        hooks = self._safe_parse_hooks(raw)
        log.success(f"生成完成：{len(hooks)} 条候选钩子")
        return hooks

    def rank_hooks(self, kp_info: dict, hooks: list[str]) -> dict:
        """
        对候选钩子评分排序，返回推荐索引。
        低温度(0.3)保证评分稳定性。
        """
        if not hooks:
            return {"rankings": [], "recommended_index": 0}

        book_name = kp_info.get("book_name", "")
        prompt = self._load_prompt("hook_ranker.txt")
        candidates_text = "\n".join(f"[{i}] {h}" for i, h in enumerate(hooks))
        prompt = prompt.replace("{book_name}", book_name)
        prompt = prompt.replace("{category}", kp_info.get("category", "认知"))
        prompt = prompt.replace("{content_summary}", self._build_summary(kp_info))
        prompt = prompt.replace("{hook_candidates}", candidates_text)

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一位短视频数据策略师。只输出 JSON，不要任何其他文字。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=3000,
        )

        raw = response.choices[0].message.content or "{}"
        try:
            result = extract_json(raw)
            log.info(f"评分完成，推荐索引: {result.get('recommended_index', 0)}")
            return result
        except ValueError as e:
            log.warn(f"  评分 JSON 解析失败，使用默认评分（选第一条）: {str(e)[:80]}")
            # 降级：按原始顺序返回默认评分，推荐第0条
            rankings = [{"index": i, "score": 5, "reason": "默认评分（AI评分失败）"} for i in range(len(hooks))]
            return {"rankings": rankings, "recommended_index": 0, "recommendation_reason": "AI评分失败，默认选第一条"}

    def select_hook(self, kp_dir: Path, hook_index: int) -> dict:
        """
        选定主钩子（用户或规则选择）。
        保存到 hook_candidates.json。
        """
        candidates_path = kp_dir / HOOK_CANDIDATES_FILE
        if not candidates_path.exists():
            raise ValueError("未找到候选钩子，请先生成")

        candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
        hooks = candidates.get("candidates", [])
        if hook_index < 0 or hook_index >= len(hooks):
            raise ValueError(f"钩子索引越界: {hook_index} (共 {len(hooks)} 条)")

        candidates["primary_hook"] = hooks[hook_index]
        candidates["primary_index"] = hook_index
        candidates_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"已选定主钩子 [#{hook_index}]: {hooks[hook_index][:60]}...")
        return candidates

    def auto_select(self, kp_dir: Path, kp_info: dict) -> dict:
        """
        自动评分并选定最佳钩子（无需人工干预）。
        """
        candidates = self.load_candidates(kp_dir)
        if not candidates:
            raise ValueError("未找到候选钩子，请先生成")

        # 如果已有选定钩子，直接返回
        if candidates.get("primary_hook"):
            return candidates

        hooks = candidates.get("candidates", [])
        # AI 评分
        ranking = self.rank_hooks(kp_info, hooks)
        recommended = ranking.get("recommended_index", 0)
        return self.select_hook(kp_dir, recommended)

    # ================================================================
    # 持久化
    # ================================================================

    def save_candidates(self, hooks: list[str], kp_dir: Path, kp_info: dict = None) -> Path:
        """保存候选钩子到 KP 目录"""
        kp_dir = Path(kp_dir)
        kp_dir.mkdir(parents=True, exist_ok=True)
        path = kp_dir / HOOK_CANDIDATES_FILE

        # 如果已存在且有 primary_hook，保留原有选择
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass

        data = {
            "book_name": (kp_info or {}).get("book_name", existing.get("book_name", "")),
            "kp_title": (kp_info or {}).get("title", existing.get("kp_title", "")),
            "generated_at": existing.get("generated_at", ""),
            "candidates": hooks,
            "primary_hook": existing.get("primary_hook", None),
            "primary_index": existing.get("primary_index", None),
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"候选钩子已保存: {path}")
        return path

    def load_candidates(self, kp_dir: Path) -> dict:
        """加载候选钩子"""
        path = Path(kp_dir) / HOOK_CANDIDATES_FILE
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get_primary_hook(self, kp_dir: Path) -> str:
        """获取选定的主钩子（供下游消费）"""
        candidates = self.load_candidates(kp_dir)
        return candidates.get("primary_hook", "")

    def has_selected_hook(self, kp_dir: Path) -> bool:
        """检查是否已选定主钩子"""
        return bool(self.get_primary_hook(kp_dir))

    # ================================================================
    # 内部
    # ================================================================

    def _safe_parse_hooks(self, raw: str) -> list[str]:
        """三层 JSON 解析容错 + 截断保护 + LLM前缀剥离 + 调试日志"""
        text = raw.strip()
        log.info(f"  LLM 原始返回前200字: {text[:200]}")

        # 剥离 LLM 自然语言前缀（"好的，"，"以下是" 等）
        brace = text.find("[")
        curl = text.find("{")
        start_candidates = [x for x in [brace, curl] if x >= 0]
        if start_candidates:
            start = min(start_candidates)
            if start > 0 and len(text[:start].strip()) < 200:
                text = text[start:].strip()
                log.info(f"  已剥离 LLM 前缀，从字符 {start} 开始解析")

        # 剥离 markdown 代码围栏
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl > 0:
                text = text[first_nl:].strip()
            if text.endswith("```"):
                text = text[:-3].strip()
            text = text.strip()

        # 尝试1: 直接 JSON.parse
        hooks = []
        try:
            hooks = json.loads(text)
        except Exception as e:
            log.info(f"  直接解析失败: {e}")

        # 尝试2: 从第一个 [ 到最后一个 ] 切片再解析
        if not isinstance(hooks, list):
            try:
                start = text.find("[")
                end = text.rfind("]")
                if start >= 0 and end > start:
                    sliced = text[start:end + 1]
                    hooks = json.loads(sliced)
                    log.info(f"  通过 [ ] 切片解析成功")
            except Exception as e:
                log.info(f"  [ ] 切片解析失败: {e}")

        # 尝试3: 按行提取引号内容（兜底）
        if not isinstance(hooks, list) or len(hooks) == 0:
            import re
            lines = text.split("\n")
            extracted = []
            for line in lines:
                line = line.strip().strip('",').strip()
                if line and not line.startswith(("{", "}", "[", "]")):
                    # 去掉序号前缀如 "1. "、"["、"]"
                    cleaned = re.sub(r'^[\d\s\."\'\[\],-]+', '', line).strip().strip('"').strip()
                    if cleaned and len(cleaned) > 5 and cleaned not in extracted:
                        extracted.append(cleaned)
            if len(extracted) >= 3:
                hooks = extracted
                log.warn(f"  使用行提取兜底，获取 {len(extracted)} 条")

        # 过滤非字符串和空值，最多保留 10 条
        hooks = [h.strip().strip('"').strip("'") for h in hooks if isinstance(h, str) and h.strip() and len(h.strip()) > 3]
        log.info(f"  最终解析: {len(hooks)} 条钩子")
        return hooks[:10]

    def _build_summary(self, kp_info: dict) -> str:
        """从 kp_info 构建核心内容摘要"""
        parts = []
        title = kp_info.get("title", "")
        if title:
            parts.append(f"主题：{title}")
        original = kp_info.get("original_meaning", "")
        if original:
            parts.append(f"原书原意：{original}")
        specific = kp_info.get("specific_book_content", "")
        if specific:
            if isinstance(specific, list):
                specific = "\n".join(f"- {s}" for s in specific if s)
            parts.append(f"书中具体内容：\n{specific}")
        return "\n\n".join(parts)

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        log.warn(f"未找到提示词: {filename}")
        return ""

    @staticmethod
    def _default_growth_message() -> str:
        return "（暂无历史数据，按默认策略生成）"

    @staticmethod
    def build_growth_signals(memory_dir: Path = None) -> str:
        """
        从 self_growth_memory 和 feedback_memory 构建钩子增长信号文本块。
        供 pipeline_engine / web_app 在调用 generate_hooks 前读取。
        """
        if memory_dir is None:
            from config import PROJECT_ROOT
            memory_dir = PROJECT_ROOT / "memory"

        parts = []
        try:
            import json as _json
            sg_path = memory_dir / "self_growth_memory.json"
            if sg_path.exists():
                sg = _json.loads(sg_path.read_text(encoding="utf-8"))
                openings = sg.get("openings", {}).get("rankings", [])
                if openings:
                    parts.append("## 历史高表现开场类型（按播放量排名）")
                    for i, o in enumerate(openings[:3]):
                        pct = o.get("pct_better_than_average", 0)
                        sign = "+" if pct >= 0 else ""
                        parts.append(f"  #{i+1} {o['opening']}: "
                                     f"较均值 {sign}{pct:.0f}%, "
                                     f"样本 {o['sample_count']}条")
                    parts.append("→ 优先采用以上开场类型的视角和表达方式")

                structures = sg.get("content_structures", {}).get("rankings", [])
                if structures:
                    parts.append("")
                    parts.append("## 历史高表现内容结构（按播放量排名）")
                    for i, s in enumerate(structures[:3]):
                        pct = s.get("pct_better_than_average", 0)
                        sign = "+" if pct >= 0 else ""
                        parts.append(f"  #{i+1} {s['structure']}: "
                                     f"较均值 {sign}{pct:.0f}%, "
                                     f"样本 {s['sample_count']}条")
                    parts.append("→ 钩子的表达结构优先参考以上高表现模式")

            fb_path = memory_dir / "feedback_memory.json"
            if fb_path.exists():
                fb = _json.loads(fb_path.read_text(encoding="utf-8"))
                prefs = fb.get("preferences", {})
                liked = prefs.get("liked_styles", [])
                disliked = prefs.get("disliked_styles", [])
                if liked or disliked:
                    parts.append("")
                    parts.append("## 用户偏好")
                    if liked:
                        parts.append(f"  喜欢风格：{'、'.join(liked)}")
                    if disliked:
                        parts.append(f"  不喜欢风格：{'、'.join(disliked)}")
        except Exception:
            return "（无法读取增长数据，按默认策略生成）"

        return "\n".join(parts) if parts else "（暂无历史增长数据）"
