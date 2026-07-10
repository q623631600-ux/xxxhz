"""
时间线组装 — 图片按口播内容对应音频位置
输入 visual_beats.json + content_units.json + audio/timing.json → timeline.json
"""
import json
from pathlib import Path
from utils.logger import log


class TimelineAssembler:

    def load_data(self, kp_dir: Path) -> dict:
        data = {}
        for name in ["visual_beats.json", "content_units.json", "image_prompts.json"]:
            path = kp_dir / name
            if path.exists():
                data[name] = json.loads(path.read_text(encoding="utf-8"))
        tp = kp_dir / "audio" / "timing.json"
        if tp.exists():
            data["timing"] = json.loads(tp.read_text(encoding="utf-8"))
        return data

    def assemble(self, kp_dir: Path) -> dict:
        data = self.load_data(kp_dir)
        vb = data.get("visual_beats.json", {})
        cu = data.get("content_units.json", {})
        ip = data.get("image_prompts.json", {})
        timing = data.get("timing", [])

        if not vb: raise FileNotFoundError("未找到 visual_beats.json")
        if not timing: raise FileNotFoundError("未找到 audio/timing.json")

        beats = vb.get("visual_beats", [])
        units = cu.get("content_units", [])

        # prompt 映射
        beat_prompts = {i["beat_id"]: i.get("image_prompt", "") for i in ip.get("items", [])}

        total_audio = sum(seg["duration"] for seg in timing)

        # === 构建 unit → text 映射 ===
        unit_text = {}
        for u in units:
            unit_text[u.get("unit_id", 0)] = u.get("text", "")

        # === 每个 unit 的文本长度 ===
        total_chars = sum(len(t) for t in unit_text.values())
        if total_chars == 0:
            total_chars = len(units)

        # === 按文本长度比例分配每个 unit 的时间，单张图片最长 20 秒 ===
        MAX_UNIT_DURATION = 20.0
        unit_start = {}
        unit_end = {}
        cursor = 0.0

        # 先按比例算原始时长
        raw_durations = []
        for u in units:
            uid = u.get("unit_id", 0)
            chars = len(unit_text.get(uid, ""))
            dur = total_audio * chars / total_chars if total_chars > 0 else 0
            if dur < 0.5:
                dur = 0.5
            raw_durations.append(dur)

        # 超过 20 秒的截断，将多出的时间匀给未超的
        over_sum = sum(d - MAX_UNIT_DURATION for d in raw_durations if d > MAX_UNIT_DURATION)
        under_count = sum(1 for d in raw_durations if d <= MAX_UNIT_DURATION)

        if over_sum > 0 and under_count > 0:
            extra_per_under = over_sum / under_count
            final_durations = []
            for d in raw_durations:
                if d > MAX_UNIT_DURATION:
                    final_durations.append(MAX_UNIT_DURATION)
                else:
                    final_durations.append(min(d + extra_per_under, MAX_UNIT_DURATION))
        elif over_sum > 0 and under_count == 0:
            # 全超了，全部压到 20 秒
            final_durations = [MAX_UNIT_DURATION] * len(raw_durations)
        else:
            final_durations = raw_durations

        for i, u in enumerate(units):
            uid = u.get("unit_id", 0)
            dur = final_durations[i]
            unit_start[uid] = round(cursor, 1)
            unit_end[uid] = round(cursor + dur, 1)
            cursor += dur

        # 缩放对齐到总音频时长（消除截断/补充分配的偏差）
        if cursor > 0 and abs(cursor - total_audio) > 1.0:
            scale = total_audio / cursor
            cursor = 0.0
            for u in units:
                uid = u.get("unit_id", 0)
                dur = unit_end.get(uid, 0) - unit_start.get(uid, 0)
                adjusted = dur * scale
                unit_start[uid] = round(cursor, 1)
                unit_end[uid] = round(cursor + adjusted, 1)
                cursor += adjusted
            # 最后一个对齐结尾
            if units:
                last_uid = units[-1]["unit_id"]
                unit_end[last_uid] = round(total_audio, 1)


        log.info(f"时间线: {len(beats)}画面 × {len(units)}单元, {self._fmt(total_audio)}")

        # === 每个 beat 的开始 = 第一个覆盖 unit 的开始，结束 = 最后一个覆盖 unit 的结束 ===
        timeline = []
        for beat in beats:
            bid = beat["beat_id"]
            uids = beat.get("unit_ids", [])
            if not uids:
                uid = beat.get("unit_id")
                uids = [uid] if uid else []

            if uids:
                start = unit_start.get(uids[0], 0)
                end = unit_end.get(uids[-1], start + 1)
            else:
                start = 0
                end = 1

            covered = ""
            for uid in uids:
                covered += unit_text.get(uid, "") + " | "

            timeline.append({
                "beat": bid,
                "unit_ids": uids,
                "audio_segs": [1],  # 不再用音频段分组
                "start_seconds": round(start, 1),
                "end_seconds": round(end, 1),
                "duration_seconds": round(end - start, 1),
                "visual_type": beat.get("visual_type", ""),
                "core_message": beat.get("core_message", ""),
                "covered_text_preview": covered[:80],
                "image_prompt": beat_prompts.get(bid, "")[:120],
            })

        result = {
            "total_beats": len(beats),
            "total_audio_segments": len(timing),
            "total_duration_seconds": round(total_audio, 1),
            "total_duration": self._fmt(total_audio),
            "alignment_method": "按内容单元权重比例分配，首尾相连不重叠",
            "total_audio_actual": round(total_audio, 1),
            "timeline": timeline,
        }
        log.success(f"时间线: {len(timeline)}片段, {self._fmt(total_audio)}")
        return result

    def save(self, data: dict, kp_dir: Path):
        path = kp_dir / "timeline.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"时间线已保存: {path}")
        return path

    def run(self, kp_dir: Path) -> Path:
        return self.save(self.assemble(kp_dir), kp_dir)

    def _fmt(self, s: float) -> str:
        return f"{int(s//60)}分{int(s%60)}秒"
