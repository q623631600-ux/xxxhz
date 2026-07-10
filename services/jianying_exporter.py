"""
剪映导出 — 将 timeline.json 转为剪映可用的 SRT 字幕 + 图片对照表
"""
import json
from pathlib import Path
from utils.logger import log


class JianyingExporter:
    """时间线 → 剪映可导入格式"""

    def export_srt(self, kp_dir: Path) -> Path:
        """
        生成 SRT 文件，每条"字幕"标注画面切换点
        导入剪映后作为字幕轨道，用来定位每个画面点的起始时间
        """
        tl_path = kp_dir / "timeline.json"
        if not tl_path.exists():
            raise FileNotFoundError("未找到 timeline.json，请先运行时间线组装")

        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        timeline = tl.get("timeline", [])

        # 计算累计起始时间
        srt_lines = []
        seq = 1
        cumulative = 0.0  # 当前累计秒数

        for beat in timeline:
            start = cumulative
            end = cumulative + beat["duration_seconds"]
            cumulative = end

            bid = beat["beat"]
            vtype = beat.get("visual_type", "")
            msg = beat.get("core_message", "")

            text = f"[Beat {bid}] {vtype} | {msg[:60]} | 图片占位 → images/beat_{bid:02d}.png"

            srt_lines.append(str(seq))
            srt_lines.append(f"{self._fmt_time(start)} --> {self._fmt_time(end)}")
            srt_lines.append(text)
            srt_lines.append("")
            seq += 1

        srt_path = kp_dir / "jianying_timeline.srt"
        srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
        log.success(f"剪映 SRT 已导出: {srt_path} ({len(timeline)} 条)")
        return srt_path

    def export_image_guide(self, kp_dir: Path) -> Path:
        """生成图片位置对照表"""
        tl_path = kp_dir / "timeline.json"
        if not tl_path.exists():
            raise FileNotFoundError("未找到 timeline.json")

        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        timeline = tl.get("timeline", [])

        images_dir = kp_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        lines = ["# 剪映图片对照表", f"# 总时长: {tl.get('total_duration', '?')}", ""]

        cumulative = 0.0
        for beat in timeline:
            start = cumulative
            end = cumulative + beat["duration_seconds"]
            cumulative = end

            bid = beat["beat"]
            vtype = beat.get("visual_type", "")
            msg = beat.get("core_message", "")

            placeholder = images_dir / f"beat_{bid:02d}_placeholder.txt"
            if not placeholder.exists():
                placeholder.write_text(
                    f"Beat {bid} | {vtype}\n"
                    f"显示: {self._fmt_time(start)} → {self._fmt_time(end)} ({beat['duration_seconds']}秒)\n"
                    f"内容: {msg}\n"
                    f"图片路径: images/beat_{bid:02d}.png\n",
                    encoding="utf-8")

            lines.append(
                f"{self._fmt_time(start)} → {self._fmt_time(end)}  "
                f"Beat {bid} [{vtype}] {msg[:60]}"
            )

        guide_path = kp_dir / "jianying_image_guide.txt"
        guide_path.write_text("\n".join(lines), encoding="utf-8")
        log.success(f"图片对照表已导出: {guide_path}")
        return guide_path

    def run(self, kp_dir: Path) -> dict:
        """一键导出"""
        srt = self.export_srt(kp_dir)
        guide = self.export_image_guide(kp_dir)
        return {"srt": str(srt), "image_guide": str(guide)}

    def _fmt_time(self, seconds: float) -> str:
        """秒 → SRT 时间格式 HH:MM:SS,mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
