#!/usr/bin/env python3
"""
视觉工作流 — 三层模型一键执行

用法:
  python visual_workflow.py --book "毛选" --kp-id 7
  python visual_workflow.py --book "毛选" --kp-id 7 --layer 1   # 只跑第1层

流程:
  1. ContentUnitSegmenter  → content_units.json
  2. VisualBeatExtractor    → visual_beats.json
  3. ImagePromptGenerator   → image_prompts.json
"""
import argparse
import json
import sys
from pathlib import Path

from config import OUTPUT_DIR
from utils.logger import log
from services.content_unit_segmenter import ContentUnitSegmenter
from services.visual_beat_extractor import VisualBeatExtractor
from services.image_prompt_generator import ImagePromptGenerator


def find_kp_dir(book_name: str, kp_id: int) -> Path | None:
    """查找知识点目录"""
    safe = "".join(c for c in book_name if c.isalnum() or c in " _-()（）").strip()
    book_dir = OUTPUT_DIR / safe
    if not book_dir.exists():
        return None
    prefix = f"kp_{kp_id:03d}"
    matches = sorted(book_dir.glob(f"{prefix}*"))
    return matches[0] if matches else None


def main():
    parser = argparse.ArgumentParser(description="视觉工作流 — 长脚本 → 画面提示词")
    parser.add_argument("--book", "-b", type=str, required=True, help="书名")
    parser.add_argument("--kp-id", type=int, required=True, help="知识点 ID")
    parser.add_argument("--dir", type=str, default="",
                        help="直接指定知识点目录路径（跳过自动查找）")
    parser.add_argument("--layer", type=int, choices=[1, 2, 3], default=0,
                        help="只运行指定层: 1=切分, 2=画面提取, 3=提示词, 0=全部")
    args = parser.parse_args()

    # ---- 查找目录 ----
    if args.dir:
        kp_dir = Path(args.dir)
    else:
        kp_dir = find_kp_dir(args.book, args.kp_id)

    if not kp_dir or not kp_dir.exists():
        log.error(f"未找到知识点目录。请先生成脚本。")
        log.info(f"  python main.py --book \"{args.book}\" --kp-id {args.kp_id} --script-only")
        sys.exit(1)

    log.title(f"视觉工作流 — 《{args.book}》KP #{args.kp_id}")
    print(f"  目录: {kp_dir}")

    results = {}

    # ---- 第 1 层 ----
    if args.layer in (0, 1):
        log.title("[第 1 层] 内容单元切分")
        try:
            seg = ContentUnitSegmenter()
            path = seg.run(kp_dir)
            data = json.loads(path.read_text(encoding='utf-8'))
            results['units'] = data
            print(f"  输出: {path.name}")
            print(f"  切分原则: {data.get('segmentation_principle', '')[:60]}...")
            print(f"  内容单元: {data.get('total_units', '?')} 个")
        except Exception as e:
            log.error(f"失败: {e}")
            sys.exit(1)

    # ---- 第 2 层 ----
    if args.layer in (0, 2):
        log.title("[第 2 层] 画面提取")
        try:
            ext = VisualBeatExtractor()
            path = ext.run(kp_dir)
            data = json.loads(path.read_text(encoding='utf-8'))
            results['beats'] = data
            print(f"  输出: {path.name}")
            print(f"  提取原则: {data.get('visual_extraction_principle', '')[:60]}...")
            print(f"  画面节点: {data.get('total_visual_beats', '?')} 个")
        except Exception as e:
            log.error(f"失败: {e}")
            sys.exit(1)

    # ---- 第 3 层 ----
    if args.layer in (0, 3):
        log.title("[第 3 层] 图片提示词生成")
        try:
            gen = ImagePromptGenerator()
            path = gen.run(kp_dir)
            data = json.loads(path.read_text(encoding='utf-8'))
            results['prompts'] = data
            total = data.get("total_prompts", "?")
            print(f"  输出: {path.name}")
            print(f"  图片提示词: {total} 个")
            print(f"  状态: 全部 waiting_api（未接图片 API）")
        except Exception as e:
            log.error(f"失败: {e}")
            sys.exit(1)

    # ---- 汇总 ----
    log.title("三层完成")
    print(f"  content_units.json  → {kp_dir / 'content_units.json'}")
    print(f"  visual_beats.json   → {kp_dir / 'visual_beats.json'}")
    print(f"  image_prompts.json  → {kp_dir / 'image_prompts.json'}")
    if 'units' in results:
        print(f"  内容单元: {results['units'].get('total_units', '?')} 个")
    if 'beats' in results:
        print(f"  画面节点: {results['beats'].get('total_visual_beats', '?')} 个")
    if 'prompts' in results:
        print(f"  图片提示词: {results['prompts'].get('total_prompts', '?')} 个（全部 waiting_api）")
    print(f"\n  下一步: 这三个 JSON 可用于可视化界面，或接图片 API 后替换 image_status")


if __name__ == "__main__":
    main()
