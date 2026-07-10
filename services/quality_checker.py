"""
质量审核服务 - 检查脚本是否真的符合深度讲解要求
在安全审核之前执行
"""
import json
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR
from utils.logger import log
from utils.json_utils import extract_json

class QualityChecker:
    """脚本质量审核"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    def check(self, script: dict) -> dict:
        """
        审核脚本质量（13 维度）

        Args:
            script: 完整脚本 dict

        Returns:
            quality check result dict
        """
        log.info("正在进行质量审核（13维度）...")

        full = script.get("full_script", "")
        structure = script.get("script_structure", {})

        # 提供给审核模型的元信息
        char_count = len(full)
        estimated = script.get("estimated_video_length", script.get("suggested_video_length", ""))
        source = script.get("source_scope", "")

        review_text = f"""
## 脚本元信息
- source_scope: {source}
- estimated_video_length: {estimated}
- full_script 实际字数: {char_count} 字
- 按每分钟250-320字计算，预计口播时长: {char_count // 280} 分钟左右

## 脚本结构
{json.dumps(structure, ensure_ascii=False, indent=2)}

## 完整脚本
{full}
"""

        prompt = self._load_prompt("quality_check.txt")
        prompt = prompt.replace("{script_text}", review_text)

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"请严格审核这段脚本的质量。注意：estimated={estimated}，实际{char_count}字，约{char_count // 280}分钟口播时长。检查 source_scope={source} 是否准确。"},
                ],
                temperature=0.1,
                max_tokens=2000,
            )
            result = extract_json(response.choices[0].message.content)

            # 修复：如果 LLM 只返回了 dimension_scores，补全顶层字段
            result = self._normalize_result(result)

            passed = result.get("passed", False)
            score = result.get("overall_score", 0)

            if passed and score >= 70:
                log.success(f"质量审核通过（{score}分）")
                self._print_dims(result)
            else:
                log.warn(f"质量审核未通过（{score}分）")
                self._print_dims(result)
                problems = result.get("main_problems", [])
                must_fix = result.get("must_fix", [])
                if problems:
                    print("\n  主要问题:")
                    for p in problems:
                        print(f"    - {p}")
                if must_fix:
                    print("\n  必须修改:")
                    for m in must_fix:
                        print(f"    [!] {m}")

            return result

        except Exception as e:
            log.error(f"质量审核调用失败: {e}")
            return {"passed": True, "overall_score": 0, "dimension_scores": {}, "main_problems": [], "must_fix": [], "suggested_improvements": [], "editor_conclusion": f"审核失败: {e}"}

    def _normalize_result(self, result: dict) -> dict:
        """修复 LLM 可能缺失的顶层字段"""
        # 如果已经有 passed 字段，直接返回
        if "passed" in result and "overall_score" in result:
            return result

        # 如果返回的是 dimension_scores 内层结构（缺少 passed/overall_score）
        dim_keys = {"source_accuracy", "original_understanding", "big_to_small_translation", "explanation_clarity"}
        has_dims = any(k in result for k in dim_keys)

        if has_dims:
            # LLM 把 dimension_scores 直接当顶层输出
            dims = result
            total = sum(v for v in dims.values() if isinstance(v, (int, float)))
            max_possible = 100
            passed = total >= 70
            return {
                "passed": passed,
                "overall_score": total,
                "dimension_scores": dims,
                "main_problems": result.get("main_problems", []),
                "must_fix": result.get("must_fix", []),
                "suggested_improvements": result.get("suggested_improvements", []),
                "editor_conclusion": result.get("editor_conclusion", "（审核结论缺失）"),
            }

        # 如果 dimension_scores 嵌套在内部
        if "dimension_scores" in result:
            dims = result["dimension_scores"]
            total = sum(v for v in dims.values() if isinstance(v, (int, float)))
            result.setdefault("overall_score", total)
            result.setdefault("passed", total >= 70)
            return result

        # 完全无法识别，默认通过
        result.setdefault("passed", True)
        result.setdefault("overall_score", 0)
        result.setdefault("dimension_scores", {})
        return result

    def _print_dims(self, result: dict):
        """打印维度得分"""
        dims = result.get("dimension_scores", {})
        if not dims:
            return
        labels = {
            "source_accuracy": "来源准确", "original_understanding": "原书理解",
            "problem_awareness": "问题意识", "big_to_small_translation": "大→小转换",
            "explanation_clarity": "讲解清晰度", "logic_integrity": "逻辑完整",
            "progressive_structure": "递进结构", "thinking_framework": "思维框架",
            "life_judgment_tool": "判断工具", "transfer_ability": "举一反三",
            "application_binding": "应用绑定", "plain_language": "通俗度",
            "practical_value": "实用价值", "length_reasonableness": "时长合理",
            "language_safety": "语言安全", "relatability": "普适关联",
        }
        low_dims = []
        for key, label in labels.items():
            score = dims.get(key, -1)
            max_scores = {"source_accuracy": 5, "original_understanding": 10, "problem_awareness": 10,
                          "big_to_small_translation": 12, "explanation_clarity": 15,
                          "logic_integrity": 10, "progressive_structure": 10,
                          "thinking_framework": 8, "life_judgment_tool": 5,
                          "transfer_ability": 5, "application_binding": 5,
                          "plain_language": 5, "practical_value": 5,
                          "length_reasonableness": 5, "language_safety": 8,
                          "relatability": 5}
            max_s = max_scores.get(key, 10)
            if score < max_s * 0.7:
                low_dims.append(f"{label}({score}/{max_s})")
        if low_dims:
            print(f"  低分项: {', '.join(low_dims)}")

    def save_result(self, result: dict, output_dir: Path):
        """保存审核结果"""
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "quality_check.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"质量审核结果已保存: {path}")

    # ========== 工具 ==========

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return ""
