"""
第 1 层：内容单元切分模型
输入 full_script → 输出 content_units.json（分批处理，避免输出截断）
"""
import json
import re
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR
from utils.logger import log
from utils.json_utils import extract_json

class ContentUnitSegmenter:
    """完整脚本 → 内容单元"""

    # 脚本读取优先级
    SCRIPT_NAMES = ["script_edited.json", "script_safe.json", "script.json"]
    # 每批最多处理的字符数（脚本>2000字时会自动分片，增加上下文重叠避免边界断裂）
    CHUNK_MAX_CHARS = 2000
    # 上下文重叠字符数——每个分片会在开头附带上一片末尾的这段文字作为上下文参考
    OVERLAP_CHARS = 200

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not LLM_API_KEY:
                raise RuntimeError("LLM_API_KEY 未配置")
            self._client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        return self._client

    # ========== 脚本分片 ==========

    def _split_script(self, full_text: str) -> list[dict]:
        """将脚本按自然段落分片，每片不超过 CHUNK_MAX_CHARS，带上下文重叠"""
        # 先按双换行分段（自然段落）
        paragraphs = re.split(r'\n\s*\n', full_text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # 如果某段过长，按句号切分
        split_paras = []
        for para in paragraphs:
            if len(para) <= self.CHUNK_MAX_CHARS * 1.2:
                split_paras.append(para)
            else:
                sentences = re.split(r'(?<=[。！？])', para)
                current = ""
                for s in sentences:
                    if len(current) + len(s) > self.CHUNK_MAX_CHARS and current:
                        split_paras.append(current.strip())
                        current = s
                    else:
                        current += s
                if current.strip():
                    split_paras.append(current.strip())

        # 按段落分片，片与片之间有重叠
        chunks = []
        current_chunk = []
        current_len = 0

        for para in split_paras:
            if current_len + len(para) > self.CHUNK_MAX_CHARS and current_chunk:
                # 当前片：正文
                chunk_text = "\n\n".join(current_chunk)
                chunks.append({"text": chunk_text, "context": ""})
                # 下一片的上下文重叠：取当前片末尾的一小段
                overlap = ""
                acc = 0
                for p in reversed(current_chunk):
                    if acc + len(p) > self.OVERLAP_CHARS and overlap:
                        break
                    overlap = p + "\n\n" + overlap if overlap else p
                    acc += len(p)
                # 开始新片，带上重叠上下文
                current_chunk = [para]
                current_len = len(para)
                chunks[-1]["next_context"] = overlap  # 标记给下一片用
            else:
                current_chunk.append(para)
                current_len += len(para)

        # 最后一片
        if current_chunk:
            chunk_text = "\n\n".join(current_chunk)
            chunks.append({"text": chunk_text, "context": ""})

        # 为每片（除第一片外）添加上下文头
        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            if prev_chunk.get("next_context"):
                chunks[i]["context"] = prev_chunk["next_context"]

        return chunks

    # ========== 公共接口 ==========

    def load_script(self, kp_dir: Path) -> dict:
        """按优先级加载脚本"""
        for name in self.SCRIPT_NAMES:
            path = kp_dir / name
            if path.exists():
                log.info(f"加载脚本: {path.name}")
                return json.loads(path.read_text(encoding="utf-8"))

        raise FileNotFoundError(
            f"未找到脚本文件。查找路径: {kp_dir}\n"
            f"优先级: {', '.join(self.SCRIPT_NAMES)}"
        )

    def segment(self, script: dict) -> dict:
        """切分脚本为内容单元（分批处理）"""
        full_text = script.get("full_script", "")
        if not full_text:
            raise ValueError("脚本中未找到 full_script 字段")

        log.info(f"正在切分内容单元（脚本 {len(full_text)} 字）...")

        # 短脚本直接处理
        if len(full_text) <= self.CHUNK_MAX_CHARS:
            return self._segment_single(full_text, script)

        # 长脚本分批处理
        chunks = self._split_script(full_text)
        log.info(f"  脚本分为 {len(chunks)} 片，逐片切分（含上下文重叠）...")

        prompt = self._load_prompt("content_unit_segmenter.txt")
        all_units = []

        for i, chunk in enumerate(chunks):
            chunk_text = chunk["text"]
            chunk_context = chunk.get("context", "")
            log.info(f"  片 {i+1}/{len(chunks)}（{len(chunk_text)} 字）...")

            # 如果有上下文，告诉 LLM 上下文信息（不生成单元，仅供参考）
            context_header = ""
            if chunk_context:
                context_header = f"\n\n【前文参考（不需要为其生成单元，仅作为上下文理解）】\n{chunk_context}\n\n"

            response = self.client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"请将以下脚本片段切分为内容单元:\n\n{context_header}{chunk_text}"},
                ],
                temperature=0.3,
                max_tokens=8000,
            )

            try:
                data = extract_json(response.choices[0].message.content)
            except ValueError:
                log.warn(f"  片 {i+1} JSON 解析失败，尝试降级...")
                # 按简单规则切分：每句话一个单元
                import re as _re
                sentences = _re.split(r'(?<=[。！？])', chunk_text)
                units = []
                for si, sent in enumerate(sentences):
                    sent = sent.strip()
                    if not sent:
                        continue
                    secs = max(3, len(sent) // 4)
                    units.append({"unit_id": si + 1, "text": sent, "estimated_reading_seconds": secs})
                if not units:
                    raise  # 彻底失败
                data = {
                    "segmentation_principle": "降级：按句号切分（原始 JSON 解析失败）",
                    "total_units": len(units),
                    "content_units": units,
                }
            units = data.get("content_units", [])
            log.info(f"    生成 {len(units)} 个单元")
            all_units.extend(units)

        # 重新编号
        for j, u in enumerate(all_units):
            u["unit_id"] = j + 1

        result = {
            "book_name": script.get("book_name", ""),
            "chapter": script.get("chapter", ""),
            "knowledge_point": script.get("knowledge_point", ""),
            "source_script": "script.json",
            "segmentation_principle": f"分批切分：{len(chunks)} 片，总计 {len(all_units)} 个单元",
            "total_units": len(all_units),
            "content_units": all_units,
        }

        log.success(f"内容单元切分完成：{result['total_units']} 个单元")
        return result

    def _segment_single(self, text: str, script: dict) -> dict:
        """单次切分（短脚本）"""
        prompt = self._load_prompt("content_unit_segmenter.txt")

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请将以下视频脚本切分为内容单元:\n\n{text}"},
            ],
            temperature=0.3,
            max_tokens=16000,
        )

        try:
            data = extract_json(response.choices[0].message.content)
        except ValueError:
            log.warn("  短脚本 JSON 解析失败，降级为按句号切分...")
            import re as _re
            sentences = _re.split(r'(?<=[。！？])', text)
            units = []
            for si, sent in enumerate(sentences):
                sent = sent.strip()
                if not sent:
                    continue
                secs = max(3, len(sent) // 4)
                units.append({"unit_id": si + 1, "text": sent, "estimated_reading_seconds": secs})
            data = {
                "segmentation_principle": "降级：按句号切分（原始 JSON 解析失败）",
                "total_units": len(units),
                "content_units": units,
            }
        data["book_name"] = script.get("book_name", "")
        data["chapter"] = script.get("chapter", "")
        data["knowledge_point"] = script.get("knowledge_point", "")
        data["source_script"] = "script.json"

        log.success(f"内容单元切分完成：{data.get('total_units', 0)} 个单元")
        return data

    def validate_units(self, data: dict) -> list[str]:
        """校验内容单元，返回警告列表"""
        warnings = []
        units = data.get("content_units", [])
        total = data.get("total_units", 0)

        # 1. 总数匹配
        if total != len(units):
            warnings.append(f"total_units({total}) 不等于数组长度({len(units)})")
            data["total_units"] = len(units)

        # 2. unit_id 连续递增
        expected = 1
        for u in units:
            uid = u.get("unit_id", 0)
            if uid != expected:
                warnings.append(f"unit_id 不连续: 期望 {expected}，实际 {uid}")
            expected = uid + 1

        # 3. 必填字段（精简版）
        required = ["unit_id", "text", "estimated_reading_seconds"]
        for u in units:
            for field in required:
                if field not in u:
                    warnings.append(f"unit {u.get('unit_id', '?')} 缺少字段: {field}")
            if not u.get("text", "").strip():
                warnings.append(f"unit {u.get('unit_id', '?')} text 为空")
            if not isinstance(u.get("estimated_reading_seconds"), (int, float)):
                warnings.append(f"unit {u.get('unit_id', '?')} estimated_reading_seconds 不是数字")

        # 4. 补充 stage 默认值（兼容下游）
        for u in units:
            if "stage" not in u:
                u["stage"] = "explanation"
            if "visual_type" not in u:
                u["visual_type"] = "concept"

        if warnings:
            log.warn(f"内容单元校验发现 {len(warnings)} 个问题")
        else:
            log.success("内容单元校验通过")
        return warnings

    def save_units(self, data: dict, kp_dir: Path):
        """保存 content_units.json"""
        kp_dir.mkdir(parents=True, exist_ok=True)
        path = kp_dir / "content_units.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"内容单元已保存: {path}")
        return path

    def _auto_merge_units(self, data: dict, script: dict) -> dict:
        """如果单元数超限，自动合并相邻单元"""
        units = data.get("content_units", [])
        length_str = script.get("estimated_video_length", script.get("suggested_video_length", ""))
        # 解析时长上限
        max_units = 999
        if "8" in length_str and "-" in length_str and any(c.isdigit() for c in length_str.split("-")[1] if c.isdigit()):
            parts = length_str.split("-")
            try:
                max_minutes = int(''.join(c for c in parts[1] if c.isdigit()))
            except:
                max_minutes = 99
            if max_minutes <= 8:
                max_units = 80
            elif max_minutes <= 12:
                max_units = 100
            else:
                return data  # 超过12分钟不强制

        if len(units) <= max_units:
            return data

        log.warn(f"  单元数 {len(units)} 超过上限 {max_units}，自动合并相邻单元...")
        # 合并策略：相邻单元两两合并，直到不超限
        while len(units) > max_units:
            # 找最短的相邻单元对，合并它们
            best_idx = 0
            best_len = float('inf')
            for i in range(len(units) - 1):
                combined_len = len(units[i]["text"]) + len(units[i+1]["text"])
                if combined_len < best_len:
                    best_len = combined_len
                    best_idx = i
            # 合并
            u1 = units[best_idx]
            u2 = units[best_idx + 1]
            u1["text"] = u1["text"] + u2["text"]
            u1["estimated_reading_seconds"] = u1.get("estimated_reading_seconds", 5) + u2.get("estimated_reading_seconds", 5)
            units.pop(best_idx + 1)

        # 重新编号
        for j, u in enumerate(units):
            u["unit_id"] = j + 1
        data["total_units"] = len(units)
        data["segmentation_principle"] += f"（已自动合并至{len(units)}个单元）"
        log.success(f"  自动合并完成：{len(units)} 个单元")
        return data

    def run(self, kp_dir: Path) -> Path:
        """一键执行：加载→切分→校验→合并→保存"""
        script = self.load_script(kp_dir)
        data = self.segment(script)
        data = self._auto_merge_units(data, script)
        warnings = self.validate_units(data)
        if warnings:
            for w in warnings:
                log.warn(f"  {w}")
        return self.save_units(data, kp_dir)

    # ========== 工具 ==========

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return ""
