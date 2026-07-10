"""
ContentStructureAnalyzer — 内容结构分析服务

从关键词信号 → 内容结构/开场/模型/主题 六级学习体系。

分析维度:
  1. content_structure: 信息差结构、规则揭秘结构、身份代入结构、反常识结构、现象解释结构、利益冲突结构
  2. opening: 反常识开场、信息差开场、故事开场、提问开场、结论开场
  3. content_model: 结构组合模型（如"信息差+规则揭秘+案例"）
  4. topic: 主题分类（房地产、财政、货币、就业、认知升级...）
  5. audience: 观众兴趣（通过数据分析）
  6. strategy: 策略规则（通过 strategy_memory.json）

用法:
    analyzer = ContentStructureAnalyzer()
    result = analyzer.full_structure_analysis(videos)
    # result = {
    #   "content_structures": {"rankings": [...], "best": "...", ...},
    #   "openings": {"rankings": [...], "best": "...", ...},
    #   "content_models": {"self": [...], "competitors": {}},
    #   "topics": {"rankings": [...]},
    #   "signals": {...}  # 向后兼容的关键词信号
    # }
"""

import re
from collections import defaultdict
from typing import Optional
from datetime import datetime

# ================================================================
# 内容结构模式（6种核心结构）
# ================================================================

STRUCTURE_PATTERNS = {
    "信息差结构": {
        "keywords": ["你不知道", "真相是", "其实是", "本质是", "信息差", "内行人",
                      "没人告诉", "懂的都懂", "潜规则", "内部"],
        "patterns": [r"你以为.*其实", r"为什么.*却", r"秘密"],
        "examples": ["你以为房价上涨是市场行为，其实是财政行为"],
    },
    "规则揭秘结构": {
        "keywords": ["规则", "制度", "机制", "逻辑", "原理", "公式", "定律",
                      "算法", "法则", "效应", "本质"],
        "patterns": [r"每一个.*背后", r"为什么.*都", r"底层逻辑"],
        "examples": ["为什么每一个好政策背后都藏着一笔经济账"],
    },
    "身份代入结构": {
        "keywords": ["你有没有发现", "你是不是也", "普通人", "打工人", "每个人",
                      "你", "你的"],
        "patterns": [r"越.*越", r"为什么你", r"你有没有"],
        "examples": ["你有没有发现，越努力的人越难翻身"],
    },
    "反常识结构": {
        "keywords": ["反常识", "颠覆", "最大的敌人", "误区", "都错了",
                      "不是你想", "原来", "竟然", "没想到", "辟谣"],
        "patterns": [r"最大的.*不是", r"不是.*而是", r"其实你不", r"99%.*都"],
        "examples": ["穷人最大的敌人不是贫穷，而是勤奋"],
    },
    "现象解释结构": {
        "keywords": ["为什么", "怎么回事", "背后", "原因", "揭秘", "解析",
                      "真相", "解密"],
        "patterns": [r"为什么.*都", r".*背后.*秘密"],
        "examples": ["为什么很多城市负债累累，却还在拼命建项目"],
    },
    "利益冲突结构": {
        "keywords": ["希望", "博弈", "冲突", "利益", "矛盾", "对立",
                      "各怀鬼胎", "争夺", "竞争"],
        "patterns": [r".*希望.*更", r"矛盾", r"冲突"],
        "examples": ["开发商希望涨价，地方财政更希望涨价"],
    },
}

# ================================================================
# 开场模式（5种）
# ================================================================

OPENING_PATTERNS = {
    "反常识开场": {
        "keywords": ["其实", "大多数人", "都错了", "真相", "没想到",
                      "颠覆", "最大的"],
        "patterns": [r"其实.*都", r".*不是你以为"],
    },
    "信息差开场": {
        "keywords": ["你知道吗", "你不知道", "秘密", "真正决定",
                      "懂", "内部消息"],
        "patterns": [r"你知道.*吗", r"真正.*是什么"],
    },
    "故事开场": {
        "keywords": ["有一个人", "有一个", "年前", "曾经", "那时候",
                      "有个", "那年"],
        "patterns": [r".*年前.*", r"曾经有"],
    },
    "提问开场": {
        "keywords": ["为什么", "是什么", "怎么办", "如何", "怎么",
                      "凭什么"],
        "patterns": [r"为什么.*?", r"如何.*?"],
    },
    "结论开场": {
        "keywords": ["不是", "就是", "决定", "取决于", "答案是",
                      "关键在于"],
        "patterns": [r".*不是.*决定的", r".*取决于"],
    },
}

