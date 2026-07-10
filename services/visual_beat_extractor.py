"""
第 2 层：画面提取模型
输入 content_units.json → 输出 visual_beats.json
"""
import json
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR
from utils.logger import log
from utils.json_utils import extract_json

class VisualBeatExtractor:
    """内容单元 → 画面节点（分批处理，避免截断）"""

    BATCH_SIZE = 10  # 每批处理的 content unit 数（小批次避免输出截断）

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    # ========== 公共接口 ==========

    def load_content_units(self, kp_dir: Path) -> dict:
        """加载 content_units.json"""
        path = kp_dir / "content_units.json"
        if not path.exists():
            raise FileNotFoundError(f"未找到 content_units.json: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def extract(self, content_units_data: dict) -> dict:
        """基于内容单元提取画面节点（分批处理），合并相邻单元控制图片总量 50-60 张"""
        units = content_units_data.get("content_units", [])
        total = len(units)

        # 合并相邻单元，不超过 65 张
        if total > 65:
            # 超过80张才合并：每2个单元合并为1组，目标 ~40-55 张
            TARGET = 55
            groups_two = total - TARGET  # 2个一组的组数
            groups_one = TARGET * 2 - total  # 1个一组的组数
            merged_units = []
            idx = 0
            for _ in range(groups_two):
                if idx + 1 < total:
                    group = units[idx:idx + 2]
                    merged_units.append({
                        "unit_id": group[0]["unit_id"],
                        "text": " ".join(u.get("text", "") for u in group)[:800],
                        "estimated_reading_seconds": sum(u.get("estimated_reading_seconds", 5) for u in group),
                        "_unit_ids": [u["unit_id"] for u in group],
                        "_count": len(group),
                    })
                    idx += 2
            for _ in range(groups_one):
                if idx < total:
                    u = units[idx]
                    merged_units.append({
                        "unit_id": u.get("unit_id", 0),
                        "text": u.get("text", "")[:800],
                        "estimated_reading_seconds": u.get("estimated_reading_seconds", 5),
                        "_unit_ids": [u.get("unit_id", 0)],
                        "_count": 1,
                    })
                    idx += 1
            log.info(f"内容单元较多({total})，合并为 {len(merged_units)} 组")
            units = merged_units
            total = len(units)

        log.info(f"正在提取画面节点（{total} 个内容单元，每批 {self.BATCH_SIZE} 个）...")

        prompt = self._load_prompt("visual_beat_extractor.txt")
        all_beats = []
        batch_num = 1

        for start in range(0, total, self.BATCH_SIZE):
            batch = units[start:start + self.BATCH_SIZE]
            log.info(f"  批次 {batch_num}: unit {batch[0]['unit_id']}-{batch[-1]['unit_id']}")

            # 只传必要字段，减少 token
            slim_units = [{
                "unit_id": u["unit_id"],
                "text": u.get("text", ""),
                "estimated_reading_seconds": u.get("estimated_reading_seconds", 10),
            } for u in batch]

            units_json = json.dumps(slim_units, ensure_ascii=False, indent=2)

            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"请为以下 {len(batch)} 个内容单元生成画面点（必须每个 unit 对应一个 beat，不能少）:\n\n{units_json}"},
                ],
                temperature=0.3,
                max_tokens=8000,
            )

            try:
                data = extract_json(response.choices[0].message.content)
            except ValueError:
                log.warn(f"    批次 {batch_num} JSON 解析失败，降级为逐条重试...")
                # 降级：逐条处理
                beats = []
                for u in batch:
                    solo = json.dumps([{"unit_id": u["unit_id"], "text": u.get("text", ""), "estimated_reading_seconds": u.get("estimated_reading_seconds", 10)}], ensure_ascii=False, indent=2)
                    try:
                        r2 = self.client.chat.completions.create(
                            model=LLM_MODEL, messages=[{"role": "system", "content": prompt}, {"role": "user", "content": f"请为以下 1 个内容单元生成画面点:\n\n{solo}"}],
                            temperature=0.3, max_tokens=2000,
                        )
                        d2 = extract_json(r2.choices[0].message.content)
                        beats.extend(d2.get("visual_beats", []))
                    except Exception:
                        log.warn(f"      降级 unit {u['unit_id']} 也失败，跳过")
                        # 构造一个兜底 beat
                        beats.append({
                            "beat_id": u["unit_id"], "unit_id": u["unit_id"], "unit_ids": [u["unit_id"]],
                            "stage": "explanation", "covered_text": u.get("text", "")[:100],
                            "core_message": "（自动生成）", "visual_reason": "降级生成",
                            "visual_goal": "展示对应内容", "visual_type": "concept",
                            "estimated_display_seconds": u.get("estimated_reading_seconds", 10),
                            "status": "ready",
                        })
                data = {"visual_beats": beats}
            beats = data.get("visual_beats", [])
            log.info(f"    生成了 {len(beats)} 个 beat（预期 {len(batch)}）")

            # 检测截断：返回数量少于预期
            if len(beats) < len(batch):
                log.warn(f"    截断！预期 {len(batch)} 个，实际 {len(beats)} 个，对缺失的单独重试...")
                returned_ids = {b.get("unit_id") or (b.get("unit_ids", [0])[0] if b.get("unit_ids") else 0) for b in beats}
                for u in batch:
                    if u["unit_id"] not in returned_ids:
                        log.info(f"      补提 unit {u['unit_id']}...")
                        solo_json = json.dumps([{
                            "unit_id": u["unit_id"],
                            "text": u.get("text", ""),
                            "estimated_reading_seconds": u.get("estimated_reading_seconds", 10),
                        }], ensure_ascii=False, indent=2)
                        try:
                            r2 = self.client.chat.completions.create(
                                model=LLM_MODEL,
                                messages=[
                                    {"role": "system", "content": prompt},
                                    {"role": "user", "content": f"请为以下 1 个内容单元生成画面点:\n\n{solo_json}"},
                                ],
                                temperature=0.3, max_tokens=2000,
                            )
                            d2 = extract_json(r2.choices[0].message.content)
                            beats.extend(d2.get("visual_beats", []))
                        except Exception as e:
                            log.warn(f"      补提 unit {u['unit_id']} 失败: {e}")

            all_beats.extend(beats)
            batch_num += 1

        # 重新编号 beat_id（保证连续，且等于 unit_id）
        for i, beat in enumerate(all_beats):
            beat["beat_id"] = i + 1

        # 确保 unit_id 字段存在（兼容单数/复数）
        for beat in all_beats:
            if "unit_id" not in beat and "unit_ids" in beat:
                uids = beat["unit_ids"]
                beat["unit_id"] = uids[0] if isinstance(uids, list) else uids
            if "unit_ids" not in beat and "unit_id" in beat:
                beat["unit_ids"] = [beat["unit_id"]]

        data = {
            "book_name": content_units_data.get("book_name", ""),
            "chapter": content_units_data.get("chapter", ""),
            "knowledge_point": content_units_data.get("knowledge_point", ""),
            "source_content_units": "content_units.json",
            "visual_extraction_principle": f"分批提取：{batch_num - 1} 批，每批 {self.BATCH_SIZE} 个单元，总计 {len(all_beats)} 个画面点",
            "total_visual_beats": len(all_beats),
            "visual_beats": all_beats,
        }

        log.success(f"画面节点提取完成：{data['total_visual_beats']} 个 beat（输入 {total} 个 unit）")
        return data

    def validate_visual_beats(self, data: dict, content_units_data: dict) -> list[str]:
        """校验画面节点，返回警告列表"""
        warnings = []
        beats = data.get("visual_beats", [])
        total = data.get("total_visual_beats", 0)
        all_unit_ids = {u.get("unit_id") for u in content_units_data.get("content_units", [])}

        # 1. 总数匹配
        if total != len(beats):
            warnings.append(f"total_visual_beats({total}) 不等于数组长度({len(beats)})")
            data["total_visual_beats"] = len(beats)

        # 2. 数量必须等于 content_units
        expected = len(content_units_data.get("content_units", []))
        if len(beats) != expected:
            warnings.append(f"画面点数量({len(beats)}) 不等于内容单元数量({expected})，丢失了 {expected - len(beats)} 个")

        # 3. beat_id 连续递增
        expected_id = 1
        for b in beats:
            if b.get("beat_id", 0) != expected_id:
                warnings.append(f"beat_id 不连续: 期望 {expected_id}，实际 {b.get('beat_id')}")
            expected_id = b.get("beat_id", 0) + 1

        # 4. 必填字段
        required = ["beat_id", "stage", "covered_text", "core_message",
                     "visual_reason", "visual_goal", "visual_type", "estimated_display_seconds", "status"]
        for b in beats:
            for field in required:
                if field not in b:
                    warnings.append(f"beat {b.get('beat_id', '?')} 缺少字段: {field}")

            # unit_id 校验（兼容单数/复数）
            uid = b.get("unit_id") or (b.get("unit_ids", [None])[0] if b.get("unit_ids") else None)
            if uid is None:
                warnings.append(f"beat {b.get('beat_id', '?')} 缺少 unit_id")
            elif uid not in all_unit_ids:
                warnings.append(f"beat {b.get('beat_id', '?')} 引用了不存在的 unit_id: {uid}")

            if not b.get("covered_text", "").strip():
                warnings.append(f"beat {b.get('beat_id', '?')} covered_text 为空")
            if not b.get("visual_goal", "").strip():
                warnings.append(f"beat {b.get('beat_id', '?')} visual_goal 为空")
            if not isinstance(b.get("estimated_display_seconds"), (int, float)):
                warnings.append(f"beat {b.get('beat_id', '?')} estimated_display_seconds 不是数字")

        # 5. 覆盖率警告
        covered_ids = set()
        for b in beats:
            uid = b.get("unit_id") or (b.get("unit_ids", [None])[0] if b.get("unit_ids") else None)
            if uid:
                covered_ids.add(uid)
        missing = all_unit_ids - covered_ids
        if missing:
            warnings.append(f"以下 unit_id 没有被任何 beat 覆盖: {sorted(missing)}")

        if warnings:
            log.warn(f"画面节点校验发现 {len(warnings)} 个问题")
        else:
            log.success("画面节点校验通过")
        return warnings

    def save_visual_beats(self, data: dict, kp_dir: Path):
        """保存 visual_beats.json"""
        kp_dir.mkdir(parents=True, exist_ok=True)
        path = kp_dir / "visual_beats.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"画面节点已保存: {path}")
        return path

    def run(self, kp_dir: Path) -> Path:
        """一键执行：加载→提取→校验→保存"""
        content_units_data = self.load_content_units(kp_dir)
        data = self.extract(content_units_data)
        warnings = self.validate_visual_beats(data, content_units_data)
        if warnings:
            for w in warnings:
                log.warn(f"  {w}")
        return self.save_visual_beats(data, kp_dir)

    # ========== 工具 ==========

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return ""
