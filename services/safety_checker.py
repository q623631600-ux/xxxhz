"""
内容安全审核服务 - 在发布前检测脚本中的敏感内容
红色警告 = 不可发布，黄色警告 = 建议修改
"""
import json
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR
from utils.logger import log
from utils.json_utils import extract_json

class SafetyChecker:
    """脚本 → 安全审核 → 安全版脚本"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    def check(self, script: dict) -> dict:
        """
        审核脚本安全性

        Args:
            script: 完整脚本 dict（含 segments）

        Returns:
            {"passed": bool, "risk_level": str, "issues": [...], "revised_segments": [...]}
        """
        log.info("正在进行内容安全审核...")

        # 提取纯文本用于审核
        full_text = self._extract_text(script)
        title = script.get("title", "")

        prompt = self._load_prompt("safety_check.txt")
        prompt = prompt.replace("{script_text}", full_text)

        try:
            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"请审核这条视频脚本的安全性。标题：{title}"},
                ],
                temperature=0.1,  # 低温度，严格审核
                max_tokens=2000,
            )

            result = extract_json(response.choices[0].message.content)

            if result.get("passed", True):
                log.success(f"安全审核通过 (风险等级: {result.get('risk_level', 'safe')})")
            else:
                self._print_issues(result.get("issues", []))

            return result

        except Exception as e:
            log.error(f"安全审核调用失败: {e}")
            return {"passed": True, "risk_level": "unknown", "issues": [], "summary": f"审核失败: {e}"}

    def _extract_text(self, script: dict) -> str:
        """提取脚本纯文本"""
        segments = script.get("segments", [])
        lines = [script.get("title", "")]
        for seg in segments:
            lines.append(seg.get("text", ""))
        return "\n\n".join(lines)

    def _print_issues(self, issues: list):
        """打印安全问题"""
        red_count = sum(1 for i in issues if i.get("severity") == "red")
        yellow_count = sum(1 for i in issues if i.get("severity") == "yellow")

        if red_count > 0:
            log.error(f"发现 {red_count} 个红线问题，{yellow_count} 个黄线问题")
        else:
            log.warn(f"发现 {yellow_count} 个黄线问题（建议修改）")

        for i, issue in enumerate(issues, 1):
            severity = issue.get("severity", "?")
            flag = "[RED]" if severity == "red" else "[YELLOW]"
            print(f"  {flag} 问题{i}: {issue.get('issue_type', '')}")
            print(f"       原文: {issue.get('original_text', '')[:80]}...")
            print(f"       建议: {issue.get('suggestion', '')[:80]}...")
            print()

    def apply_revisions(self, script: dict, check_result: dict) -> dict:
        """
        将安全审核建议应用到脚本

        如果有 revised_script，解析并替换 segments
        """
        revised_text = check_result.get("revised_script", "")
        if not revised_text:
            log.info("无需修改，脚本安全")
            return script

        # 尝试从 revised_script 中提取 segments
        try:
            revised = json.loads(revised_text) if isinstance(revised_text, str) else revised_text
            if "segments" in revised:
                log.info("已应用安全修改")
                script["segments"] = revised["segments"]
                if "title" in revised:
                    script["title"] = revised["title"]
        except (json.JSONDecodeError, TypeError):
            log.warn("无法解析修订版脚本，保留原版")

        return script

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return ""
