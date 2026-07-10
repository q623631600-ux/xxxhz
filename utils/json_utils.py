"""
共享 JSON 工具 — 所有 service 统一使用
"""
import json
import re
from utils.logger import log


def extract_json(text: str, warn_on_repair: bool = True) -> dict:
    """
    从 LLM 回复中提取 JSON，支持：
    - 纯 JSON 字符串
    - markdown ```json 代码块
    - 被截断的 JSON（自动修复补全）
    """
    # 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 从 markdown 代码块提取
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # 匹配最外层 {}
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    # 截断修复
    result = repair_truncated_json(text)
    if result:
        if warn_on_repair:
            log.warn("JSON 被截断，已自动修复（内容可能不完整）")
        return result

    raise ValueError(f"无法解析 JSON。前 500 字符:\n{text[:500]}")


def repair_truncated_json(text: str) -> dict | None:
    """尝试修复被截断的 JSON"""
    # 先从 markdown 代码块提取
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

    # 检查是否在字符串中间被截断
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

    # 如果 items 列表被截断，直接闭合
    truncated += "]" * open_brackets
    truncated += "}" * open_braces

    try:
        return json.loads(truncated)
    except (json.JSONDecodeError, TypeError):
        pass

    # 最后手段：尝试只保留 content_units 数组
    arr_match = re.search(r'"content_units"\s*:\s*\[([\s\S]*?)(?:\]|\Z)', text)
    if arr_match:
        try:
            arr_text = arr_match.group(1)
            # 尝试修复并重建
            units = []
            # 用正则提取每个 {...} 对象
            obj_matches = re.finditer(r'\{[^{}]*\}', arr_text)
            for om in obj_matches:
                try:
                    units.append(json.loads(om.group()))
                except json.JSONDecodeError:
                    pass
            if units:
                return {"content_units": units, "total_units": len(units)}
        except Exception:
            pass

    return None


def safe_read_json(path) -> dict | None:
    """安全读取 JSON 文件，失败返回 None"""
    try:
        from pathlib import Path
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None
