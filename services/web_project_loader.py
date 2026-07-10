"""
Web 工作台数据加载器 — 只读扫描 output 目录
"""
import json
from pathlib import Path
from collections import Counter

OUTPUT_DIR = Path(__file__).parent.parent / "output"


class ProjectLoader:
    """扫描 output 目录，加载各层数据"""

    def __init__(self):
        self.output_dir = OUTPUT_DIR

    # ---- 项目级别 ----

    def list_books(self) -> list[dict]:
        """列出所有书籍项目"""
        if not self.output_dir.exists():
            return []
        books = []
        for d in sorted(self.output_dir.iterdir()):
            if not d.is_dir():
                continue
            kps = self.list_kp_dirs(d.name)
            plan = self._read_plan(d.name)
            books.append({
                "name": d.name,
                "has_plan": plan is not None,
                "kp_count": len(kps),
                "total_kps": plan.get("total_knowledge_points", len(kps)) if plan else len(kps),
            })
        return books

    def list_kp_dirs(self, book_name: str) -> list[Path]:
        """列出某本书下的知识点目录"""
        book_dir = self.output_dir / book_name
        if not book_dir.exists():
            return []
        return sorted([d for d in book_dir.iterdir() if d.is_dir() and d.name.startswith("kp_")])

    def book_summary(self, book_name: str) -> dict:
        """获取书籍概览"""
        plan = self._read_plan(book_name)
        kps = self.list_kp_dirs(book_name)
        kp_list = []
        for kd in kps:
            info = self._kp_info(kd)
            if info:
                kp_list.append(info)
        return {
            "book_name": book_name,
            "has_plan": plan is not None,
            "plan": plan,
            "kp_count": len(kps),
            "kps": kp_list,
        }

    # ---- 知识点级别 ----

    def kp_detail(self, book_name: str, kp_id: int) -> dict:
        """获取知识点完整信息（优先使用 knowledge_plan.json 精确路径）"""
        kp_dir = self._kp_dir_from_plan(book_name, kp_id)
        if not kp_dir:
            for d in self.list_kp_dirs(book_name):
                if d.name.startswith(f"kp_{kp_id:03d}"):
                    kp_dir = d
                    break
        if not kp_dir:
            return {"error": f"未找到知识点目录 kp_{kp_id:03d}"}
        return self._kp_full_detail(kp_dir, book_name)

    def kp_dir_path(self, book_name: str, kp_id: int) -> Path | None:
        """获取知识点目录路径（优先使用 knowledge_plan.json 精确路径）"""
        kp_dir = self._kp_dir_from_plan(book_name, kp_id)
        if not kp_dir:
            # fallback: 优先选有 final.mp4 或 script.json 的目录
            candidates = [d for d in self.list_kp_dirs(book_name) if d.name.startswith(f"kp_{kp_id:03d}")]
            if candidates:
                # 优先 final.mp4 > script.json > 第一个
                for c in candidates:
                    if (c / "final.mp4").exists():
                        return c
                for c in candidates:
                    if (c / "script.json").exists():
                        return c
                return candidates[0]
        return kp_dir

    def _kp_dir_from_plan(self, book_name: str, kp_id: int) -> Path | None:
        """从 knowledge_plan.json 读取精确的 kp_dir（直接读原始 JSON，避免 ContentPlanner 过滤）"""
        plan_path = self.output_dir / book_name / "knowledge_plan.json"
        if not plan_path.exists():
            return None
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        for sec in plan.get("content_outline", []):
            for kp in sec.get("knowledge_points", []):
                if kp.get("id") == kp_id:
                    kp_dir_str = kp.get("kp_dir", "")
                    if kp_dir_str:
                        p = Path(kp_dir_str)
                        if p.exists():
                            return p
        return None

    # ---- 文件读取 ----

    def read_json(self, book_name: str, kp_id: int, filename: str) -> dict | None:
        """读取指定 JSON 文件"""
        kp_dir = self.kp_dir_path(book_name, kp_id)
        if not kp_dir:
            return None
        return self._read_json(kp_dir / filename)

    def read_script(self, book_name: str, kp_id: int) -> tuple[dict | None, str]:
        """按优先级读取脚本，返回 (data, source_name)"""
        kp_dir = self.kp_dir_path(book_name, kp_id)
        if not kp_dir:
            return None, ""
        for name in ["script_edited.json", "script_safe.json", "script.json"]:
            data = self._read_json(kp_dir / name)
            if data:
                return data, name
        return None, ""

    # ---- 内部 ----

    def _read_plan(self, book_name: str) -> dict | None:
        """读取大纲，自动标准化 core_insight 格式。通过 ContentPlanner.load_plan 确保兼容性"""
        try:
            from services.content_planner import ContentPlanner
            return ContentPlanner().load_plan(book_name)
        except Exception:
            # 兜底：直接读取
            return self._read_json(self.output_dir / book_name / "knowledge_plan.json")

    def _kp_info(self, kp_dir: Path) -> dict:
        """提取知识点基本信息"""
        parts = kp_dir.name.split("_", 2)
        if len(parts) < 2:
            return None
        kp_id_str = parts[1]
        try:
            kp_id = int(kp_id_str)
        except ValueError:
            kp_id = 0
        title = parts[2] if len(parts) > 2 else ""

        files = {
            "script": (kp_dir / "script.json").exists(),
            "script_safe": (kp_dir / "script_safe.json").exists(),
            "script_edited": (kp_dir / "script_edited.json").exists(),
            "quality_check": (kp_dir / "quality_check.json").exists(),
            "safety_check": (kp_dir / "safety_check.json").exists(),
            "content_units": (kp_dir / "content_units.json").exists(),
            "visual_beats": (kp_dir / "visual_beats.json").exists(),
            "image_prompts": (kp_dir / "image_prompts.json").exists(),
        }

        # 读脚本取标题
        script = None
        for n in ["script_edited.json", "script_safe.json", "script.json"]:
            script = self._read_json(kp_dir / n)
            if script:
                break
        display_title = title
        if script:
            display_title = script.get("knowledge_point", title)

        return {
            "kp_id": kp_id,
            "kp_title": display_title,
            "dir_name": kp_dir.name,
            "files": files,
        }

    def _kp_full_detail(self, kp_dir: Path, book_name: str) -> dict:
        """获取完整详情"""
        result = {"book_name": book_name, "kp_dir": kp_dir.name}
        result["files"] = {}
        for name in ["script.json", "script_safe.json", "script_edited.json",
                      "quality_check.json", "safety_check.json",
                      "content_units.json", "visual_beats.json", "image_prompts.json",
                      "timeline.json"]:
            result["files"][name] = (kp_dir / name).exists()

        # 脚本
        script, src = None, ""
        for n in ["script_edited.json", "script_safe.json", "script.json"]:
            script = self._read_json(kp_dir / n)
            if script:
                src = n
                break
        result["script"] = script
        result["script_source"] = src

        # 各层数据
        result["quality_check"] = self._read_json(kp_dir / "quality_check.json")
        result["safety_check"] = self._read_json(kp_dir / "safety_check.json")
        result["content_units"] = self._read_json(kp_dir / "content_units.json")
        result["visual_beats"] = self._read_json(kp_dir / "visual_beats.json")

        ip = self._read_json(kp_dir / "image_prompts.json")
        if ip:
            items = ip.get("items", [])
            counts = Counter(i.get("image_status", "?") for i in items)
            ip["_status_counts"] = dict(counts)
        result["image_prompts"] = ip

        # 时间线
        tl = self._read_json(kp_dir / "timeline.json")
        if tl:
            beats = tl.get("beats", tl.get("timeline", []))
            audio = tl.get("audio_segments", tl.get("segments", []))
            tl["_beat_count"] = len(beats) if isinstance(beats, list) else tl.get("total_beats", 0)
            tl["_audio_count"] = len(audio) if isinstance(audio, list) else tl.get("total_audio_segments", 0)
        result["timeline"] = tl

        return result

    def _read_json(self, path: Path) -> dict | None:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None


# 全局单例
loader = ProjectLoader()
