"""
StrategyValidator — 策略验证引擎

管理策略生命周期: testing → validated → rejected

状态机:
  testing ──(连续20条样本有效 OR 50+样本且>70%成功率)──▶ validated
  testing ──(连续10条样本失效)──▶ rejected
  validated ──(连续5条样本失效)──▶ rejected
  rejected: 不再提升，所有选择查询过滤掉

策略规则（strategy_memory.json）:
  - 每次分析自动生成结构/开场/模型规则
  - 规则从数据分析中归纳，非人工编写
  - 格式：{rule, avg_play_increase, sample_count, confidence, status}

用法:
    validator = StrategyValidator(Path("memory"))
    entry = validator.record_strategy_outcome("信息差+规则揭秘结构", success=True)
    validated = validator.get_validated_strategies()
    rejected = validator.get_rejected_strategies()
    rules = validator.get_rules()
    validator.learn_from_analysis(structures, openings, models, topics)
"""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional


class StrategyValidator:
    """策略验证引擎"""

    # 生命周期阈值
    PROMOTION_MIN_SAMPLES = 20
    PROMOTION_CONSECUTIVE_SUCCESSES = 20
    PROMOTION_SUCCESS_RATE = 0.7
    TESTING_REJECTION_FAILURES = 10
    VALIDATED_REJECTION_FAILURES = 5

    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.pool_path = self.memory_dir / "strategy_pool.json"
        self.memory_path = self.memory_dir / "strategy_memory.json"

    # ================================================================
    # 策略池 API（基于 strategy_pool.json）
    # ================================================================

    def record_strategy_outcome(self, strategy_name: str, success: bool,
                                 context: Optional[dict] = None) -> dict:
        """
        记录策略结果，更新策略池。

        Args:
            strategy_name: 策略名称
            success: True=成功, False=失败
            context: 可选的上下文

        Returns:
            更新后的策略条目
        """
        pool = self._load_pool()
        entry = self._find_or_create(pool, strategy_name, context)

        if success:
            entry["success_count"] += 1
            entry["consecutive_successes"] += 1
            entry["consecutive_failures"] = 0
        else:
            entry["failure_count"] += 1
            entry["consecutive_failures"] += 1
            entry["consecutive_successes"] = 0

        total = entry["success_count"] + entry["failure_count"]
        entry["confidence"] = round(entry["success_count"] / max(total, 1), 2)
        entry["last_tested_at"] = datetime.now().isoformat()

        old_status = entry["status"]
        new_status = self._check_transition(entry)
        if new_status and new_status != old_status:
            entry["status"] = new_status
            entry["transitioned_at"] = datetime.now().isoformat()

        history_entry = {
            "strategy_name": strategy_name,
            "success": success,
            "context": context or {},
            "previous_status": old_status,
            "new_status": entry["status"],
            "timestamp": datetime.now().isoformat(),
        }
        pool.setdefault("history", []).append(history_entry)
        if len(pool["history"]) > 500:
            pool["history"] = pool["history"][-500:]

        pool["last_updated"] = datetime.now().isoformat()
        self._save_pool(pool)
        return entry

    def get_validated_strategies(self) -> list[dict]:
        """返回所有已验证的策略"""
        pool = self._load_pool()
        return [s for s in pool.get("strategies", [])
                if s["status"] == "validated"]

    def get_testing_strategies(self) -> list[dict]:
        """返回所有测试中的策略"""
        pool = self._load_pool()
        return [s for s in pool.get("strategies", [])
                if s["status"] == "testing"]

    def get_rejected_strategies(self) -> list[dict]:
        """返回所有已淘汰策略（不再使用）"""
        pool = self._load_pool()
        return [s for s in pool.get("strategies", [])
                if s["status"] == "rejected"]

    def select_best_strategies(self, context: Optional[dict] = None,
                                top_n: int = 3) -> list[dict]:
        """
        从已验证策略池中选择最优策略。

        Args:
            context: {"category": "...", "structure": "...", "opening": "..."}
            top_n: 返回数量

        Returns:
            [{"strategy": {...}, "match_score": X}, ...]
        """
        validated = self.get_validated_strategies()
        if not validated:
            return []

        scored = []
        for s in validated:
            score = 0.0
            ctx_struct = (context or {}).get("structure", "")
            strategy_ctx = s.get("context", {})
            if ctx_struct and strategy_ctx.get("structure") == ctx_struct:
                score += 0.5
            ctx_cat = (context or {}).get("category", "")
            strategy_cat = strategy_ctx.get("category", "")
            if ctx_cat and strategy_cat and ctx_cat == strategy_cat:
                score += 0.3
            score += s.get("confidence", 0) * 0.2
            scored.append({"strategy": s, "match_score": round(score, 2)})

        scored.sort(key=lambda x: -x["match_score"])
        return scored[:top_n]

    def get_summary(self) -> dict:
        """返回策略池统计摘要"""
        pool = self._load_pool()
        strategies = pool.get("strategies", [])
        history = pool.get("history", [])

        validated = [s for s in strategies if s["status"] == "validated"]
        testing = [s for s in strategies if s["status"] == "testing"]
        rejected = [s for s in strategies if s["status"] == "rejected"]
        recent_additions = [s for s in strategies
                            if s.get("created_at", "")[:10] >= "2026-06-16"]

        return {
            "total_strategies": len(strategies),
            "validated_count": len(validated),
            "testing_count": len(testing),
            "rejected_count": len(rejected),
            "recent_additions_count": len(recent_additions),
            "recent_additions": recent_additions[-5:],
            "recent_history": history[-10:],
        }

    def reject_strategy(self, strategy_name: str, reason: str = "") -> Optional[dict]:
        """手动淘汰一个策略"""
        pool = self._load_pool()
        for s in pool.get("strategies", []):
            if s["name"] == strategy_name and s["status"] != "rejected":
                s["status"] = "rejected"
                s["transitioned_at"] = datetime.now().isoformat()
                s["rejection_reason"] = reason
                pool["last_updated"] = datetime.now().isoformat()
                self._save_pool(pool)
                return s
        return None

    # ================================================================
    # 策略规则 API（基于 strategy_memory.json）
    # ================================================================

    def learn_from_analysis(self, structures: dict,
                             openings: dict,
                             content_models: dict,
                             topics: dict) -> list[dict]:
        """
        从结构分析结果中学习，自动生成/更新策略规则。

        Args:
            structures: analyze_content_structures() 的结果
            openings: analyze_openings() 的结果
            content_models: analyze_content_models() 的结果
            topics: analyze_topics() 的结果

        Returns:
            新增或更新的规则列表
        """
        memory = self._load_memory()
        updated_rules = []
        now = datetime.now().isoformat()

        # 从结构排行榜生成规则
        for r in structures.get("rankings", []):
            rule = self._upsert_rule(memory, r["structure"], {
                "category": "content_structure",
                "avg_play_increase": r.get("pct_better_than_average", 0),
                "sample_count": r["sample_count"],
                "confidence": r["confidence"],
                "avg_metric": r["avg_metric"],
            })
            updated_rules.append(rule)

        # 从开场排行榜生成规则
        for r in openings.get("rankings", []):
            rule = self._upsert_rule(memory, r["opening"], {
                "category": "opening",
                "avg_play_increase": r.get("pct_better_than_average", 0),
                "sample_count": r["sample_count"],
                "confidence": r["confidence"],
                "avg_metric": r["avg_metric"],
            })
            updated_rules.append(rule)

        # 从内容模型排行榜生成规则
        for r in content_models.get("self", []):
            rule = self._upsert_rule(memory, r["model"], {
                "category": "content_model",
                "avg_play_increase": r.get("pct_better_than_average", 0),
                "sample_count": r["sample_count"],
                "confidence": r["confidence"],
                "avg_metric": r["avg_metric"],
            })
            updated_rules.append(rule)

        # 从主题排行榜生成规则
        for r in topics.get("rankings", []):
            rule = self._upsert_rule(memory, r["topic"], {
                "category": "topic",
                "avg_play_increase": r.get("avg_metric", 0),
                "sample_count": r["sample_count"],
                "confidence": r["confidence"],
                "avg_metric": r["avg_metric"],
            })
            updated_rules.append(rule)

        memory["last_updated"] = now
        self._save_memory(memory)
        return updated_rules

    def get_rules(self, category: str = "") -> list[dict]:
        """
        获取所有策略规则，可按类别筛选。

        Args:
            category: "content_structure" | "opening" | "content_model" | "topic" | ""

        Returns:
            规则列表，按 avg_play_increase 降序
        """
        memory = self._load_memory()
        rules = memory.get("rules", [])
        if category:
            rules = [r for r in rules if r.get("category") == category]
        rules.sort(key=lambda x: -abs(x.get("avg_play_increase", 0)))
        return rules

    def get_rejected_rules(self) -> list[dict]:
        """获取已淘汰的策略规则"""
        return [r for r in self.get_rules() if r.get("status") == "rejected"]

    def get_validated_rules(self) -> list[dict]:
        """获取已验证的策略规则"""
        return [r for r in self.get_rules() if r.get("status") == "validated"]

    def get_testing_rules(self) -> list[dict]:
        """获取测试中的策略规则"""
        return [r for r in self.get_rules() if r.get("status") == "testing"]

    def get_learning_center_data(self) -> dict:
        """
        返回学习中心所需的完整数据。

        Returns:
            {
                "structures": [...],  # 结构规则
                "openings": [...],     # 开场规则
                "content_models": [...],  # 模型规则
                "topics": [...],       # 主题规则
                "recent_rules": [...], # 最近新增
                "recent_rejected": [...], # 最近淘汰
                "next_to_test": [...], # 待测试
            }
        """
        all_rules = self.get_rules()
        structures = [r for r in all_rules if r.get("category") == "content_structure"]
        openings = [r for r in all_rules if r.get("category") == "opening"]
        content_models = [r for r in all_rules if r.get("category") == "content_model"]
        topics = [r for r in all_rules if r.get("category") == "topic"]

        # 最近5条新增规则（按创建时间倒序）
        recent_rules = sorted(
            [r for r in all_rules if r.get("status") != "rejected"],
            key=lambda x: x.get("created_at", ""), reverse=True
        )[:5]

        # 最近淘汰的规则
        recent_rejected = sorted(
            [r for r in all_rules if r.get("status") == "rejected"],
            key=lambda x: x.get("last_updated", ""), reverse=True
        )[:5]

        # 待测试（置信度最低的 testing 规则）
        next_to_test = sorted(
            [r for r in all_rules if r.get("status") == "testing" and r.get("sample_count", 0) < 20],
            key=lambda x: x.get("confidence", 0)
        )[:5]

        return {
            "structures": structures,
            "openings": openings,
            "content_models": content_models,
            "topics": topics,
            "recent_rules": recent_rules,
            "recent_rejected": recent_rejected,
            "next_to_test": next_to_test,
        }

    # ================================================================
    # 内部方法
    # ================================================================

    # ---- strategy_pool.json ----

    def _load_pool(self) -> dict:
        if self.pool_path.exists():
            try:
                return json.loads(self.pool_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"strategies": [], "history": []}
        return {"strategies": [], "history": []}

    def _save_pool(self, data: dict):
        self.pool_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _find_or_create(self, pool: dict, name: str,
                        context: Optional[dict]) -> dict:
        for s in pool.get("strategies", []):
            if s["name"] == name:
                return s
        entry = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "source": "self_analysis",
            "category": (context or {}).get("category", ""),
            "context": context or {},
            "success_count": 0, "failure_count": 0,
            "consecutive_successes": 0, "consecutive_failures": 0,
            "confidence": 0.0,
            "status": "testing",
            "created_at": datetime.now().isoformat(),
            "last_tested_at": datetime.now().isoformat(),
            "transitioned_at": "", "notes": "",
        }
        pool.setdefault("strategies", []).append(entry)
        return entry

    def _check_transition(self, entry: dict) -> Optional[str]:
        status = entry["status"]
        if status == "testing":
            total = entry["success_count"] + entry["failure_count"]
            if total >= self.PROMOTION_MIN_SAMPLES and \
               entry["confidence"] >= self.PROMOTION_SUCCESS_RATE:
                return "validated"
            if entry["consecutive_successes"] >= self.PROMOTION_CONSECUTIVE_SUCCESSES:
                return "validated"
            if entry["consecutive_failures"] >= self.TESTING_REJECTION_FAILURES:
                return "rejected"
        elif status == "validated":
            if entry["consecutive_failures"] >= self.VALIDATED_REJECTION_FAILURES:
                return "rejected"
        return None

    # ---- strategy_memory.json ----

    def _load_memory(self) -> dict:
        if self.memory_path.exists():
            try:
                return json.loads(self.memory_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"rules": [], "history": []}
        return {"rules": [], "history": []}

    def _save_memory(self, data: dict):
        self.memory_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _upsert_rule(self, memory: dict, name: str,
                     data: dict) -> dict:
        """查找或创建规则，更新统计"""
        rules = memory.setdefault("rules", [])
        for r in rules:
            if r["rule"] == name and r.get("category") == data.get("category"):
                # 更新现有规则
                old_sample = r.get("sample_count", 0)
                new_sample = data.get("sample_count", 0)
                # 加权平均 avg_play_increase
                old_inc = r.get("avg_play_increase", 0)
                new_inc = data.get("avg_play_increase", 0)
                total_sample = old_sample + new_sample
                if total_sample > 0:
                    r["avg_play_increase"] = round(
                        (old_inc * old_sample + new_inc * new_sample) / total_sample, 1
                    )
                r["sample_count"] = total_sample
                r["avg_metric"] = data.get("avg_metric", r.get("avg_metric", 0))
                r["confidence"] = round(min(1.0, total_sample / 20), 2)
                r["last_updated"] = datetime.now().isoformat()

                # 检查生命周期状态
                if total_sample >= 20 and r.get("avg_play_increase", 0) > 0:
                    r["status"] = "validated"
                elif total_sample >= 10 and r.get("avg_play_increase", 0) <= 0:
                    r["status"] = "rejected"
                return r

        # 创建新规则
        rule = {
            "id": str(uuid.uuid4())[:8],
            "rule": name,
            "category": data.get("category", "content_structure"),
            "avg_play_increase": data.get("avg_play_increase", 0),
            "avg_metric": data.get("avg_metric", 0),
            "sample_count": data.get("sample_count", 0),
            "confidence": data.get("confidence", 0),
            "status": "testing",
            "first_seen": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
        }
        if rule["sample_count"] >= 20 and rule["avg_play_increase"] > 0:
            rule["status"] = "validated"
        elif rule["sample_count"] >= 10 and rule["avg_play_increase"] <= 0:
            rule["status"] = "rejected"
        rules.append(rule)
        return rule
