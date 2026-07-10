"""
数据加载器 — 导入 Excel/CSV 数据到 VideoData

支持格式:
  .xlsx (Excel)
  .csv  (CSV, UTF-8/GBK自动检测)

字段映射（自动按列名匹配）:
  title / 标题 / 视频标题        → VideoData.title
  plays / 播放量 / 播放数        → VideoData.plays
  likes / 点赞量 / 点赞数        → VideoData.likes
  collects / 收藏量 / 收藏数      → VideoData.collects
  comments / 评论量 / 评论数      → VideoData.comments
  shares / 转发量 / 分享数        → VideoData.shares
  publish_time / 发布时间         → VideoData.publish_time
  cover / 封面描述                → VideoData.cover_desc
  content / 内容描述 / 脚本        → VideoData.content_desc
  duration / 时长 / 视频时长       → VideoData.duration
"""
from pathlib import Path
from typing import Optional

import pandas as pd

from utils.logger import log


COLUMN_MAP = {
    # 中文 → 标准字段
    "标题": "title",
    "视频标题": "title",
    "播放量": "plays",
    "播放数": "plays",
    "点赞量": "likes",
    "点赞数": "likes",
    "收藏量": "collects",
    "收藏数": "collects",
    "评论量": "comments",
    "评论数": "comments",
    "转发量": "shares",
    "转发数": "shares",
    "分享量": "shares",
    "分享数": "shares",
    "发布时间": "publish_time",
    "封面描述": "cover_desc",
    "封面": "cover_desc",
    "内容描述": "content_desc",
    "内容": "content_desc",
    "时长": "duration",
    "视频时长": "duration",
    # 英文 → 标准字段
    "title": "title",
    "plays": "plays",
    "views": "plays",
    "likes": "likes",
    "collects": "collects",
    "favorites": "collects",
    "comments": "comments",
    "shares": "shares",
    "publish_time": "publish_time",
    "publish_time ": "publish_time",
    "cover_desc": "cover_desc",
    "content_desc": "content_desc",
    "duration": "duration",
}

REQUIRED_FIELDS = ["title", "plays"]
OPTIONAL_FIELDS = ["likes", "collects", "comments", "shares",
                   "publish_time", "cover_desc", "content_desc", "duration"]


def load_video_data(file_path: str) -> list[dict]:
    """
    加载视频数据文件。

    Args:
        file_path: Excel 或 CSV 文件路径

    Returns:
        VideoData dict 列表

    Raises:
        ValueError: 格式不支持、缺少必要字段、文件不存在
        FileNotFoundError: 文件未找到
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    suffix = path.suffix.lower()

    if suffix == ".xlsx":
        df = _read_excel(path)
    elif suffix == ".csv":
        df = _read_csv(path)
    else:
        raise ValueError(f"不支持的文件格式: {suffix}（仅支持 .xlsx 和 .csv）")

    if df.empty:
        log.warn(f"文件为空: {file_path}")
        return []

    # 字段映射
    df = _map_columns(df)

    # 检查必要字段
    missing = [f for f in REQUIRED_FIELDS if f not in df.columns]
    if missing:
        raise ValueError(
            f"缺少必要字段: {missing}。\n"
            f"请确保数据包含以下列之一:\n"
            f"  标题/视频标题/title（必填）\n"
            f"  播放量/播放数/plays/views（必填）\n"
            f"  可选: 点赞量/评论量/收藏量/转发量/发布时间/时长/封面描述"
        )

    # 填充可选字段
    for field in OPTIONAL_FIELDS:
        if field not in df.columns:
            df[field] = ""

    # 数值字段转换为 int
    numeric_fields = ["plays", "likes", "collects", "comments", "shares"]
    for field in numeric_fields:
        if field in df.columns:
            df[field] = pd.to_numeric(df[field], errors="coerce").fillna(0).astype(int)

    # 重命名列名便于 Agent 处理
    df = df.rename(columns={
        "title": "title",
        "plays": "plays",
        "likes": "likes",
        "collects": "collects",
        "comments": "comments",
        "shares": "shares",
        "publish_time": "publish_time",
        "cover_desc": "cover_desc",
        "content_desc": "content_desc",
        "duration": "duration",
    })

    # 转为 dict 列表
    records = df.to_dict(orient="records")

    # 确保所有字段都存在
    cleaned = []
    for r in records:
        cleaned.append({
            "title": str(r.get("title", "")),
            "plays": int(r.get("plays", 0)),
            "likes": int(r.get("likes", 0)),
            "collects": int(r.get("collects", 0)),
            "comments": int(r.get("comments", 0)),
            "shares": int(r.get("shares", 0)),
            "publish_time": str(r.get("publish_time", "")),
            "cover_desc": str(r.get("cover_desc", "")),
            "content_desc": str(r.get("content_desc", "")),
            "duration": str(r.get("duration", "")),
        })

    log.info(f"  解析完成: {len(cleaned)} 行, {len(df.columns)} 列")
    return cleaned


def _read_excel(path: Path) -> pd.DataFrame:
    """读取 Excel 文件"""
    log.info(f"读取 Excel: {path.name}")
    try:
        df = pd.read_excel(path, dtype=str)
    except Exception as e:
        raise ValueError(f"Excel 读取失败: {e}") from e
    return df


def _read_csv(path: Path) -> pd.DataFrame:
    """读取 CSV 文件，自动检测编码"""
    log.info(f"读取 CSV: {path.name}")

    encodings = ["utf-8", "utf-8-sig", "gbk", "gb18030", "latin-1"]
    for enc in encodings:
        try:
            df = pd.read_csv(path, dtype=str, encoding=enc)
            log.info(f"  编码: {enc}")
            return df
        except (UnicodeDecodeError, UnicodeError):
            continue

    raise ValueError(f"无法解码 CSV 文件（尝试了 {encodings}）")


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """将中文/英文列名映射为标准字段名"""
    mapped = df.rename(columns=lambda c: COLUMN_MAP.get(c.strip(), c.strip()))
    # 去重：如果有多个列映射到同一标准字段，只保留第一个
    seen = set()
    keep = []
    for col in mapped.columns:
        if col not in seen:
            seen.add(col)
            keep.append(col)
        else:
            log.warn(f"  列 '{col}' 重复，仅保留第一次出现的列")
    return mapped[keep]