# ================================================================
# 主题分类
# ================================================================

TOPIC_PATTERNS = {
    "房地产": ["房价", "买房", "房贷", "租房", "楼市", "地产", "首付",
                "贷款买房", "租金", "房地产"],
    "财政": ["财政", "税收", "国债", "地方债", "赤字", "预算", "财政收入",
              "转移支付"],
    "货币": ["货币", "通胀", "通缩", "印钱", "降息", "加息", "M2",
              "利率", "汇率"],
    "就业": ["就业", "失业", "找工作", "裁员", "35岁", "内卷", "职场"],
    "消费": ["消费", "省钱", "物价", "购买力", "性价比", "薅羊毛"],
    "认知升级": ["认知", "格局", "思维", "底层逻辑", "认知升级", "心智"],
    "商业案例": ["商业", "商业模式", "创业", "企业", "公司", "老板"],
    "经济学": ["经济学", "经济", "市场", "供需", "资本", "投资", "理财"],
    "社会观察": ["社会", "阶层", "普通人", "打工人", "穷人", "富人"],
    "金融": ["金融", "股票", "基金", "银行", "投资", "理财", "资产"],
}

# ================================================================
# 内容模型（结构组合）
# ================================================================

CONTENT_MODELS = [
    {"name": "信息差 + 规则揭秘", "structures": ["信息差结构", "规则揭秘结构"]},
    {"name": "身份代入 + 反常识", "structures": ["身份代入结构", "反常识结构"]},
    {"name": "现象解释 + 数据支撑", "structures": ["现象解释结构"]},
    {"name": "利益冲突 + 信息差", "structures": ["利益冲突结构", "信息差结构"]},
    {"name": "反常识 + 规则揭秘", "structures": ["反常识结构", "规则揭秘结构"]},
    {"name": "提问 + 现象解释", "structures": ["现象解释结构"]},
]

# ================================================================
# 向后兼容的信号关键词
# ================================================================

EMOTIONAL_SIGNALS = {
    "财富焦虑": ["穷", "没钱", "买不起", "负债", "月光", "工资", "房贷", "车贷",
                 "贵", "涨价", "贬值", "赔钱", "亏", "消费降级", "降薪"],
    "职业焦虑": ["裁员", "35岁", "失业", "内卷", "被裁", "找工作", "面试", "职场"],
    "婚恋焦虑": ["单身", "相亲", "分手", "结婚", "彩礼", "离婚"],
    "阶层焦虑": ["阶层", "跨越", "出身", "底层", "翻身", "寒门", "县城"],
    "身份焦虑": ["身份", "标签", "认可", "尊重", "歧视", "面子", "精神内耗"],
}

COGNITIVE_SIGNALS = {
    "反常识": ["反常识", "颠覆", "真相", "骗局", "误区", "没想到", "揭秘"],
    "认知升级": ["认知", "格局", "思维", "层次", "本质", "底层逻辑"],
    "信息差": ["信息差", "你不知道", "内行", "秘密", "潜规则", "懂的都懂"],
    "内幕": ["内幕", "黑幕", "背后", "行业内", "爆料", "套路", "割韭菜"],
    "规则": ["规则", "制度", "机制", "原理", "逻辑", "公式", "定律", "算法"],
}

BENEFIT_SIGNALS = {
    "赚钱": ["赚钱", "搞钱", "副业", "收入", "变现", "被动收入", "财富自由"],
    "省钱": ["省钱", "省下", "优惠", "折扣", "薅羊毛", "白嫖", "免费"],
    "避坑": ["避坑", "别买", "别做", "上当", "踩坑", "陷阱", "风险"],
    "机会": ["机会", "风口", "趋势", "红利", "蓝海", "新赛道"],
    "风险": ["风险", "危机", "崩盘", "泡沫", "暴雷", "破产"],
}

IDENTIFICATION_SIGNALS = {
    "你": ["你", "你的", "你自己"],
    "普通人": ["普通人", "普通家庭", "平凡人", "老百姓", "平民"],
    "打工人": ["打工人", "社畜", "上班族", "牛马"],
    "创业者": ["创业者", "老板", "创业", "做生意"],
    "年轻人": ["年轻人", "后浪", "00后", "90后", "80后", "新手"],
}

