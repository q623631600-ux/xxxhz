"""
字幕生成服务 — 从脚本 + 音频时间数据生成 SRT 字幕 + 标题叠加数据

输入: script.json + audio/timing.json + timeline.json
输出: subtitles.srt + title_overlays.json
"""
import json
import re
from pathlib import Path

from utils.logger import log


class SubtitleGenerator:
    """生成观众字幕和标题叠加数据"""

    # 字幕排版规则
    MAX_CHARS_PER_LINE = 20      # 每行最多中文字符
    MAX_LINES_PER_SUB = 1        # 每条字幕最多行数（单行模式）
    MAX_CHARS_PER_SUB = 20       # 每条字幕最多总字符
    MIN_DURATION_PER_SUB = 0.8   # 每条字幕最短显示时间(秒)

    def __init__(self):
        pass

    # ================================================================
    # 主入口
    # ================================================================

    def generate(self, kp_dir: Path) -> dict:
        """生成字幕和标题数据"""
        # 加载数据
        script = self._read_json(kp_dir / "script.json")
        if not script:
            script = self._read_json(kp_dir / "script_safe.json")
        if not script:
            script = self._read_json(kp_dir / "script_edited.json")
        if not script:
            raise FileNotFoundError("未找到脚本文件 (script.json / script_safe.json / script_edited.json)")

        timing = self._read_json(kp_dir / "audio" / "timing.json")
        if not timing:
            raise FileNotFoundError("未找到 audio/timing.json，请先生成配音")

        timeline_data = self._read_json(kp_dir / "timeline.json")

        full_script = script.get("full_script", "")
        if not full_script:
            raise ValueError("脚本中无 full_script 字段")

        # 1. 生成字幕 SRT
        srt_path = self._generate_srt(full_script, timing, kp_dir)

        # 2. 生成标题叠加数据
        title_path = None
        if timeline_data:
            title_path = self._generate_title_overlays(timeline_data, kp_dir)

        result = {
            "srt_path": str(srt_path),
            "subtitles_count": self._subtitle_count,
            "title_overlays_path": str(title_path) if title_path else None,
            "title_overlays_count": self._title_count if timeline_data else 0,
        }
        log.success(f"字幕生成完成: {self._subtitle_count} 条字幕, "
                     f"{result['title_overlays_count']} 个标题叠加")
        return result

    # ================================================================
    # SRT 字幕生成
    # ================================================================

    def _generate_srt(self, full_script: str, timing: list[dict], kp_dir: Path) -> Path:
        """生成 SRT 字幕文件

        使用 timing.json 中存储的精确文本段（与 TTS 生成的音频一一对应），
        确保字幕与配音完全同步。
        """
        # 解析 full_script 段落作为后备（当 timing.json 缺少完整 text 字段时使用）
        script_paragraphs = [p.strip() for p in full_script.split("\n\n") if p.strip()]

        # 计算每段音频的累计起始时间
        seg_start_times = []
        cum = 0.0
        for seg in timing:
            seg_start_times.append(cum)
            cum += seg.get("duration", 0)

        # 为每段生成字幕块
        all_subtitles = []  # [(start_sec, end_sec, text)]

        for i, seg in enumerate(timing):
            seg_start = seg_start_times[i]
            seg_duration = seg.get("duration", 5.0)
            seg_end = seg_start + seg_duration

            # 获取对应文本：优先 timing.json 完整 text → timing.json text_preview → full_script 段落
            seg_text = seg.get("text", "")
            if not seg_text:
                seg_text = seg.get("text_preview", "")
            # 如果 text 为空或只是截断的 text_preview（以 ... 结尾），尝试用 full_script 段落
            if (not seg_text or seg_text.endswith("...")) and i < len(script_paragraphs):
                seg_text = script_paragraphs[i]
            if not seg_text:
                continue

            # 将文本切分为字幕块
            subtitle_blocks = self._split_into_subtitle_blocks(seg_text)

            if not subtitle_blocks:
                continue

            # 按字数比例分配时间（与音频段对齐，字幕与配音同步）
            total_chars = sum(len(block) for block in subtitle_blocks)
            time_per_char = seg_duration / max(total_chars, 1)

            current_time = seg_start
            for j, block in enumerate(subtitle_blocks):
                block_chars = len(block)
                block_duration = max(block_chars * time_per_char, self.MIN_DURATION_PER_SUB)

                # 最后一条字幕填满剩余时间（确保覆盖整个音频段）
                if j == len(subtitle_blocks) - 1:
                    block_end = seg_end
                else:
                    block_end = current_time + block_duration

                # 确保不超出音频段结束时间
                block_end = min(block_end, seg_end)
                if block_end <= current_time:
                    block_end = current_time + self.MIN_DURATION_PER_SUB

                all_subtitles.append((current_time, block_end, block))
                current_time = block_end

        # 写入 SRT 文件
        self._subtitle_count = len(all_subtitles)
        srt_path = kp_dir / "subtitles.srt"
        srt_lines = []
        for idx, (start, end, text) in enumerate(all_subtitles, 1):
            srt_lines.append(str(idx))
            srt_lines.append(f"{self._fmt_srt_time(start)} --> {self._fmt_srt_time(end)}")
            srt_lines.append(text)
            srt_lines.append("")

        srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
        log.info(f"SRT 字幕已保存: {srt_path} ({self._subtitle_count} 条)")
        return srt_path

    def _split_into_subtitle_blocks(self, text: str) -> list[str]:
        """
        将一段文字切分为字幕块。
        规则：按标点切分短句，合并短句直到接近 MAX_CHARS_PER_SUB (36字)，
              每个短句作为一行，最多两行。
        """
        # 按中文标点切分为短句
        sentences = self._split_sentences(text)
        if not sentences:
            return [text] if text.strip() else []

        blocks = []
        current_block = []  # list of sentence strings
        current_len = 0

        for sent in sentences:
            sent_len = len(sent)

            # 如果当前块加上这个短句会超过限制，先保存当前块
            if current_block and current_len + sent_len > self.MAX_CHARS_PER_SUB:
                blocks.append("\n".join(current_block))
                current_block = []
                current_len = 0

            # 如果单个短句超过限制，需要再切分
            if sent_len > self.MAX_CHARS_PER_SUB:
                # 先保存当前块
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []
                    current_len = 0
                # 长句按字符数强制拆分
                for k in range(0, sent_len, self.MAX_CHARS_PER_LINE):
                    chunk = sent[k:k + self.MAX_CHARS_PER_LINE]
                    blocks.append(chunk)
                continue

            # 如果当前块已有2行，保存并开始新块
            if len(current_block) >= self.MAX_LINES_PER_SUB:
                blocks.append("\n".join(current_block))
                current_block = []
                current_len = 0

            current_block.append(sent)
            current_len += sent_len

        # 保存最后一块
        if current_block:
            blocks.append("\n".join(current_block))

        return blocks if blocks else [text.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        """按中文标点切分短句，保留标点在短句末尾"""
        # 使用正则在标点后切分，同时保留标点
        pattern = r'([^。，！？；：\n]+[。，！？；：\n]?)'
        matches = re.findall(pattern, text)

        # 合并过短的片段
        result = []
        buf = ""
        for m in matches:
            m = m.strip()
            if not m:
                continue
            if buf and len(buf) + len(m) < 8:  # 太短就合并
                buf += m
            else:
                if buf:
                    result.append(buf)
                buf = m
        if buf:
            result.append(buf)

        # 如果没有匹配到，返回原文本
        return result if result else [text.strip()]

    # ================================================================
    # 标题叠加数据生成
    # ================================================================

    def _generate_title_overlays(self, timeline_data: dict, kp_dir: Path) -> Path:
        """从 timeline.json 生成标题叠加数据"""
        timeline = timeline_data.get("timeline", [])
        if not timeline:
            log.warn("timeline.json 中无 timeline 数据")
            return None

        overlays = []
        for beat in timeline:
            msg = beat.get("core_message", "").strip()
            if not msg:
                continue

            # 截断过长的标题
            if len(msg) > 40:
                # 保留前40个字符，在最后一个完整词处截断
                msg = msg[:40] + "..."

            overlays.append({
                "start_seconds": beat.get("start_seconds", 0),
                "end_seconds": beat.get("end_seconds", 0),
                "text": msg,
            })

        self._title_count = len(overlays)
        title_path = kp_dir / "title_overlays.json"
        title_path.write_text(
            json.dumps({"overlays": overlays, "count": len(overlays)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(f"标题叠加数据已保存: {title_path} ({self._title_count} 条)")
        return title_path

    # ================================================================
    # 工具方法
    # ================================================================

    def _read_json(self, path: Path) -> dict | None:
        """安全读取 JSON"""
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _fmt_srt_time(self, seconds: float) -> str:
        """秒 → SRT 时间格式 HH:MM:SS,mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
