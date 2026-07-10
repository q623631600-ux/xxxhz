"""独立生成封面钩子预览图 — 16:9 纯黑背景，参考 new_hook_preview.png"""
import json, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ============================================================
# 配置：16:9
# ============================================================
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
FONT_PATHS = [
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]

def load_font(size):
    for fp in FONT_PATHS:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()

def split_hook_lines(text):
    """第1句(格式A/B)全黄色独占首行，后续文字白色填充1-2行"""
    # 按句末标点拆句子
    sentences = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in "。！？":
            sentences.append(buf)
            buf = ""
    if buf:
        sentences.append(buf)

    if not sentences:
        return [text], {0: [(0, len(text), True)]}

    first_sentence = sentences[0]
    rest_text = "".join(sentences[1:])

    # 第1句独占首行（黄色）
    if not rest_text:
        # 短句不拆分，长句对半拆
        if len(first_sentence) <= 25:
            return [first_sentence], {0: [(0, len(first_sentence), True)]}
        mid = len(first_sentence) // 2
        return [first_sentence[:mid], first_sentence[mid:]], {0: [(0, mid, True)], 1: [(0, len(first_sentence)-mid, True)]}

    lines = [first_sentence]  # 第1行=全黄

    # 剩余文字分1-2行（白色）
    if len(rest_text) <= 50:
        lines.append(rest_text)
    else:
        parts = []
        buf = ""
        for ch in rest_text:
            buf += ch
            if ch in "。！？；，":
                parts.append(buf)
                buf = ""
        if buf:
            parts.append(buf)

        target = len(rest_text) / 2
        line2 = ""
        line2_len = 0
        remaining = []
        for p in parts:
            if not line2 or line2_len + len(p) <= target * 1.25:
                line2 += p
                line2_len += len(p)
            else:
                remaining.append(p)
        line3 = "".join(remaining)

        if line2:
            lines.append(line2)
        if line3:
            lines.append(line3)

    # 标记黄色：仅第1行全黄
    yellow_spans = {0: [(0, len(first_sentence), True)]}
    for li in range(1, len(lines)):
        yellow_spans[li] = []

    return lines, yellow_spans

def draw_mixed_line(draw, line, yellow_spans, font, font_size, y, img_w):
    """绘制一行，支持行内白+黄混色"""
    if not yellow_spans:
        tw = draw.textbbox((0, 0), line, font=font)[2]
        x = (img_w - tw) // 2
        draw.text((x + 3, y + 3), line, fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), line, fill=(255, 255, 255, 255), font=font)
        return

    total_w = draw.textbbox((0, 0), line, font=font)[2]
    start_x = (img_w - total_w) // 2

    spans = sorted(yellow_spans, key=lambda s: s[0])
    segments = []
    pos = 0
    for s_start, s_end, _ in spans:
        if pos < s_start:
            segments.append((line[pos:s_start], False))
        segments.append((line[s_start:s_end], True))
        pos = s_end
    if pos < len(line):
        segments.append((line[pos:], False))

    x = start_x
    for seg_text, is_yellow in segments:
        if not seg_text:
            continue
        color = (255, 215, 0, 255) if is_yellow else (255, 255, 255, 255)
        draw.text((x + 3, y + 3), seg_text, fill=(0, 0, 0, 200), font=font)
        draw.text((x, y), seg_text, fill=color, font=font)
        x += draw.textbbox((0, 0), seg_text, font=font)[2]

def get_en_lines(script):
    """英文：知识点标题，黄色"""
    kp = script.get("knowledge_point", "")
    if not kp:
        return []
    return [kp]

