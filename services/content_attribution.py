"""
ContentAttributor — 自动归因系统

分析指标背后的原因：
  - 2秒跳出率为什么高/低
  - 完播率为什么高/低
  - 收藏率为什么高/低
  - 涨粉率为什么高/低

双层设计: 规则评分（零成本）+ 可选的LLM增强

用法:
    attributor = ContentAttributor()
    result = attributor.full_attribution(video, signal_profile)
"""

from typing import Optional


class ContentAttributor:
    """自动归因系统"""

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: 可选的 LLM 调用函数，用于生成自然语言解释
                        签名: (system_prompt, user_prompt) -> str
        """
        self.llm = llm_client

    # ================================================================
    # 2秒跳出率归因
    # ================================================================

    def attribution_2s_dropoff(self, video: dict,
                                signal_profile: Optional[dict] = None) -> dict:
        """
        分析2秒跳出率。

        Factors:
          - 开头冲突缺失
          - 无结论前置
          - 无利益点
          - 无价值判断
          - 信号强度不足

        Returns:
            {"score": 0-100 (越高越差), "factors": [...], "recommendations": [...]}
        """
        dropoff_rate = float(video.get("drop_off_rate", 0) or
                             video.get("comp_2s", 0) or 0)
        title = video.get("title", "") or ""
        signals = signal_profile or {}

        factors = []
        recommendations = []
        score = 50  # 默认中等

        # 规则1: 标题是否包含冲突/反常识信号？
        has_conflict = self._signal_detected(signals, "cognitive", "反常识")
        if not has_conflict:
            factors.append({
                "factor": "开头缺少冲突感",
                "detail": "标题/开头没有反常识或对立观点，用户无法快速判断内容价值",
                "impact": "high",
            })
            score += 15
            recommendations.append("开头3秒内给出反常识结论或冲突观点")

        # 规则2: 是否有明确利益点？
        has_benefit = any(
            self._signal_detected(signals, "benefit", sig)
            for sig in ["赚钱", "省钱", "避坑"]
        )
        if not has_benefit:
            factors.append({
                "factor": "开头缺少利益点",
                "detail": "用户无法在头3秒判断'这和我有什么关系'",
                "impact": "high",
            })
            score += 15
            recommendations.append("开头点明对用户的具体价值——省钱、避坑、赚钱")

        # 规则3: 是否有代入信号？
        has_identity = any(
            self._signal_detected(signals, "identification", sig)
            for sig in ["你", "普通人", "打工人"]
        )
        if not has_identity:
            factors.append({
                "factor": "缺少身份代入",
                "detail": "你没有使用'你''普通人''打工人'等代入词，用户觉得与自己无关",
                "impact": "medium",
            })
            score += 10
            recommendations.append("用'你是不是也…'开头，3秒内建立身份关联")

        # 规则4: 标题长度是否过长？
        if len(title) > 30:
            factors.append({
                "factor": "标题过长",
                "detail": f"标题{len(title)}字，超过30字后3秒理解成本上升",
                "impact": "medium",
            })
            score += 10
            recommendations.append("标题控制在15-25字以内，信息密度更高")

        # 规则5: 是否有认知信号？
        has_cognitive = self._signal_detected(signals, "cognitive", "认知升级") or \
                        self._signal_detected(signals, "cognitive", "信息差")
        if has_cognitive:
            # 正向因素：降低跳出
            score -= 10

        score = max(0, min(100, score))
        severity = "high" if score >= 70 else "medium" if score >= 40 else "low"

        result = {
            "metric": "2秒跳出率",
            "value": dropoff_rate,
            "score": score,
            "severity": severity,
            "factors": factors,
            "recommendations": recommendations,
        }

        if self.llm:
            result["llm_explanation"] = self._llm_enhance_dropoff(video, result)

        return result

    # ================================================================
    # 完播率归因
    # ================================================================

    def attribution_completion_rate(self, video: dict,
                                     signal_profile: Optional[dict] = None) -> dict:
        """
        分析完播率。

        Factors:
          - 中段节奏断裂
          - 案例不足
          - 信息密度下降
          - 结构不清晰
        """
        completion = float(video.get("completion_rate", 0) or
                           video.get("comp_5s", 0) or 0)
        signals = signal_profile or {}

        factors = []
        recommendations = []
        score = 50

        # 规则1: 是否有认知升级信号？（正向）
        has_depth = self._signal_detected(signals, "cognitive", "认知升级") or \
                    self._signal_detected(signals, "cognitive", "反常识")
        if not has_depth:
            factors.append({
                "factor": "内容缺乏深度认知",
                "detail": "没有持续提供认知价值，用户中段失去观看动力",
                "impact": "high",
            })
            score += 15
            recommendations.append("结构中段加入一个反常识案例或认知升级点")

        # 规则2: 是否有情绪信号？（正向 —— 维持观看）
        has_emotion = any(
            self._signal_detected(signals, "emotional", sig)
            for sig in ["财富焦虑", "职业焦虑", "身份焦虑"]
        )
        if not has_emotion:
            factors.append({
                "factor": "缺少情绪维持",
                "detail": "内容偏理性，缺少情绪波动点让用户持续观看",
                "impact": "medium",
            })
            score += 10
            recommendations.append("每段加入一个情绪触发点——焦虑、共鸣或意外")

        # 规则3: 利益信号是否持续？
        has_ongoing_benefit = self._signal_detected(signals, "benefit", "避坑") or \
                              self._signal_detected(signals, "benefit", "赚钱")
        if not has_ongoing_benefit:
            factors.append({
                "factor": "持续性利益不足",
                "detail": "用户看不到持续观看的收获，中途离开",
                "impact": "medium",
            })
            score += 10
            recommendations.append("分段设置小利益点——每15秒给一个'值得看完'的理由")

        score = max(0, min(100, score))
        severity = "high" if score >= 70 else "medium" if score >= 40 else "low"

        result = {
            "metric": "完播率",
            "value": completion,
            "score": score,
            "severity": severity,
            "factors": factors,
            "recommendations": recommendations,
        }

        if self.llm:
            result["llm_explanation"] = self._llm_enhance(video, result,
                                                           "completion_rate")

        return result

    # ================================================================
    # 收藏率归因
    # ================================================================

    def attribution_favorite_rate(self, video: dict,
                                   signal_profile: Optional[dict] = None) -> dict:
        """
        分析收藏率。

        Factors:
          - 提供认知但缺少可执行方法
          - 用户没有保存需求
          - 缺少框架/步骤/清单类内容
        """
        fav_rate = float(video.get("favorites", 0) or 0)
        plays = float(video.get("plays", 0) or 1)
        fav_ratio = fav_rate / max(plays, 1) * 100
        signals = signal_profile or {}

        factors = []
        recommendations = []
        score = 50

        # 规则1: 是否有方法论/框架信号？
        has_method = self._signal_detected(signals, "cognitive", "认知升级") or \
                     self._signal_detected(signals, "cognitive", "规则")
        if not has_method:
            factors.append({
                "factor": "缺少可收藏的方法论",
                "detail": "用户觉得内容有道理但不需要保存——因为无法反复执行",
                "impact": "high",
            })
            score += 20
            recommendations.append("提供可反复查看的框架/步骤/清单——收藏率提升的关键")

        # 规则2: 是否有利益信号？
        has_benefit = any(
            self._signal_detected(signals, "benefit", sig)
            for sig in ["避坑", "省钱", "赚钱"]
        )
        if has_benefit:
            score -= 10  # 正向
        else:
            factors.append({
                "factor": "缺少收藏动机",
                "detail": "用户看完即走，没有'以后用得上'的动机",
                "impact": "medium",
            })
            score += 10
            recommendations.append("加入可保存的实用信息——清单、话术、公式")

        score = max(0, min(100, score))
        severity = "high" if score >= 70 else "medium" if score >= 40 else "low"

        result = {
            "metric": "收藏率",
            "value": round(fav_ratio, 2),
            "score": score,
            "severity": severity,
            "factors": factors,
            "recommendations": recommendations,
        }

        if self.llm:
            result["llm_explanation"] = self._llm_enhance(video, result,
                                                           "favorite_rate")

        return result

    # ================================================================
    # 涨粉率归因
    # ================================================================

    def attribution_follow_rate(self, video: dict,
                                 signal_profile: Optional[dict] = None) -> dict:
        """
        分析涨粉率。

        Factors:
          - 身份认同强度
          - 价值观输出
          - 个人品牌一致性
          - 社区行动召唤
        """
        follows = float(video.get("follows", 0) or
                        video.get("follower_growth", 0) or 0)
        plays = float(video.get("plays", 0) or 1)
        follow_ratio = follows / max(plays, 1) * 100
        signals = signal_profile or {}

        factors = []
        recommendations = []
        score = 50

        # 规则1: 是否有身份认同信号？
        has_identity = any(
            self._signal_detected(signals, "identification", sig)
            for sig in ["打工人", "普通人", "创业者", "年轻人"]
        )
        if not has_identity:
            factors.append({
                "factor": "缺少身份认同感",
                "detail": "用户没有'这就是我的故事'的共鸣，不会因此关注",
                "impact": "high",
            })
            score += 15
            recommendations.append("建立群体身份——'我们打工人''这是每个普通人都面对的问题'")

        # 规则2: 是否有价值观输出？
        has_values = self._signal_detected(signals, "cognitive", "认知升级") or \
                     self._signal_detected(signals, "emotional", "身份焦虑")
        if not has_values:
            factors.append({
                "factor": "缺少价值观输出",
                "detail": "用户关注的核心动力是'这个人有我想成为的样子'——内容缺少价值立场",
                "impact": "high",
            })
            score += 15
            recommendations.append("结尾输出明确的价值观——让用户因为认同而关注")

        # 规则3: 是否有情绪共鸣？
        has_empathy = any(
            self._signal_detected(signals, "emotional", sig)
            for sig in ["财富焦虑", "职业焦虑", "阶层焦虑"]
        )
        if has_empathy:
            score -= 10  # 正向：情绪共鸣促进关注
        else:
            factors.append({
                "factor": "缺少情绪共鸣",
                "detail": "内容偏知识传递，缺少情感连接——用户记不住你是谁",
                "impact": "medium",
            })
            score += 10
            recommendations.append("在内容中加入个人故事或情感经历——让用户记住账号背后的人")

        score = max(0, min(100, score))
        severity = "high" if score >= 70 else "medium" if score >= 40 else "low"

        result = {
            "metric": "涨粉率",
            "value": round(follow_ratio, 4) if follow_ratio < 0.01 else round(follow_ratio, 2),
            "score": score,
            "severity": severity,
            "factors": factors,
            "recommendations": recommendations,
        }

        if self.llm:
            result["llm_explanation"] = self._llm_enhance(video, result,
                                                           "follow_rate")

        return result

    # ================================================================
    # 综合归因
    # ================================================================

    def full_attribution(self, video: dict,
                          signal_profile: Optional[dict] = None) -> dict:
        """
        全部4项归因 + 综合摘要。

        Args:
            video: 视频数据 dict
            signal_profile: 可选的信号检测结果

        Returns:
            {
                "dropoff": {...},
                "completion": {...},
                "favorite": {...},
                "follow": {...},
                "summary": "综合评估文本",
            }
        """
        results = {
            "dropoff": self.attribution_2s_dropoff(video, signal_profile),
            "completion": self.attribution_completion_rate(video, signal_profile),
            "favorite": self.attribution_favorite_rate(video, signal_profile),
            "follow": self.attribution_follow_rate(video, signal_profile),
        }

        # 生成综合摘要
        high_risk = [k for k, v in results.items() if v["severity"] == "high"]
        all_recommendations = []
        for k, v in results.items():
            all_recommendations.extend(v.get("recommendations", []))

        if high_risk:
            summary = f"发现{len(high_risk)}个高风险维度: "
            summary += "、".join(high_risk)
            summary += f"。建议优先处理: {all_recommendations[0] if all_recommendations else '无'}"
        else:
            summary = "整体表现中等偏上。"
            if all_recommendations:
                summary += f"优化建议: {all_recommendations[0]}"

        results["summary"] = summary
        return results

    # ================================================================
    # 内部方法
    # ================================================================

    @staticmethod
    def _signal_detected(signal_profile: dict, category: str,
                         signal_name: str) -> bool:
        """检查某个信号是否被检测到"""
        if not signal_profile:
            return False
        categories = signal_profile.get("categories", {}) if isinstance(
            signal_profile, dict) else {}
        cat_data = categories.get(category, {})
        if isinstance(cat_data, dict):
            return cat_data.get(signal_name, {}).get("count", 0) > 0
        return False

    def _llm_enhance(self, video: dict, result: dict,
                     metric: str) -> str:
        """LLM增强：生成自然语言解释"""
        if not self.llm:
            return ""

        system_prompt = """你是一个内容分析专家，请你根据归因分析结果，用自然语言写一段简短的分析和优化建议。
语言要具体、可执行。不要用"提高质量""继续优化"这类空话。控制在150字以内。"""

        user_prompt = f"""
视频标题: {video.get('title', '未知')}
指标: {result['metric']}
问题评分: {result['score']}/100
严重程度: {result['severity']}
检测到的问题: {[f['factor'] for f in result.get('factors', [])]}

请写出简洁的分析和改进建议。"""

        try:
            return self.llm(system_prompt, user_prompt)
        except Exception:
            return ""

    def _llm_enhance_dropoff(self, video: dict, result: dict) -> str:
        """专门的2秒跳出LLM解释——强调开头优化"""
        return self._llm_enhance(video, result, "dropoff")