ALL_SIGNAL_CATEGORIES = {
    "emotional": EMOTIONAL_SIGNALS,
    "cognitive": COGNITIVE_SIGNALS,
    "benefit": BENEFIT_SIGNALS,
    "identification": IDENTIFICATION_SIGNALS,
}

SIGNAL_CATEGORY_LABELS = {
    "emotional": "情绪信号",
    "cognitive": "认知信号",
    "benefit": "利益信号",
    "identification": "代入信号",
}


class ContentStructureAnalyzer:
    """
    内容结构分析服务（替换原 SignalDetector）

    六级学习体系：
      1. content_structure — 6种内容结构识别
      2. opening — 5种开场类型识别
      3. content_model — 结构组合模型
      4. topic — 主题分类
      5. audience — 观众数据
      6. strategy — 策略规则（通过 StrategyValidator）
    """

    # ================================================================
    # 第一层：内容结构学习
    # ================================================================

    def analyze_content_structures(self, videos: list[dict],
                                    metric: str = "plays") -> dict:
        """
        分析视频内容结构，输出结构排行榜。

        Returns:
            {
                "rankings": [
                    {"structure": "信息差结构", "sample_count": N, "avg_metric": X,
                     "titles": [...], "pct_better_than_average": X},
                    ...
                ],
                "best": "最高排名结构",
                "worst": "最低排名结构",
                "total_analyzed": N
            }
        """
        structure_stats = defaultdict(lambda: {
            "titles": [], "values": [], "count": 0, "total": 0.0
        })
        overall_total = 0.0
        overall_count = 0

        for v in videos:
            title = v.get("title", "") or ""
            value = float(v.get(metric, 0) or 0)
            overall_total += value
            overall_count += 1

            structures = self._detect_structures(title)
            for struct_name in structures:
                structure_stats[struct_name]["titles"].append(title)
                structure_stats[struct_name]["values"].append(value)
                structure_stats[struct_name]["total"] += value
                structure_stats[struct_name]["count"] += 1

        overall_avg = overall_total / max(overall_count, 1)

        rankings = []
        for name, data in structure_stats.items():
            if data["count"] < 1:
                continue
            avg_val = round(data["total"] / data["count"], 1)
            pct_diff = round((avg_val - overall_avg) / max(overall_avg, 1) * 100, 1)
            rankings.append({
                "structure": name,
                "sample_count": data["count"],
                "avg_metric": avg_val,
                "overall_avg": round(overall_avg, 1),
                "pct_better_than_average": pct_diff,
                "confidence": round(min(1.0, data["count"] / 20), 2),
                "sample_titles": data["titles"][:3],
            })

        rankings.sort(key=lambda x: -x["avg_metric"])

        return {
            "rankings": rankings,
            "best": rankings[0]["structure"] if rankings else "",
            "best_sample_count": rankings[0]["sample_count"] if rankings else 0,
            "worst": rankings[-1]["structure"] if rankings else "",
            "worst_avg": rankings[-1]["avg_metric"] if rankings else 0,
            "total_analyzed": overall_count,
        }

    def _detect_structures(self, title: str) -> list[str]:
        """检测单条标题命中的内容结构"""
        detected = []
        for struct_name, patterns in STRUCTURE_PATTERNS.items():
            # 关键词匹配
            for kw in patterns["keywords"]:
                if kw in title:
                    detected.append(struct_name)
                    break
            else:
                # 关键词未命中，尝试正则
                for p in patterns["patterns"]:
                    if re.search(p, title):
                        detected.append(struct_name)
                        break
        return detected

    # ================================================================
    # 第二层：开场学习
    # ================================================================

    def analyze_openings(self, videos: list[dict],
                          metric: str = "plays") -> dict:
        """
        分析视频开场/前5秒类型，输出开场排行榜。

        Returns:
            {
                "rankings": [
                    {"opening": "反常识开场", "sample_count": N, "avg_metric": X,
                     "pct_better_than_average": X, "sample_titles": [...]},
                    ...
                ],
                "best": "最高排名开场"
            }
        """
        opening_stats = defaultdict(lambda: {
            "titles": [], "values": [], "count": 0, "total": 0.0
        })
        overall_total = 0.0
        overall_count = 0

        for v in videos:
            title = v.get("title", "") or ""
            value = float(v.get(metric, 0) or 0)
            overall_total += value
            overall_count += 1

            opening = self._detect_opening(title)
            if opening:
                opening_stats[opening]["titles"].append(title)
                opening_stats[opening]["values"].append(value)
                opening_stats[opening]["total"] += value
                opening_stats[opening]["count"] += 1

        overall_avg = overall_total / max(overall_count, 1)

        rankings = []
        for name, data in opening_stats.items():
            if data["count"] < 1:
                continue
            avg_val = round(data["total"] / data["count"], 1)
            pct_diff = round((avg_val - overall_avg) / max(overall_avg, 1) * 100, 1)
            rankings.append({
                "opening": name,
                "sample_count": data["count"],
                "avg_metric": avg_val,
                "pct_better_than_average": pct_diff,
                "confidence": round(min(1.0, data["count"] / 20), 2),
                "sample_titles": data["titles"][:3],
            })

        rankings.sort(key=lambda x: -x["avg_metric"])

        return {
            "rankings": rankings,
            "best": rankings[0]["opening"] if rankings else "",
        }

    def _detect_opening(self, title: str) -> Optional[str]:
        """检测单条标题的开场类型"""
        for open_name, patterns in OPENING_PATTERNS.items():
            for kw in patterns["keywords"]:
                if kw in title:
                    return open_name
            for p in patterns["patterns"]:
                if re.search(p, title):
                    return open_name
        return None

    # ================================================================
    # 第三层：内容模型学习
    # ================================================================

    def analyze_content_models(self, videos: list[dict],
                                metric: str = "plays") -> dict:
        """
        分析内容模型（结构组合），输出模型排行榜。

        Returns:
            {
                "self": [
                    {"model": "信息差+规则揭秘", "sample_count": N, "avg_metric": X, ...},
                    ...
                ],
                "competitors": {}  # 竞品数据，由外部注入
            }
        """
        model_stats = defaultdict(lambda: {
            "titles": [], "values": [], "count": 0, "total": 0.0
        })
        overall_total = 0.0
        overall_count = 0

        for v in videos:
            title = v.get("title", "") or ""
            value = float(v.get(metric, 0) or 0)
            overall_total += value
            overall_count += 1

            structures = self._detect_structures(title)
            if not structures:
                continue

            # 检查是否匹配预定义模型
            matched_models = self._match_models(structures)
            for model_name in matched_models:
                model_stats[model_name]["titles"].append(title)
                model_stats[model_name]["values"].append(value)
                model_stats[model_name]["total"] += value
                model_stats[model_name]["count"] += 1

        overall_avg = overall_total / max(overall_count, 1)

        rankings = []
        for name, data in model_stats.items():
            if data["count"] < 1:
                continue
            avg_val = round(data["total"] / data["count"], 1)
            pct_diff = round((avg_val - overall_avg) / max(overall_avg, 1) * 100, 1)
            rankings.append({
                "model": name,
                "sample_count": data["count"],
                "avg_metric": avg_val,
                "pct_better_than_average": pct_diff,
                "confidence": round(min(1.0, data["count"] / 20), 2),
                "sample_titles": data["titles"][:3],
            })

        rankings.sort(key=lambda x: -x["avg_metric"])
        return {"self": rankings, "competitors": {}}

    def _match_models(self, structures: list[str]) -> list[str]:
        """检测匹配哪些预定义内容模型"""
        matched = []
        struct_set = set(structures)
        for model in CONTENT_MODELS:
            model_structs = set(model["structures"])
            if model_structs.issubset(struct_set):
                matched.append(model["name"])
        return matched

    # ================================================================
    # 第四层：主题学习
    # ================================================================

    def analyze_topics(self, videos: list[dict],
                       metric: str = "plays") -> dict:
        """
        分析视频主题，输出主题排行榜。

        Returns:
            {
                "rankings": [
                    {"topic": "房地产", "sample_count": N, "avg_metric": X, ...},
                    ...
                ]
            }
        """
        topic_stats = defaultdict(lambda: {
            "titles": [], "values": [], "count": 0, "total": 0.0
        })

        for v in videos:
            title = v.get("title", "") or ""
            value = float(v.get(metric, 0) or 0)

            topics = self._detect_topics(title)
            for topic_name in topics:
                topic_stats[topic_name]["titles"].append(title)
                topic_stats[topic_name]["values"].append(value)
                topic_stats[topic_name]["total"] += value
                topic_stats[topic_name]["count"] += 1

        rankings = []
        for name, data in topic_stats.items():
            if data["count"] < 1:
                continue
            avg_val = round(data["total"] / data["count"], 1)
            rankings.append({
                "topic": name,
                "sample_count": data["count"],
                "avg_metric": avg_val,
                "confidence": round(min(1.0, data["count"] / 20), 2),
                "sample_titles": data["titles"][:3],
            })

        rankings.sort(key=lambda x: -x["avg_metric"])
        return {"rankings": rankings}

    def _detect_topics(self, title: str) -> list[str]:
        """检测单条标题的主题分类"""
        detected = []
        for topic_name, keywords in TOPIC_PATTERNS.items():
            for kw in keywords:
                if kw in title:
                    detected.append(topic_name)
                    break
        return detected

    # ================================================================
    # 第五层：观众学习（数据需外部传入抖音观众分析数据）
    # ================================================================

    def build_audience_memory(self, audience_data: dict) -> dict:
        """
        从抖音观众分析数据构建 Audience Memory。

        Args:
            audience_data: {
                "interests": ["听泉赏宝", "资本论", "直男财经", ...],
                "similar_authors": ["艾维奇Vic", "鹤老师", ...],
                "search_keywords": ["房地产真相", "普通人怎么赚钱", ...]
            }

        Returns:
            {
                "interests": [...],
                "similar_authors": [...],
                "search_keywords": [...],
            }
        """
        return {
            "interests": audience_data.get("interests", []),
            "similar_authors": audience_data.get("similar_authors", []),
            "search_keywords": audience_data.get("search_keywords", []),
            "updated_at": datetime.now().isoformat(),
        }

    # ================================================================
    # 综合全分析
    # ================================================================

    def full_structure_analysis(self, videos: list[dict]) -> dict:
        """
        完整六级分析（不含策略层，策略由 StrategyValidator 处理）。

        Returns:
            {
                "content_structures": {...},
                "openings": {...},
                "content_models": {"self": [...], "competitors": {}},
                "topics": {...},
                "signals": {...},  # 向后兼容
                "total_videos": N
            }
        """
        structures = self.analyze_content_structures(videos, "plays")
        openings = self.analyze_openings(videos, "plays")
        models = self.analyze_content_models(videos, "plays")
        topics = self.analyze_topics(videos, "plays")
        signals = self.analyze_signals(videos)

        return {
            "content_structures": structures,
            "openings": openings,
            "content_models": models,
            "topics": topics,
            "signals": signals,
            "total_videos": len(videos),
        }

    # ================================================================
    # 更新 self_growth_memory（五层结构）
    # ================================================================

    def update_self_growth_memory(self, memory: dict,
                                   analysis_result: dict) -> dict:
        """
        将完整分析结果合并到 self_growth_memory（五层结构）。

        Args:
            memory: 现有的 self_growth_memory dict
            analysis_result: full_structure_analysis() 的返回值

        Returns:
            更新后的 memory dict
        """
        from copy import deepcopy
        memory = deepcopy(memory)
        memory["last_updated"] = datetime.now().isoformat()
        memory["total_videos_analyzed"] += analysis_result["total_videos"]

        # 更新 content_structures
        cs = analysis_result.get("content_structures", {})
        rankings = cs.get("rankings", [])
        if rankings:
            existing_rankings = memory["content_structures"]["rankings"]
            seen = {r["structure"] for r in existing_rankings}
            for r in rankings:
                if r["structure"] not in seen:
                    existing_rankings.append(r)
                    seen.add(r["structure"])
                else:
                    for er in existing_rankings:
                        if er["structure"] == r["structure"]:
                            er.update(r)
                            break
            existing_rankings.sort(key=lambda x: -x.get("avg_metric", 0))
            memory["content_structures"]["rankings"] = existing_rankings
            memory["content_structures"]["best"] = cs.get("best", "")
            memory["content_structures"]["worst"] = cs.get("worst", "")

        # 更新 openings
        op = analysis_result.get("openings", {})
        rankings = op.get("rankings", [])
        if rankings:
            existing_rankings = memory["openings"]["rankings"]
            seen = {r["opening"] for r in existing_rankings}
            for r in rankings:
                if r["opening"] not in seen:
                    existing_rankings.append(r)
                    seen.add(r["opening"])
                else:
                    for er in existing_rankings:
                        if er["opening"] == r["opening"]:
                            er.update(r)
                            break
            existing_rankings.sort(key=lambda x: -x.get("avg_metric", 0))
            memory["openings"]["rankings"] = existing_rankings
            memory["openings"]["best"] = op.get("best", "")

        # 更新 content_models
        cm = analysis_result.get("content_models", {}).get("self", [])
        if cm:
            existing_models = memory["content_models"]["self"]
            seen = {m["model"] for m in existing_models}
            for m in cm:
                if m["model"] not in seen:
                    existing_models.append(m)
                    seen.add(m["model"])
                else:
                    for em in existing_models:
                        if em["model"] == m["model"]:
                            em.update(m)
                            break
            existing_models.sort(key=lambda x: -x.get("avg_metric", 0))
            memory["content_models"]["self"] = existing_models

        # 更新 topics
        tp = analysis_result.get("topics", {})
        rankings = tp.get("rankings", [])
        if rankings:
            existing_rankings = memory["topics"]["rankings"]
            seen = {r["topic"] for r in existing_rankings}
            for r in rankings:
                if r["topic"] not in seen:
                    existing_rankings.append(r)
                    seen.add(r["topic"])
                else:
                    for er in existing_rankings:
                        if er["topic"] == r["topic"]:
                            er.update(r)
                            break
            existing_rankings.sort(key=lambda x: -x.get("avg_metric", 0))
            memory["topics"]["rankings"] = existing_rankings

        return memory

    # ================================================================
    # 向后兼容的关键词信号检测（原 SignalDetector 功能）
    # ================================================================

    def analyze_signals(self, videos: list[dict]) -> dict:
        """向后兼容：关键词级别的信号检测"""
        categories = self._init_result_categories()
        total_with_signals = 0
        multi_signal = 0

        for v in videos:
            title = v.get("title", "") or ""
            if not title:
                continue

            signals_detected = self._detect_signals_in_title(title)
            signal_count = len(set(signals_detected))

            for cat_name, sig_name in signals_detected:
                categories[cat_name][sig_name]["count"] += 1
                categories[cat_name][sig_name]["titles"].append(title)

                for metric in ["plays", "likes", "favorites", "comments",
                               "shares", "completion_rate", "follows"]:
                    val = v.get(metric, 0)
                    if val:
                        entry = categories[cat_name][sig_name]
                        if "total_" + metric not in entry:
                            entry["total_" + metric] = 0.0
                        entry["total_" + metric] += float(val)

            if signal_count > 0:
                total_with_signals += 1
            if signal_count > 1:
                multi_signal += 1

        for cat_name in categories:
            for sig_name in categories[cat_name]:
                entry = categories[cat_name][sig_name]
                c = entry["count"]
                if c > 0:
                    for metric in ["plays", "likes", "favorites", "comments",
                                   "shares", "completion_rate", "follows"]:
                        key = "total_" + metric
                        if key in entry:
                            entry["avg_" + metric] = round(entry[key] / c, 1)
                            del entry[key]

        summary = self._build_summary(categories)

        return {
            "categories": categories,
            "summary": summary,
            "total_videos": len(videos),
            "videos_with_signals": total_with_signals,
            "multi_signal_videos": multi_signal,
        }

    def find_high_performing_patterns(self, videos: list[dict],
                                       metric: str = "plays",
                                       top_n: int = 5) -> list[dict]:
        """向后兼容：关键词级别高表现信号"""
        return self._find_patterns(videos, metric, top_n=top_n, reverse=True)

    def find_low_performing_patterns(self, videos: list[dict],
                                      metric: str = "plays",
                                      top_n: int = 5) -> list[dict]:
        """向后兼容：关键词级别低表现信号"""
        return self._find_patterns(videos, metric, top_n=top_n, reverse=False)

    def compare_with_competitors(self, self_signals: dict,
                                  competitor_signals: dict) -> dict:
        """向后兼容：信号对比"""
        return self._compare_signals(self_signals, competitor_signals)

    # ================================================================
    # 内部方法（向后兼容）
    # ================================================================

    def _detect_signals_in_title(self, title: str) -> list[tuple[str, str]]:
        """向后兼容：关键词信号检测"""
        detected = []
        for cat_name, signals in ALL_SIGNAL_CATEGORIES.items():
            for sig_name, keywords in signals.items():
                for kw in keywords:
                    if kw in title:
                        detected.append((cat_name, sig_name))
                        break
        return detected

    def _find_patterns(self, videos: list[dict], metric: str,
                       top_n: int, reverse: bool) -> list[dict]:
        """向后兼容：通用模式查找"""
        signal_metrics = defaultdict(lambda: {
            "titles": [], "values": [], "total": 0.0, "count": 0
        })

        for v in videos:
            title = v.get("title", "") or ""
            if not title:
                continue
            val = float(v.get(metric, 0) or 0)

            signals = self._detect_signals_in_title(title)
            seen = set()
            for cat_name, sig_name in signals:
                key = f"{cat_name}/{sig_name}"
                if key in seen:
                    continue
                seen.add(key)
                signal_metrics[key]["titles"].append(title)
                signal_metrics[key]["values"].append(val)
                signal_metrics[key]["total"] += val
                signal_metrics[key]["count"] += 1

        results = []
        for key, data in signal_metrics.items():
            if data["count"] < 1:
                continue
            avg_val = round(data["total"] / data["count"], 1)
            cat_name, sig_name = key.split("/", 1)
            confidence = min(1.0, data["count"] / 10)
            results.append({
                "signal_category": cat_name,
                "signal_category_label": SIGNAL_CATEGORY_LABELS.get(cat_name, cat_name),
                "signal_name": sig_name,
                "avg_metric": avg_val,
                "sample_count": data["count"],
                "confidence": round(confidence, 2),
                "sample_titles": data["titles"][:5],
            })

        results.sort(key=lambda x: x["avg_metric"], reverse=reverse)
        return results[:top_n]

    def _init_result_categories(self) -> dict:
        return {
            cat: {sig: {"count": 0, "titles": []}
                  for sig in signals}
            for cat, signals in ALL_SIGNAL_CATEGORIES.items()
        }

    def _build_summary(self, categories: dict) -> dict:
        summary = {}
        for cat_name, signals in categories.items():
            total = sum(s["count"] for s in signals.values())
            top_signal = max(signals.items(), key=lambda x: x[1]["count"]) if signals else ("", {})
            summary[cat_name] = {
                "label": SIGNAL_CATEGORY_LABELS.get(cat_name, cat_name),
                "total_detected": total,
                "top_signal": top_signal[0] if top_signal[0] else "",
                "top_signal_count": top_signal[1]["count"] if top_signal[1] else 0,
            }
        return summary

    def _flatten_signal_avgs(self, signal_data: dict) -> dict:
        result = {}
        for cat_name, signals in signal_data.get("categories", {}).items():
            if not isinstance(signals, dict):
                continue
            for sig_name, data in signals.items():
                if isinstance(data, dict) and data.get("count", 0) > 0:
                    avg = data.get("avg_plays", 0) or 0
                    result[f"{cat_name}/{sig_name}"] = avg
        return result

    def _compare_signals(self, self_signals: dict,
                          competitor_signals: dict) -> dict:
        gaps, advantages, overlaps = [], [], []
        self_sigs = self._flatten_signal_avgs(self_signals)
        comp_sigs = self._flatten_signal_avgs(competitor_signals)
        all_signals = set(list(self_sigs.keys()) + list(comp_sigs.keys()))

        for sig in sorted(all_signals):
            sv = self_sigs.get(sig, 0)
            cv = comp_sigs.get(sig, 0)
            if sv == 0 and cv == 0:
                continue
            entry = {"signal": sig, "self_avg": sv, "competitor_avg": cv, "gap": sv - cv}
            if sv > 0 and cv > 0:
                if sv > cv * 1.2:
                    advantages.append(entry)
                elif cv > sv * 1.2:
                    gaps.append(entry)
                else:
                    overlaps.append(entry)
            elif sv > 0 and cv == 0:
                advantages.append(entry)
            elif cv > 0 and sv == 0:
                gaps.append(entry)

        return {
            "gaps": sorted(gaps, key=lambda x: -x["gap"])[:10],
            "advantages": sorted(advantages, key=lambda x: -x["gap"])[:10],
            "overlaps": overlaps[:10],
        }
