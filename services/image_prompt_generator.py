"""
第 3 层：图片提示词模型
输入 visual_beats.json → 输出 image_prompts.json
"""
import json
from pathlib import Path
from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, PROMPTS_DIR
from utils.logger import log
from utils.json_utils import extract_json


class ImagePromptGenerator:
    """画面节点 → 图片提示词"""

    BATCH_SIZE = 2  # 每批 2 个 beat，防止输出截断

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

    def load_visual_beats(self, kp_dir: Path) -> dict:
        path = kp_dir / "visual_beats.json"
        if not path.exists():
            raise FileNotFoundError(f"未找到 visual_beats.json: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _process_batch(self, batch: list, prompt: str, batch_label: str, style_ref: str = "", _depth: int = 0) -> list:
        """处理一个批次，返回 items 列表。如果截断则自动拆分重试。"""
        MAX_RETRY_DEPTH = 5
        if _depth > MAX_RETRY_DEPTH:
            log.error(f"  {batch_label} 重试深度耗尽 ({_depth})，放弃 {len(batch)} 个 beat")
            return []

        beats_json = json.dumps([{
            "beat_id": b["beat_id"], "stage": b.get("stage"),
            "visual_type": b.get("visual_type"), "covered_text": b.get("covered_text", ""),
            "core_message": b.get("core_message"), "visual_goal": b.get("visual_goal"),
            "estimated_display_seconds": b.get("estimated_display_seconds"),
        } for b in batch], ensure_ascii=False, indent=2)

        # 注入统一风格参考，确保所有批次风格一致
        style_instruction = ""
        if style_ref:
            style_instruction = (
                f"\n\n## 统一风格参考（所有图片必须严格遵循，不可偏离）\n\n"
                f"{style_ref}\n\n"
                f"**关键要求：这 {len(batch)} 张图片将出现在同一个视频中，"
                f"必须看起来像是同一个画师在同一时间创作的，风格100%一致。"
                f"色调、线条粗细、光影处理、人物面部特征——全部要一样。**\n"
            )

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"请为以下 {len(batch)} 个 visual beats 生成图片提示词:\n\n{beats_json}{style_instruction}"},
            ],
            temperature=0.7, max_tokens=16000,
        )

        # 检测 LLM 输出是否被截断
        finish = response.choices[0].finish_reason
        if finish == "length":
            log.warn(f"  {batch_label} LLM 输出被截断 (finish_reason=length)")

        raw_text = response.choices[0].message.content
        try:
            data = extract_json(raw_text)
        except ValueError as e:
            log.error(f"  {batch_label} JSON 解析失败，原始响应前 200 字符: {raw_text[:200]}")
            if _depth < MAX_RETRY_DEPTH:
                log.info(f"  重试整个批次（深度 {_depth + 1}）...")
                return self._process_batch(batch, prompt, batch_label, style_ref, _depth + 1)
            log.error(f"  {batch_label} 重试耗尽，放弃 {len(batch)} 个 beat")
            return []
        items = data.get("items", [])

        # 检测截断：返回数量少于预期
        if len(items) < len(batch):
            log.warn(f"  {batch_label} 截断：预期 {len(batch)} 个，实际 {len(items)} 个")

            # 找出缺失的 beat_id
            returned_ids = {it.get("beat_id") for it in items}
            missing = [b for b in batch if b["beat_id"] not in returned_ids]

            if missing:
                if len(missing) < len(batch):
                    # 有进展：缺失数比总数少，继续递归重试
                    log.info(f"  重试缺失的 {len(missing)} 个 beat...（深度 {_depth + 1}）")
                    retry_items = self._process_batch(missing, prompt, f"{batch_label}-retry", style_ref, _depth + 1)
                    items.extend(retry_items)
                else:
                    # 一个都没返回（LLM 输出完全不可解析），逐条重试
                    log.warn(f"  {batch_label} 完全截断（0/{len(batch)}），逐条重试...")
                    for b in missing:
                        retry_items = self._process_batch([b], prompt, f"{batch_label}-beat{b['beat_id']}", style_ref, _depth + 1)
                        items.extend(retry_items)

        return items

    def generate_prompts(self, visual_beats_data: dict, kp_dir: Path = None,
                         agent_context_block: str = "") -> dict:
        """为每个 visual beat 生成图片提示词（分批，避免截断）"""
        beats = visual_beats_data.get("visual_beats", [])
        total = len(beats)
        log.info(f"正在生成图片提示词（{total} 个 beat，每批 {self.BATCH_SIZE} 个）...")

        prompt = self._load_prompt("image_prompt_generator.txt")
        if agent_context_block:
            prompt = prompt.replace("{agent_strategy_context}", agent_context_block)
            log.info(f"  [OK] 已注入 Agent Strategy Context")

        # 构建统一风格参考字符串（注入到每个批次，确保风格一致）
        style_ref = self._build_style_reference()

        all_items = []
        batch_num = 1

        for start in range(0, total, self.BATCH_SIZE):
            batch = beats[start:start + self.BATCH_SIZE]
            label = f"批次{batch_num}(beat {batch[0]['beat_id']}-{batch[-1]['beat_id']})"
            log.info(f"  {label}")

            items = self._process_batch(batch, prompt, label, style_ref)
            log.info(f"    生成 {len(items)} 个提示词")
            all_items.extend(items)
            batch_num += 1

        book_name = visual_beats_data.get("book_name", "")
        data = {
            "book_name": book_name,
            "chapter": visual_beats_data.get("chapter", ""),
            "knowledge_point": visual_beats_data.get("knowledge_point", ""),
            "source_visual_beats": "visual_beats.json",
            "style": "现代知识类视频插画风，干净简洁，柔和光影，信息表达清晰，人物一律为外国人形象（欧美面孔），适合抖音读书类视频。横屏 16:9，构图主体突出，背景简化，预留字幕空间。",
            "total_prompts": len(all_items),
            "items": all_items,
        }

        # 封面图：书级别共用，检查是否已存在
        # 使用安全的目录名（与实际文件系统路径一致）
        from config import OUTPUT_DIR
        book_dir_name = kp_dir.parent.name if kp_dir else book_name
        book_cover_path = OUTPUT_DIR / book_dir_name / "cover.png"
        if book_cover_path.exists():
            log.info(f"  书籍封面已存在，跳过: {book_cover_path}")
            # 不插入 beat_id=0，所有 KP 共用同一张封面
        else:
            # 需要生成新封面（只生成一次，存在书级别目录下）
            cover_prompt = {
                "beat_id": 0, "stage": "cover", "visual_type": "scene",
                "covered_text": f"《{book_name}》知识讲解",
                "core_message": f"《{book_name}》知识讲解视频封面",
                "visual_goal": "封面画面：展示博主形象与书本主题，同一本书所有视频共用此封面",
                "image_prompt": (
                    "欧美男性，深色西装，双手交叉抱胸，大腿以上。旁边有一本书。"
                    "背景简洁书房，表情自信沉稳。现代插画风，外国人形象。"
                    "16:9 横屏，人物居中偏右，左侧预留标题空间。"
                    "画面中无任何文字。"
                ),
                "negative_prompt": "中文文字、英文文字、LOGO、标题、标签、海报风、真实照片风、亚洲面孔、政治人物",
                "image_status": "waiting_api", "image_path": None,
                "notes": f"【书级别封面】《{book_name}》所有视频共用此封面图",
                "_book_cover_path": str(book_cover_path),  # 使用安全目录名
            }
            data["items"].insert(0, cover_prompt)
            data["total_prompts"] = len(data["items"])

        log.success(f"图片提示词生成完成：{data['total_prompts']} 个（含封面）")
        return data

    def validate_prompts(self, data: dict, visual_beats_data: dict) -> list[str]:
        warnings = []
        items = data.get("items", [])
        all_beat_ids = {b["beat_id"] for b in visual_beats_data.get("visual_beats", [])}

        # 封面不计入比对
        beat_items = [i for i in items if i.get("stage") != "cover"]

        if len(beat_items) != visual_beats_data.get("total_visual_beats", 0):
            warnings.append(f"图片提示词数量({len(beat_items)}) 与画面点数量({visual_beats_data.get('total_visual_beats', 0)}) 不一致")

        # 检查缺失的 beat
        generated_ids = {i.get("beat_id") for i in beat_items}
        missing_ids = all_beat_ids - generated_ids - {0}
        if missing_ids:
            warnings.append(f"缺失以下 beat 的提示词: {sorted(missing_ids)}")

        for item in items:
            bid = item.get("beat_id")
            if bid != 0 and bid not in all_beat_ids:
                warnings.append(f"item beat {bid} 不在 visual_beats 中")
            if not item.get("image_prompt", "").strip():
                warnings.append(f"item beat {bid} image_prompt 为空")

        if warnings:
            log.warn(f"图片提示词校验: {len(warnings)} 个问题")
        else:
            log.success("图片提示词校验通过")
        return warnings

    def save_prompts(self, data: dict, kp_dir: Path):
        kp_dir.mkdir(parents=True, exist_ok=True)
        path = kp_dir / "image_prompts.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.success(f"图片提示词已保存: {path}")
        return path

    def run(self, kp_dir: Path) -> Path:
        visual_beats_data = self.load_visual_beats(kp_dir)
        # 读取 plan 中的 Agent Strategy Context
        agent_context_block = ""
        plan_path = kp_dir.parent / "knowledge_plan.json"
        if plan_path.exists():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                agent_context_block = plan.get("_agent_context_block", "")
            except Exception:
                pass
        data = self.generate_prompts(visual_beats_data, kp_dir,
                                     agent_context_block=agent_context_block)

        # 自动注入统一风格前缀到每条 prompt
        STYLE_TAG = "美式漫画风格，"
        for item in data.get("items", []):
            prompt = item.get("image_prompt", "").strip()
            if prompt and not prompt.startswith(STYLE_TAG):
                item["image_prompt"] = STYLE_TAG + prompt
            item.setdefault("image_status", "waiting_api")
            item.setdefault("image_path", None)
            item.setdefault("negative_prompt", "大段长文段落、海报风、真实照片风、亚洲面孔、政治人物、战争、暴力、血腥")

        warnings = self.validate_prompts(data, visual_beats_data)
        for w in warnings:
            log.warn(f"  {w}")
        return self.save_prompts(data, kp_dir)

    def _build_style_reference(self) -> str:
        """构建统一的风格参考描述，确保所有批次的图片风格高度一致"""
        return (
            "## 统一画风标准（所有图片100%遵循）\n\n"
            "**画风类型：** 现代知识讲解漫画风 (Modern Educational Comic Style)\n\n"
            "**色彩体系：**\n"
            "- 主色调：暖米色(#F5E6D3)、深棕(#4A3728)、复古蓝(#3A5C7A)、暗红(#8B4545)\n"
            "- 辅助色：灰绿(#7A9A8E)、奶油黄(#FFF8E7)、炭灰(#3C3C3C)\n"
            "- 禁止使用：荧光色、高饱和色(饱和度>60%)、纯黑(#000000)、纯白(#FFFFFF)\n\n"
            "**线条风格：**\n"
            "- 所有人物和主要物体必须有明显的黑色描边（线宽约2-3pt）\n"
            "- 线条粗细均匀，有轻微的手绘感\n"
            "- 背景元素用更细的线条（约1pt），区分层次\n\n"
            "**上色方式：**\n"
            "- 纯色块填充，无渐变、无3D光影\n"
            "- 阴影用稍深一点的同色系色块表示，不要模糊过渡\n"
            "- 高光用稍亮一点的同色系色块表示\n\n"
            "**人物特征：**\n"
            "- 统一欧美面孔，轮廓分明\n"
            "- 发色：棕色、深金、红棕色\n"
            "- 表情夸张但不过度，像欧美漫画角色\n"
            "- 身材比例正常，不Q版不写实\n\n"
            "**画面密度：**\n"
            "- 每张图1-2个视觉焦点，背景干净\n"
            "- 画面底部20%区域保持简洁，留给字幕\n"
            "- 不堆砌元素，信息量适中\n\n"
            "**材质感：**\n"
            "- 轻微纸张纹理（像印在略粗糙的纸上）\n"
            "- 不是光滑的数字渲染\n"
            "- 不是水彩晕染，不是油画笔触\n\n"
            "**构图规则：**\n"
            "- 16:9横屏，主体居中或黄金分割点\n"
            "- 视线引导线指向主体\n"
            "- 不同图片的构图要有变化，但画法一致"
        )

    def _load_prompt(self, filename: str) -> str:
        prompt_file = PROMPTS_DIR / filename
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
        return ""
