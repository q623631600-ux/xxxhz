"""
图片生成服务 — 调用 GPT-Image API 生成图片
输入 image_prompts.json → 下载图片到 images/ → 更新 image_prompts.json

错误分级（按 Claude Code 图文生成工作流规则）：
  Hard Error  → 401/402 立即暂停整个工作流
  Soft Error  → 503/超时/DNS 连续2张失败则暂停
  Rate Limit  → 429 仅重试1次(3-5s)，失败计入连续计数
"""
import json
import os
import time
import shutil
from datetime import datetime
from pathlib import Path
import requests
from dotenv import load_dotenv

from utils.logger import log


class HardError(Exception):
    """Hard Error: 401 API Key 失效, 402 余额不足, 403 无权限 — 必须人工处理，不重试"""
    pass


class ImageGenerator:
    """GPT-Image 图片生成（OpenAI 兼容接口，支持双API切换 + 并发模式）"""

    MODEL = "gpt-image-2"
    STYLE_PREFIX = "美式漫画风格，粗黑轮廓线，半色调网点，动态构图，强烈光影对比，富有张力的画面感，16:9横屏。"
    MAX_CONCURRENT = 3          # 最大并发数（降低并发避免 API 超时）
    REQUEST_INTERVAL = 3.0       # 正常请求间隔（秒）— 并发模式下只在提交批次间生效
    RATE_LIMIT_RETRY_DELAY = 4   # 429 重试等待（秒）

    # API 配置池
    APIS = {
        1: {"name": "lk888", "url_env": "IMAGE_API1_URL", "key_env": "IMAGE_API1_KEY", "size_env": "IMAGE_API1_SIZE", "default_size": "1920x1088", "async": True},
    }
    _active_api = None

    def __init__(self):
        env_path = Path(__file__).parent.parent / ".env"
        load_dotenv(env_path)
        self.MODEL = os.getenv("IMAGE_MODEL", "") or self.MODEL
        self._load_active_api()

    def _load_active_api(self):
        """加载当前激活的 API 配置"""
        active = int(os.getenv("IMAGE_ACTIVE_API", "1"))
        self._active_api = active
        cfg = self.APIS.get(active, self.APIS[1])
        self.API_URL = os.getenv(cfg["url_env"], "") or f"https://default/{cfg['name']}"
        self.API_KEY = os.getenv(cfg["key_env"], "")
        self.SIZE = os.getenv(cfg["size_env"], "") or cfg["default_size"]
        self.RESOLUTION = cfg.get("resolution", "")
        self.IS_ASYNC = cfg.get("async", False)

    def switch_api(self, api_num: int):
        """切换 API"""
        if api_num not in self.APIS:
            raise ValueError(f"API 编号无效: {api_num}")
        self._active_api = api_num
        env_path = Path(__file__).parent.parent / ".env"
        self._update_env(env_path, "IMAGE_ACTIVE_API", str(api_num))
        os.environ["IMAGE_ACTIVE_API"] = str(api_num)
        self._load_active_api()
        log.info(f"已切换到 API {api_num}: {self.APIS[api_num]['name']} ({self.API_URL})")

    @staticmethod
    def _update_env(env_path: Path, key: str, value: str):
        """更新 .env 中的键值"""
        lines = env_path.read_text(encoding="utf-8").splitlines()
        new_lines = []
        for line in lines:
            if line.startswith(key + "="):
                new_lines.append(f"{key}={value}")
            else:
                new_lines.append(line)
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    def get_active_api_info(self) -> dict:
        """返回当前 API 信息"""
        cfg = self.APIS.get(self._active_api, self.APIS[1])
        return {
            "active": self._active_api,
            "name": cfg["name"],
            "url": self.API_URL,
            "size": self.SIZE,
        }

    # ========== 公共接口 ==========

    def load_image_prompts(self, kp_dir: Path) -> dict:
        path = kp_dir / "image_prompts.json"
        if not path.exists():
            raise FileNotFoundError(f"未找到 image_prompts.json: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def generate_images(self, kp_dir: Path, max_images: int = 0) -> dict:
        """为所有 waiting_api 的提示词生成图片

        规则：
          - 第一轮生成全部图片
          - 后续每轮只重试失败图片，跳过已成功的
          - 每张图片连续失败 4 次 → 永久标记为 failed_permanent，不再重试
          - Hard Error → 立即暂停，提示用户
          - 点一次按钮跑到底，全部完成后自动结束
        """
        MAX_RETRY_ROUNDS = 10  # 最多自动重试10轮（实际会被per-image 4次上限截断）

        if not self.API_KEY:
            raise RuntimeError("IMAGE_API_KEY 未配置，请在 .env 中设置")

        data = self.load_image_prompts(kp_dir)
        items = data.get("items", [])
        images_dir = kp_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        progress_path = kp_dir / "generate_progress.json"
        checkpoint_path = kp_dir / "generate_checkpoint.json"

        # 先写一个初始进度，让前端轮询能看到"开始"状态，避免来回跳
        total = len(items)
        self._write_progress(progress_path, "generating", total, 0, 0, 0, 0, 0)

        # 清理旧状态（checkpoint 和 pause。flag 不影响前端进度）
        for stale in ["pause.flag", "generate_checkpoint.json"]:
            stale_path = kp_dir / stale
            if stale_path.exists():
                stale_path.unlink()

        # 重新生成时：重置所有失败/占位图，重新尝试
        reset_count = 0
        for i in items:
            if i.get("image_status") in ("failed", "failed_permanent", "no_prompt"):
                i["image_status"] = "waiting_api"
                i["_fail_count"] = 0
                i["_error"] = None
                # 清理占位图，避免 _sync_file_status 误判为已生成
                bid = i.get("beat_id", 0)
                if bid > 0:
                    img_path = images_dir / f"beat_{bid:03d}.png"
                    if img_path.exists():
                        try:
                            img_path.unlink()
                        except Exception:
                            pass
                reset_count += 1
        if reset_count:
            log.info(f"  重置 {reset_count} 张失败图片为待生成（已清除占位图）")
            self._save(kp_dir, data)

        # 先检查哪些 beat 已有图片文件，自动标记为 generated
        pre_fixed = self._sync_file_status(items, images_dir, kp_dir)

        already_done = sum(1 for i in items if i.get("image_status") == "generated")
        log.info(f"共 {len(items)} 个提示词，{already_done} 张已完成，{pre_fixed} 张已有文件")

        total_generated = 0
        total_failed = 0
        total_api_calls = 0
        all_failed_items = []
        hard_error_occurred = False

        # 初始化每张图片的连续失败计数（首次运行时设为0，已有值的保留）
        for i in items:
            if "_fail_count" not in i:
                i["_fail_count"] = 0

        for round_num in range(1, MAX_RETRY_ROUNDS + 1):
            # 每轮只处理 waiting_api 或 failed 的图片（跳过 failed_permanent）
            waiting = [i for i in items
                       if i.get("image_status") in ("waiting_api", "failed")
                       and i.get("beat_id", 0) >= 0
                       and i.get("_fail_count", 0) < 4]

            if not waiting:
                break

            if max_images > 0:
                waiting = waiting[:max_images]

            total_waiting = len(waiting)
            round_label = f"第{round_num}轮" if round_num > 1 else ""
            log.info(f"{round_label} 并发生成 {total_waiting} 张图片（并发数: {self.MAX_CONCURRENT}）...")

            # 并发处理
            batch_result = self._process_batch_concurrent(waiting, items, data, kp_dir, images_dir, progress_path)

            total_generated += batch_result["generated"]
            total_failed += batch_result["failed"]
            total_api_calls += batch_result["api_calls"]
            all_failed_items.extend(batch_result["failed_items"])

            hard_error_occurred = batch_result.get("hard_error", False)
            pause_reason = batch_result.get("pause_reason")
            if hard_error_occurred:
                break
            if pause_reason == "user_paused":
                break

            # 检查每张失败图片的连续失败次数，标记永久失败
            for i in items:
                if i.get("image_status") == "generated":
                    i["_fail_count"] = 0  # 成功则重置
                elif i.get("image_status") == "failed":
                    i["_fail_count"] = i.get("_fail_count", 0) + 1
                    if i["_fail_count"] >= 4:
                        log.warn(f"  ⛔ beat {i.get('beat_id')}: 连续失败 {i['_fail_count']} 次，永久停止重试")
                        i["image_status"] = "failed_permanent"
                        i["_error"] = f"[永久失败] 连续{i['_fail_count']}次生成失败"

            self._save(kp_dir, data)

            # 判断是否还有可重试的图片
            still_retryable = [i for i in items
                               if i.get("image_status") == "failed"
                               and i.get("_fail_count", 0) < 4
                               and i.get("beat_id", 0) >= 0]
            still_failed = sum(1 for i in items if i.get("image_status") == "failed")
            perm_failed = sum(1 for i in items if i.get("image_status") == "failed_permanent")

            if still_retryable and round_num < MAX_RETRY_ROUNDS and not hard_error_occurred:
                retry_delay = 10 * round_num
                log.info(f"  本轮完成: {batch_result['generated']}成功 / {still_failed}可重试 / {perm_failed}永久失败，{retry_delay}s 后自动重试...")
                time.sleep(retry_delay)
                # 可重试的标记回 waiting_api（保留原始错误，用于排查）
                for i in items:
                    if i.get("image_status") == "failed" and i.get("_fail_count", 0) < 4:
                        i["image_status"] = "waiting_api"
                        orig_err = i.get("_error", "未知错误")
                        i["_error"] = f"[第{round_num}轮] {orig_err}"
                self._save(kp_dir, data)
            elif still_retryable:
                log.info("  达到最大轮数，停止重试")

        # === 完成 ===
        final_generated = sum(1 for i in items if i.get("image_status") == "generated")
        final_failed = sum(1 for i in items if i.get("image_status") in ("failed", "failed_permanent", "no_prompt"))
        permanent_failed = sum(1 for i in items if i.get("image_status") == "failed_permanent")
        self._write_progress(progress_path, "finish", len(items), final_generated, final_failed, 0, total_api_calls, 0)

        # 生成失败报告
        perm_items = [{"beat_id": i.get("beat_id"), "error": i.get("_error", ""), "fail_count": i.get("_fail_count", 0)}
                      for i in items if i.get("image_status") == "failed_permanent"]
        self._generate_failure_report(kp_dir, final_generated, final_failed, len(items), total_api_calls,
                                       perm_items + all_failed_items, "hard_error" if hard_error_occurred else None)

        log.success(f"图片生成完成: {final_generated}成功, {final_failed}失败(其中{permanent_failed}张永久失败), {total_api_calls}次API调用")

        return {
            "success": True,
            "generated": final_generated,
            "failed": final_failed,
            "permanent_failed": permanent_failed,
            "total": len(items),
            "api_calls": total_api_calls,
            "pause_reason": "hard_error" if hard_error_occurred else None,
            "failed_items": all_failed_items,
        }

    def retry_failed_only(self, kp_dir: Path) -> dict:
        """重试失败图片：包括 failed 和 failed_permanent，全部重置后重新生成"""
        data = self.load_image_prompts(kp_dir)
        items = data.get("items", [])
        retryable = [i for i in items if i.get("image_status") in ("failed", "failed_permanent")
                     and i.get("beat_id", 0) >= 0]

        if not retryable:
            log.info("没有需要重试的失败项")
            return {"success": True, "generated": 0, "failed": 0, "message": "没有失败项"}

        log.info(f"一键重跑: {len(retryable)} 张（含永久失败）")
        for item in retryable:
            item["image_status"] = "waiting_api"
            item["_error"] = None
            item["_fail_count"] = 0  # 重置失败计数，重新尝试
        self._save(kp_dir, data)

        return self.generate_images(kp_dir)

    def regenerate_all(self, kp_dir: Path) -> dict:
        """全量重生成：清空图片目录，全部重置为 waiting_api，适合比例变更后迁移"""
        import shutil
        data = self.load_image_prompts(kp_dir)
        items = data.get("items", [])
        images_dir = kp_dir / "images"

        # 不再直接删除图片，只清状态，旧图会在生成时被覆盖

        # 全部重置为 waiting_api（封面 beat=0 也要重生成）
        reset_count = 0
        for item in items:
            if item.get("beat_id", 0) >= 0:
                item["image_status"] = "waiting_api"
                item["image_path"] = None
                item["_error"] = None
                reset_count += 1
        self._save(kp_dir, data)

        log.info(f"全量重生成: {reset_count} 张，旧图已清除，新尺寸={self.SIZE}")
        return self.generate_images(kp_dir)

    def _sync_file_status(self, items: list, images_dir: Path, kp_dir: Path) -> int:
        """检查 images 目录已有文件，自动更新 image_prompts 状态"""
        from config import OUTPUT_DIR
        fixed = 0
        for item in items:
            bid = item.get("beat_id", 0)
            if bid < 0:
                continue

            # beat_id=0 封面：检查书级别封面是否存在
            if bid == 0:
                book_name = ""
                # 从 kp_dir 路径推断书名 (output/<book>/kp_xxx/)
                if kp_dir.parent.parent == OUTPUT_DIR:
                    book_name = kp_dir.parent.name
                if book_name:
                    book_cover = OUTPUT_DIR / book_name / "cover.png"
                    if book_cover.exists():
                        # 封面已存在，标记为已生成（避免重复调用API）
                        if item.get("image_status") != "generated":
                            item["image_status"] = "generated"
                            item["image_path"] = str(book_cover.relative_to(OUTPUT_DIR / book_name))
                            fixed += 1
                    else:
                        # 不存在则从已有 beat_000 迁移
                        for ext in [".png", ".jpg", ".jpeg"]:
                            beat000 = images_dir / f"beat_000{ext}"
                            if beat000.exists():
                                log.info(f"  迁移封面: {beat000} → {book_cover}")
                                self._make_book_cover(beat000, book_name, book_cover)
                                item["image_status"] = "generated"
                                item["image_path"] = f"images/beat_000{ext}"
                                fixed += 1
                                break
                continue  # 封面不参与常规状态同步

            if item.get("image_status") == "generated":
                # 已有生成标记，检查文件是否还在
                img_path_str = item.get("image_path", "")
                if img_path_str:
                    abs_path = kp_dir / img_path_str
                    if not abs_path.exists():
                        item["image_status"] = "waiting_api"
                        item["image_path"] = None
                        item["_error"] = "文件丢失，需重新生成"
                        fixed += 1
                continue
            # 检查是否有对应图片文件
            patterns = [
                f"beat_{bid:03d}.png", f"beat_{bid:03d}.jpg", f"beat_{bid:03d}.jpeg",
                f"beat_{bid:02d}.png", f"beat_{bid:02d}.jpg", f"beat_{bid:02d}.jpeg",
                f"{bid-1}.jpeg", f"{bid-1}.jpg", f"{bid-1}.png",
            ]
            found = None
            for p in patterns:
                if (images_dir / p).exists():
                    found = p
                    break
            if found:
                # 跳过占位图（小文件），重新生成
                found_path = images_dir / found
                if found_path.stat().st_size < 20000:
                    item["image_status"] = "waiting_api"
                    item["image_path"] = None
                    item["_error"] = "占位图需重新生成"
                    fixed += 1
                    continue
                # 文件存在且不是占位图，直接使用
                item["image_status"] = "generated"
                item["image_path"] = f"images/{found}"
                fixed += 1
        if fixed > 0:
            regenerating = sum(1 for i in items if i.get("_error") == "比例不匹配，自动重生成")
            skipped = fixed - regenerating
            parts = []
            if skipped > 0:
                parts.append(f"{skipped} 张已有")
            if regenerating > 0:
                parts.append(f"{regenerating} 张比例不匹配需重生成")
            log.info(f"  文件同步: {'，'.join(parts)}")
        return fixed

    def _needs_regeneration(self, image_path: Path) -> bool:
        """检测图片比例是否与当前配置匹配，不匹配则需重生成"""
        try:
            expected_w, expected_h = map(int, self.SIZE.split("x"))
            expected_ratio = expected_w / expected_h

            from PIL import Image
            img = Image.open(str(image_path))
            actual_w, actual_h = img.size
            img.close()
            actual_ratio = actual_w / actual_h

            # 误差超过 5% 视为比例不匹配，统一用配置尺寸
            if abs(actual_ratio - expected_ratio) > 0.05:
                log.info(f"  {image_path.name}: 比例不匹配 ({actual_w}x{actual_h}, "
                         f"实际{actual_ratio:.2f} ≠ 期望{expected_ratio:.2f})，自动重生成")
                return True
            return False
        except Exception:
            return False  # 无法读取则保留原状态

    # ========== 并发处理 ==========

    def _process_single_item(self, item: dict, kp_dir: Path, images_dir: Path) -> dict:
        """处理单个图片生成任务（线程安全，供并发池调用）"""
        beat_id = item.get("beat_id", "?")
        prompt_text = self.STYLE_PREFIX + item.get("image_prompt", "").strip()

        result = {
            "beat_id": beat_id,
            "status": "failed",
            "error_type": "",
            "error_msg": "",
            "api_calls": 0,
        }

        if not prompt_text:
            result["status"] = "no_prompt"
            result["error_msg"] = "image_prompt 为空"
            self._create_placeholder_img(images_dir, beat_id)
            return result

        try:
            image_url = self._call_api(prompt_text)
            result["api_calls"] = 1
            image_path = self._download(image_url, images_dir, beat_id)
            result["status"] = "generated"
            result["image_path"] = str(image_path.relative_to(kp_dir))
            return result
        except HardError as e:
            result["status"] = "hard_error"
            result["error_type"] = "hard_error"
            result["error_msg"] = str(e)[:200]
            self._create_placeholder_img(images_dir, beat_id)
            return result
        except Exception as e:
            error_msg = str(e)
            result["status"] = "failed"
            if "429" in error_msg:
                result["error_type"] = "rate_limit"
            elif "timeout" in error_msg.lower():
                result["error_type"] = "timeout"
            elif "connection" in error_msg.lower():
                result["error_type"] = "connection"
            elif "HTTP 5" in error_msg:
                result["error_type"] = "server_error"
            elif "content_filter" in error_msg.lower():
                result["error_type"] = "content_filter"
            else:
                result["error_type"] = "unknown"
            result["error_msg"] = error_msg[:200]
            self._create_placeholder_img(images_dir, beat_id)
            return result

    def _process_batch_concurrent(self, waiting: list, items: list, data: dict,
                                   kp_dir: Path, images_dir: Path, progress_path: Path) -> dict:
        """并发处理一批 waiting 图片 - 维护满载任务池，完成一个补充一个"""
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

        total = len(waiting)
        generated = 0
        failed = 0
        api_calls = 0
        hard_error_occurred = False
        pause_reason = None
        all_failed = []

        with ThreadPoolExecutor(max_workers=self.MAX_CONCURRENT) as executor:
            futures = {}          # future → (index, item)
            next_idx = 0
            completed_count = 0

            def submit_one():
                """提交下一个待处理任务到线程池"""
                nonlocal next_idx
                if next_idx >= total:
                    return None
                idx = next_idx
                item = waiting[idx]
                next_idx += 1
                fut = executor.submit(self._process_single_item, item, kp_dir, images_dir)
                futures[fut] = (idx, item)
                return fut

            # 第1步：填满并发池
            submitted = 0
            for _ in range(self.MAX_CONCURRENT):
                if submit_one() is not None:
                    submitted += 1
            log.info(f"  并发池已提交 {submitted} 个任务（最大 {self.MAX_CONCURRENT} 并发）")

            # 第2步：主循环 — 完成一个 → 处理结果 → 补充一个
            while futures:
                done_set, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)

                for fut in done_set:
                    idx, item = futures.pop(fut)
                    # 跳过被取消的任务
                    if fut.cancelled():
                        continue

                    try:
                        result = fut.result()
                    except Exception as e:
                        result = {
                            "beat_id": item.get("beat_id", "?"),
                            "status": "failed",
                            "error_type": "thread_error",
                            "error_msg": str(e)[:200],
                            "api_calls": 0,
                        }

                    beat_id = item.get("beat_id", "?")
                    api_calls += result.get("api_calls", 0)

                    if result["status"] == "hard_error":
                        # === Hard Error → 立即停止所有任务 ===
                        log.error(f"  !!! Hard Error beat {beat_id}: {result['error_msg'][:200]}")
                        item["image_status"] = "failed"
                        item["_error"] = f"[Hard Error] {result['error_msg'][:300]}"
                        failed += 1
                        all_failed.append({
                            "beat_id": beat_id,
                            "error_type": "hard_error",
                            "error_msg": result["error_msg"][:200],
                            "timestamp": datetime.now().isoformat(),
                        })
                        hard_error_occurred = True
                        pause_reason = "hard_error"
                        # 取消所有剩余任务
                        for f in list(futures.keys()):
                            f.cancel()
                        futures.clear()
                        break

                    elif result["status"] == "generated":
                        item["image_status"] = "generated"
                        item["image_path"] = result.get("image_path", "")
                        item["_error"] = None
                        generated += 1
                        # 封面特殊处理
                        if beat_id == 0:
                            book_name = data.get("book_name", "")
                            cover_target = item.get("_book_cover_path", "")
                            if book_name and cover_target:
                                img_path = images_dir / f"beat_{beat_id:03d}.png"
                                if img_path.exists():
                                    self._make_book_cover(img_path, book_name, Path(cover_target))

                    elif result["status"] == "no_prompt":
                        item["image_status"] = "no_prompt"
                        item["_error"] = "image_prompt 为空"
                        failed += 1
                        all_failed.append({
                            "beat_id": beat_id, "error_type": "no_prompt",
                            "error_msg": "image_prompt 为空", "timestamp": datetime.now().isoformat(),
                        })

                    else:
                        # 失败 → 标记，后续轮次重试
                        item["image_status"] = "failed"
                        item["_error"] = result.get("error_msg", "")[:300]
                        failed += 1
                        err_type = result.get("error_type", "unknown")
                        all_failed.append({
                            "beat_id": beat_id, "error_type": err_type,
                            "error_msg": result.get("error_msg", "")[:200],
                            "timestamp": datetime.now().isoformat(),
                        })

                    completed_count += 1
                    self._write_progress(progress_path, "generating", total, completed_count,
                                         generated, failed, api_calls, 0)
                    self._save(kp_dir, data)

                    # 检查暂停标志
                    if (kp_dir / "pause.flag").exists():
                        log.warn(f"  !!! 检测到暂停标志，停止生成。已完成 {completed_count}/{total}")
                        pause_reason = "user_paused"
                        # 未完成的标记回 waiting_api
                        for r in range(next_idx, total):
                            waiting[r]["image_status"] = "waiting_api"
                            waiting[r]["_error"] = "用户手动暂停"
                        for f in list(futures.keys()):
                            f.cancel()
                        futures.clear()
                        self._save(kp_dir, data)
                        break

                    # 补充新任务到池中
                    if not hard_error_occurred:
                        submit_one()

            # 清理取消的任务引用
            futures.clear()

        return {
            "generated": generated,
            "failed": failed,
            "api_calls": api_calls,
            "failed_items": all_failed,
            "hard_error": hard_error_occurred,
            "pause_reason": pause_reason,
        }

    # ========== API 调用 ==========

    REQUEST_INTERVAL = 3.0       # 正常请求间隔（秒）— 并发模式下只在提交批次间生效
    RATE_LIMIT_RETRY_DELAY = 4   # 429 重试等待（秒）

    # API 配置池
    APIS = {
        1: {"name": "lk888", "url_env": "IMAGE_API1_URL", "key_env": "IMAGE_API1_KEY", "size_env": "IMAGE_API1_SIZE", "default_size": "1920x1088", "async": True},
    }
    _active_api = None

    def _call_api(self, prompt: str) -> str:
        """调用 GPT-Image API，按错误类型分级处理：

        Hard Error (401/402) → 立即抛 HardError，不重试
        Rate Limit (429)    → 等待3-5s后重试1次
        Soft Error (5xx/超时/连接) → 重试1次
        内容审核/4xx        → 不重试
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.API_KEY}",
        }
        body = {
            "model": self.MODEL,
            "prompt": prompt,
            "n": 1,
            "size": self.SIZE,
        }
        if self.RESOLUTION:
            body["resolution"] = self.RESOLUTION
        else:
            body["response_format"] = "url"

        if self.IS_ASYNC:
            return self._call_async(prompt)

        last_error = None
        # 最多2次调用：原始1次 + 重试1次（仅429/5xx/网络异常允许重试）
        for attempt in range(2):
            try:
                resp = requests.post(self.API_URL, headers=headers, json=body, timeout=180)

                if resp.status_code == 200:
                    result = resp.json()
                    data_list = result.get("data", [])
                    if not data_list:
                        raise RuntimeError(f"API 返回空 data: {json.dumps(result, ensure_ascii=False)[:300]}")
                    url = data_list[0].get("url", "")
                    if not url:
                        b64 = data_list[0].get("b64_json", "")
                        if b64:
                            raise RuntimeError("API 返回 base64 而非 URL，请设置 response_format=url")
                        raise RuntimeError(f"API 返回无 url: {json.dumps(data_list[0], ensure_ascii=False)[:200]}")
                    return url

                # === 非 200：按状态码分类 ===
                error_detail = resp.text[:500]

                # Hard Error: 401 API Key, 402 余额不足, 403 无权限 → 立即终止
                if resp.status_code in (401, 402, 403):
                    raise HardError(f"HTTP {resp.status_code}: {error_detail}")

                # 内容审核拒绝 → 不重试
                if "content_filter" in error_detail.lower() or "safety" in error_detail.lower():
                    raise RuntimeError(f"[内容审核] HTTP {resp.status_code}: {error_detail}")

                # 429 Rate Limit → 允许重试1次
                if resp.status_code == 429 and attempt == 0:
                    log.info(f"    速率限制(429)，{self.RATE_LIMIT_RETRY_DELAY}s 后重试...")
                    time.sleep(self.RATE_LIMIT_RETRY_DELAY)
                    last_error = RuntimeError(f"HTTP 429: {error_detail}")
                    continue

                # 400 限流（某些API用400而非429返回限流）→ 允许重试
                if resp.status_code == 400 and attempt == 0:
                    if any(kw in error_detail for kw in ["限制", "limit", "rate", "等待", "wait"]):
                        log.info(f"    被限流(400)，{self.RATE_LIMIT_RETRY_DELAY}s 后重试...")
                        time.sleep(self.RATE_LIMIT_RETRY_DELAY)
                        last_error = RuntimeError(f"HTTP 400(限流): {error_detail}")
                        continue

                # 5xx 服务端错误 → 允许重试1次
                if resp.status_code >= 500 and attempt == 0:
                    log.info(f"    服务端错误({resp.status_code})，3s 后重试...")
                    time.sleep(3)
                    last_error = RuntimeError(f"HTTP {resp.status_code}: {error_detail}")
                    continue

                # 其他 4xx → 不重试
                last_error = RuntimeError(f"HTTP {resp.status_code}: {error_detail}")
                raise last_error

            except HardError:
                raise  # 直接向上抛，不捕获

            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if attempt == 0:
                    log.info(f"    网络异常({type(e).__name__})，3s 后重试...")
                    time.sleep(3)
                    last_error = e
                    continue
                last_error = e

            # 第二次尝试也失败 → 不再重试
            break

        raise last_error or RuntimeError("API 调用失败")

    def _call_async(self, prompt: str) -> str:
        """异步 API（lk888）：创建任务 → 轮询 → 返回图片 URL"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.API_KEY}",
        }
        body = {
            "model": self.MODEL,
            "prompt": prompt,
            "n": 1,
            "size": self.SIZE,
        }

        # 1. 创建任务
        resp = requests.post(self.API_URL, headers=headers, json=body, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"创建任务失败 HTTP {resp.status_code}: {resp.text[:300]}")
        rj = resp.json()
        # 检查业务状态码（lx888 等 API 在 HTTP 200 里返回 402 表示余额不足）
        biz_code = rj.get("code", 0)
        if biz_code and biz_code != 0 and biz_code != 200:
            err_msg = rj.get("msg", rj.get("message", resp.text[:300]))
            if biz_code in (401, 402, 403):
                raise HardError(f"API 业务错误 code={biz_code}: {err_msg}")
            raise RuntimeError(f"API 业务错误 code={biz_code}: {err_msg}")
        task_id = rj.get("data", {}).get("task_id")
        if not task_id:
            raise RuntimeError(f"未获取到 task_id: {resp.text[:300]}")

        # 2. 轮询状态（容错：连接异常时重试，不直接崩溃）
        status_url = self.API_URL.rsplit("/", 1)[0] + "/status"
        consecutive_errors = 0
        for _ in range(300):  # 最多等 10 分钟
            time.sleep(2)
            try:
                sr = requests.get(f"{status_url}?task_id={task_id}", headers=headers, timeout=30)
                if sr.status_code != 200:
                    consecutive_errors += 1
                    continue
                consecutive_errors = 0
                sd = sr.json()
                if sd.get("is_final"):
                    url = sd.get("result_url", "")
                    if not url:
                        raise RuntimeError(f"任务完成但无 result_url: {sr.text[:300]}")
                    return url
                if sd.get("state") == "failed":
                    raise RuntimeError(f"任务失败: {sd.get('error', sr.text[:300])}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                consecutive_errors += 1
                if consecutive_errors > 5:
                    raise RuntimeError(f"连续 {consecutive_errors} 次查询状态失败: {e}")
                continue

        raise RuntimeError(f"任务超时未完成 (task_id={task_id})")

    def _download(self, url: str, images_dir: Path, beat_id) -> Path:
        """下载图片到本地，统一保存为 beat_NNN.png，自动清除旧后缀文件"""
        import base64
        import re

        ext = ".png"
        filename = f"beat_{beat_id:03d}{ext}"
        filepath = images_dir / filename

        # 先清除同一 beat 的旧后缀文件（.jpg/.jpeg/.webp），避免残留
        for old_ext in [".jpg", ".jpeg", ".webp"]:
            old_file = images_dir / f"beat_{beat_id:03d}{old_ext}"
            if old_file.exists():
                old_file.unlink()

        # data URI: data:image/png;base64,xxxxx
        if url.startswith("data:"):
            match = re.match(r"data:image/(\w+);base64,(.+)", url, re.DOTALL)
            if match:
                b64_data = match.group(2)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(b64_data))
                return filepath
            raise RuntimeError(f"无法解析 data URI: {url[:100]}...")

        # 普通 HTTP URL
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            resp.raw.decode_content = True
            shutil.copyfileobj(resp.raw, f)

        return filepath

    def _make_book_cover(self, source_image: Path, book_name: str, target_path: Path):
        """给封面图添加书名文字，保存到书级别目录"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            log.warn("Pillow 未安装，直接复制封面（无书名文字）")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_image), str(target_path))
            return

        try:
            img = Image.open(str(source_image)).convert("RGB")

            # 按 1920x1080 缩放（封面图可能是 2K）
            target_w, target_h = 1920, 1080
            img_ratio = img.width / img.height
            target_ratio = target_w / target_h
            if img_ratio > target_ratio:
                new_h = target_h
                new_w = int(target_h * img_ratio)
            else:
                new_w = target_w
                new_h = int(target_w / img_ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            # 居中裁剪
            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            img = img.crop((left, top, left + target_w, top + target_h))

            draw = ImageDraw.Draw(img)

            # 标题文字
            title = f"《{book_name}》"
            # 尝试加载中文字体
            font_paths = [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/simsun.ttc",
            ]
            font = None
            font_size = 72
            for fp in font_paths:
                if Path(fp).exists():
                    try:
                        font = ImageFont.truetype(fp, font_size)
                        break
                    except Exception:
                        continue

            if font is None:
                font = ImageFont.load_default()

            # 计算文字位置：左侧区域，垂直居中偏上
            # 封面人物在右侧，文字放左侧
            text_bbox = draw.textbbox((0, 0), title, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]

            # 左侧 1/3 区域居中
            text_x = (target_w * 0.35) - (text_w / 2)
            text_y = (target_h - text_h) / 2 - 40

            # 文字阴影（黑色半透明）
            shadow_offset = 3
            draw.text((text_x + shadow_offset, text_y + shadow_offset), title,
                      fill=(0, 0, 0, 180), font=font)

            # 文字主体（白色）
            draw.text((text_x, text_y), title, fill=(255, 255, 255), font=font)

            # 副标题
            subtitle = "深度解读 · 知识讲解"
            sub_font_size = 32
            sub_font = None
            for fp in font_paths:
                if Path(fp).exists():
                    try:
                        sub_font = ImageFont.truetype(fp, sub_font_size)
                        break
                    except Exception:
                        continue
            if sub_font is None:
                sub_font = ImageFont.load_default()

            sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font)
            sub_w = sub_bbox[2] - sub_bbox[0]
            sub_x = (target_w * 0.35) - (sub_w / 2)
            sub_y = text_y + text_h + 20

            draw.text((sub_x + 2, sub_y + 2), subtitle, fill=(0, 0, 0, 180), font=sub_font)
            draw.text((sub_x, sub_y), subtitle, fill=(220, 220, 220), font=sub_font)

            # 保存
            target_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(target_path), "PNG")
            log.success(f"  书籍封面已保存（含书名）: {target_path}")

        except Exception as e:
            log.warn(f"  封面文字添加失败: {e}，直接复制原图")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(source_image), str(target_path))

    def _save(self, kp_dir: Path, data: dict):
        path = kp_dir / "image_prompts.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_progress(self, progress_path: Path, stage: str, total: int, current: int,
                        generated: int, failed: int, api_calls: int = 0, consecutive_fails: int = 0):
        """写生成进度文件，供前端轮询"""
        try:
            data = {
                "stage": stage,
                "total": total,
                "current": current,
                "generated": generated,
                "failed": failed,
                "api_calls": api_calls,
                "consecutive_fails": consecutive_fails,
                "message": (
                    f"正在生成... {current}/{total}（{generated}成功, {failed}失败, "
                    f"API调用{api_calls}次, 连续失败{consecutive_fails}）"
                    if stage == "generating" else
                    f"已暂停（{generated}成功, {failed}失败, API调用{api_calls}次）" if stage == "paused" else
                    f"完成（API调用{api_calls}次, {generated}张成功, {failed}张失败）"
                ),
            }
            progress_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _create_placeholder_img(self, images_dir: Path, beat_id: int):
        """为失败图片生成占位图，保证后续视频合成不中断"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return

        try:
            from config import VIDEO_WIDTH, VIDEO_HEIGHT
            w, h = VIDEO_WIDTH, VIDEO_HEIGHT
        except Exception:
            w, h = 1920, 1080

        filepath = images_dir / f"beat_{beat_id:03d}.png"
        if filepath.exists():
            return  # 已有占位图，不覆盖

        img = Image.new("RGB", (w, h), color=(30, 30, 40))
        draw = ImageDraw.Draw(img)

        # 加载字体
        font = None
        for fp in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"]:
            if Path(fp).exists():
                try:
                    font = ImageFont.truetype(fp, 48)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()

        text = f"图片 {beat_id}\n生成失败"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(((w - tw) / 2, (h - th) / 2), text, fill=(180, 180, 180), font=font)

        img.save(str(filepath), "PNG")
        log.info(f"    占位图已生成: beat_{beat_id:03d}.png")

    def _save_checkpoint(self, checkpoint_path: Path, last_failed_index: int,
                         consecutive_fails: int, reason: str):
        """保存暂停检查点，供恢复时使用"""
        try:
            data = {
                "last_failed_index": last_failed_index,
                "consecutive_fails": consecutive_fails,
                "pause_reason": reason,
                "timestamp": datetime.now().isoformat(),
            }
            checkpoint_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info(f"  检查点已保存: last_failed_index={last_failed_index}, reason={reason}")
        except Exception:
            pass

    def _generate_failure_report(self, kp_dir: Path, generated: int, failed: int, total: int,
                                 api_calls: int, failed_items: list, pause_reason: str | None):
        """生成失败报告 JSON"""
        try:
            rate = f"{generated / max(total, 1) * 100:.1f}%"
            report = {
                "total_images": total,
                "generated": generated,
                "failed": failed,
                "success_rate": rate,
                "api_calls": api_calls,
                "efficiency": f"{api_calls}次API调用 → {generated}张成功",
                "pause_reason": pause_reason,
                "failed_items": failed_items,
                "generated_at": datetime.now().isoformat(),
            }
            report_path = kp_dir / "failure_report.json"
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

            # 打印摘要
            log.info(f"  {'='*50}")
            log.info(f"  失败报告: {generated}/{total} 成功 ({rate}), {api_calls}次API调用")
            if failed_items:
                log.info(f"  失败明细:")
                for fi in failed_items:
                    log.info(f"    beat {fi['beat_id']}: [{fi['error_type']}] {fi['error_msg'][:100]}")
            if pause_reason:
                log.info(f"  暂停原因: {pause_reason}")
            log.info(f"  {'='*50}")
        except Exception:
            pass

    # ========== 一键执行 ==========

    def run(self, kp_dir: Path, max_images: int = 0) -> dict:
        return self.generate_images(kp_dir, max_images=max_images)