def create_hook_overlay(kp_dir: Path, output_path: Path):
    """生成16:9纯黑封面"""
    script = None
    for name in ["script_edited.json", "script_safe.json", "script.json"]:
        sp = kp_dir / name
        if sp.exists():
            script = json.loads(sp.read_text(encoding="utf-8"))
            break
    if not script:
        print("错误: 未找到脚本")
        return None

    full_script = script.get("full_script", "")
    if not full_script:
        print("错误: 脚本为空")
        return None

    first_para = full_script.split("\n\n")[0].strip()
    if not first_para:
        print("错误: 钩子段落为空")
        return None

    print(f"钩子原文 ({len(first_para)}字):")
    print(f"  {first_para[:200]}...")

    img_w, img_h = VIDEO_WIDTH, VIDEO_HEIGHT
    overlay = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 255))
    draw = ImageDraw.Draw(overlay)

    # 拆分中文行 + 黄色标记
    cn_lines, yellow_spans = split_hook_lines(first_para)

    # 字号：自动选最大且不超出画面的
    margin_x = 120
    max_text_w = img_w - 2 * margin_x
    cn_sizes = [88, 72, 60, 48, 40, 36]
    cn_size = cn_sizes[0]
    cn_font = None
    for sz in cn_sizes:
        font = load_font(sz)
        max_line_w = max((draw.textbbox((0, 0), line, font=font)[2] for line in cn_lines), default=0)
        if max_line_w <= max_text_w:
            cn_size = sz
            cn_font = font
            break
    if cn_font is None:
        cn_font = load_font(36)
        cn_size = 36
    en_size = max(24, cn_size * 2 // 5)
    en_font = load_font(en_size)

    # 中文块
    cn_line_h = draw.textbbox((0, 0), "Ag", font=cn_font)[3] - draw.textbbox((0, 0), "Ag", font=cn_font)[1]
    cn_gap = int(cn_size * 0.35)
    cn_block_h = len(cn_lines) * cn_line_h + (len(cn_lines) - 1) * cn_gap

    # 英文块
    en_line_h = draw.textbbox((0, 0), "Ag", font=en_font)[3] - draw.textbbox((0, 0), "Ag", font=en_font)[1]
    en_gap = int(en_size * 0.35)
    en_lines = get_en_lines(script)
    en_block_h = len(en_lines) * en_line_h + (len(en_lines) - 1) * en_gap if en_lines else 0

    cn_en_gap = 80 if en_lines else 0
    total_h = cn_block_h + cn_en_gap + en_block_h
    start_y = (img_h - total_h) // 2

    # 绘制中文
    y = start_y
    for li, line in enumerate(cn_lines):
        spans = yellow_spans.get(li, [])
        draw_mixed_line(draw, line, spans, cn_font, cn_size, y, img_w)
        y += cn_line_h + cn_gap

    # 绘制英文
    if en_lines:
        y += cn_en_gap - cn_gap
        for li, line in enumerate(en_lines):
            color = (255, 215, 0, 255) if li == 0 else (255, 255, 255, 255)
            tw = draw.textbbox((0, 0), line, font=en_font)[2]
            x = (img_w - tw) // 2
            draw.text((x + 2, y + 2), line, fill=(0, 0, 0, 180), font=en_font)
            draw.text((x, y), line, fill=color, font=en_font)
            y += en_line_h + en_gap

    overlay.save(str(output_path), "PNG")
    print(f"\n封面已生成: {output_path}")
    print(f"画布: {img_w}x{img_h} (16:9)")
    print(f"中文: {len(cn_lines)}行, 字号={cn_size}px")
    print(f"英文: {len(en_lines)}行, 字号={en_size}px")
    print(f"黄色=第1句全文高亮, 白色=后续文字")
    for li, line in enumerate(cn_lines):
        spans = yellow_spans.get(li, [])
        yellow_texts = [line[s:e] for s, e, _ in spans]
        rest = line
        for s, e, _ in reversed(spans):
            rest = rest[:s] + "…" + rest[e:]
        print(f"  行{li+1}: 黄色={yellow_texts}")
    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python _gen_cover_preview.py <kp_dir> [output_path]")
        kp_dir = Path("D:/讲书工作流/output/富爸爸穷爸爸/kp_001_穷爸爸 vs 富爸爸两种金钱观如何决定你的人生")
        output = Path("D:/讲书工作流/output/_preview/cover_preview.png")
    else:
        kp_dir = Path(sys.argv[1])
        output = Path(sys.argv[2]) if len(sys.argv) > 2 else kp_dir / "cover_preview.png"

    create_hook_overlay(kp_dir, output)
