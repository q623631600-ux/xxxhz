"""
抖音数据分析服务 — 封装 undoom-douyin-data-analysis 核心逻辑
支持两种数据来源：
  1. 在线采集：通过 DrissionPage 自动搜索抖音
  2. 离线导入：通过 Excel/CSV 上传，支持抖音创作者后台导出格式
"""
import json
import logging
from datetime import datetime
from typing import Optional
from collections import Counter
import jieba
import re

logger = logging.getLogger("douyin-analyzer")

# ─── 导入 DrissionPage（可选） ─────────────────────────────
try:
    from DrissionPage import ChromiumPage
    DRISSION_AVAILABLE = True
except ImportError:
    DRISSION_AVAILABLE = False
    logger.warning("DrissionPage 未安装，在线搜索不可用")


def _parse_num(val) -> float:
    """将各种数字格式转为 float。支持 '1.2万'、'1,200'、'85.2%' 等"""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(',', '').replace(' ', '')
    if not s:
        return 0.0
    # 百分比 → 小数
    if s.endswith('%'):
        return float(s.replace('%', '')) / 100.0
    # 万
    if '万' in s:
        return float(s.replace('万', '')) * 10000
    try:
        return float(s)
    except ValueError:
        return 0.0


def _format_num(num) -> str:
    """数字转显示格式"""
    if isinstance(num, str):
        return num
    if num >= 10000:
        return f"{num/10000:.1f}万"
    return str(int(num))


def _fmt_large(num: int) -> str:
    if num >= 10000:
        return f"{num/10000:.1f}万"
    return str(num)


class DouyinAnalyzer:
    """抖音数据分析器"""

    # 抖音创作者后台典型导出列名映射
    COLUMN_MAP = {
        # 标题
        '标题': 'title', 'title': 'title', '视频标题': 'title', '作品标题': 'title',
        '视频名称': 'title', '作品名称': 'title',
        # 作者
        # 作者
        '作者': 'author', 'author': 'author', '博主': 'author', '发布者': 'author', '昵称': 'author',
        # 播放
        '播放': 'plays', '播放量': 'plays', 'plays': 'plays', 'play': 'plays', 'play_count': 'plays',
        # 点赞
        '点赞': 'likes', '点赞数': 'likes', 'likes': 'likes', 'like': 'likes', 'digg_count': 'likes',
        # 评论
        '评论': 'comments', '评论数': 'comments', 'comments': 'comments', 'comment': 'comments', 'comment_count': 'comments',
        # 分享
        '分享': 'shares', '分享数': 'shares', 'shares': 'shares', 'share': 'shares', 'share_count': 'shares',
        # 收藏
        '收藏': 'favorites', '收藏数': 'favorites', 'favorites': 'favorites', 'favorite': 'favorites',
        'favorite_count': 'favorites', '收藏量': 'favorites',
        # 完播率
        '完播率': 'completion_rate', '完整播放率': 'completion_rate', 'completion_rate': 'completion_rate',
        # 平均播放时长（秒）
        '平均播放时长': 'avg_play_duration', '平均观看时长': 'avg_play_duration', 'avg_play_duration': 'avg_play_duration',
        '平均播放时长(秒)': 'avg_play_duration',
        # 3秒完播率 / 5秒完播率
        '3秒完播率': 'comp_3s', '3s完播率': 'comp_3s', 'comp_3s': 'comp_3s',
        '5秒完播率': 'comp_5s', '5s完播率': 'comp_5s', 'comp_5s': 'comp_5s',
        # 粉丝播放占比
        '粉丝播放占比': 'fan_play_ratio', '粉丝播放': 'fan_play_ratio', 'fan_play_ratio': 'fan_play_ratio',
        '粉丝占比': 'fan_play_ratio',
        # 跳出率
        '跳出率': 'drop_off_rate', '2s跳出率': 'drop_off_rate', '2秒跳出率': 'drop_off_rate',
        '流失率': 'drop_off_rate', 'drop_off_rate': 'drop_off_rate',
        # 点击率
        '点击率': 'ctr', '条均点击率': 'ctr', 'ctr': 'ctr',
        # 粉丝增长
        '粉丝增长': 'follower_growth', '涨粉': 'follower_growth', 'follower_growth': 'follower_growth',
        # 主页访问
        '主页访问': 'profile_visits', '主页访问量': 'profile_visits', 'profile_visits': 'profile_visits',
        # 发布时间
        '发布时间': 'publish_time', '时间': 'publish_time', '发布日期': 'publish_time',
        'publish_time': 'publish_time', 'create_time': 'publish_time',
        # 抖音数据通/创作者服务中心汇总导出列
        '条均5s完播率': 'comp_5s', '条均2s跳出率': 'drop_off_rate',
        '条均播放时长': 'avg_play_duration', '条均点赞数': 'likes',
        '条均评论量': 'comments', '条均分享量': 'shares',
        '播放量中位数': 'plays_median', '周期内投稿量': 'total_posts',
        # 链接
        '链接': 'video_link', 'url': 'video_link', 'video_link': 'video_link',
        # 视频时长
        '视频时长': 'video_duration', '时长': 'video_duration', 'video_duration': 'video_duration',
        'duration': 'video_duration',
        # 互动率（可计算）
        '互动率': 'engagement_rate', 'engagement_rate': 'engagement_rate',
    }

    # 需要解析为数值的字段
    NUMERIC_FIELDS = [
        'likes', 'comments', 'shares', 'favorites', 'plays',
        'completion_rate', 'avg_play_duration', 'comp_3s', 'comp_5s',
        'fan_play_ratio', 'drop_off_rate', 'follower_growth', 'profile_visits',
        'video_duration', 'engagement_rate',
    ]

    def __init__(self):
        self.videos = []
        self.users = []
        self.page = None

    # ================================================================
    # 数据采集（在线模式，需 DrissionPage + Chrome）
    # ================================================================

    def search_videos(self, keyword: str, scroll_count: int = 8, delay: float = 1.5) -> list[dict]:
        """搜索抖音视频"""
        if not DRISSION_AVAILABLE:
            raise RuntimeError("DrissionPage 未安装，无法在线搜索。请先用上传文件方式。")

        from urllib.parse import quote
        from bs4 import BeautifulSoup
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._async_search_videos(keyword, scroll_count, delay))
        finally:
            loop.close()

    async def _async_search_videos(self, keyword: str, scroll_count: int, delay: float) -> list[dict]:
        """异步搜索抖音视频"""
        new_data = []
        try:
            if not self.page:
                self.page = ChromiumPage()
                await asyncio.sleep(1.5)

            from urllib.parse import quote
            search_url = f"https://www.douyin.com/search/{quote(keyword)}?source=normal_search&type=video"
            logger.info(f"搜索抖音视频: {keyword}")
            self.page.get(search_url)
            await asyncio.sleep(3)

            last_height = self.page.run_js("return document.body.scrollHeight")
            for i in range(scroll_count):
                self.page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(delay)

                new_height = self.page.run_js("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

                page_source = self.page.html
                soup = BeautifulSoup(page_source, 'html.parser')
                batch = self._extract_video_items(soup)
                for d in batch:
                    if d not in new_data:
                        new_data.append(d)

                logger.info(f"采集进度 {i+1}/{scroll_count}，累计 {len(new_data)} 条")

            self.videos.extend(new_data)
        except Exception as e:
            logger.error(f"搜索失败: {e}")
            raise
        finally:
            try:
                if self.page:
                    self.page.quit()
                    self.page = None
            except Exception:
                pass

        return new_data

    # ================================================================
    # 从上传文件导入数据
    # ================================================================

    def load_from_file(self, filepath: str) -> int:
        """从 Excel/CSV 加载数据。自动识别抖音创作者后台导出格式。"""
        import pandas as pd
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath, encoding='utf-8-sig')
        else:
            df = pd.read_excel(filepath)

        # 统一列名映射
        df.rename(columns=lambda c: self.COLUMN_MAP.get(str(c).strip(), c), inplace=True)

        records = df.to_dict(orient='records')
        for r in records:
            r['collected_at'] = datetime.now().isoformat()
            # 解析数字字段
            for k in self.NUMERIC_FIELDS:
                if k in r:
                    r[k] = _parse_num(r[k])

        self.videos.extend(records)
        return len(records)

    # ================================================================
    # 数据分析
    # ================================================================

    def analyze_interaction(self) -> dict:
        """分析互动数据（点赞/评论/分享/收藏）"""
        if not self.videos:
            return {"error": "没有数据可分析"}

        def get_vals(field):
            return [v.get(field, 0) for v in self.videos if isinstance(v.get(field), (int, float)) and v.get(field, 0) > 0]

        likes = get_vals('likes')
        comments = get_vals('comments')
        shares = get_vals('shares')
        favorites = get_vals('favorites')
        plays = get_vals('plays')

        def stats(arr):
            if not arr:
                return None
            total = sum(arr)
            return {
                "total": _format_num(total),
                "avg": _format_num(int(total / len(arr))),
                "max": _format_num(max(arr)),
                "min": _format_num(min(arr)),
                "raw_avg": int(total / len(arr)),
            }

        result = {"total_videos": len(self.videos)}

        if likes:
            result["likes"] = stats(likes)
            # 点赞分布
            result["likes_distribution"] = self._build_distribution(likes,
                [(0, 100), (101, 1000), (1001, 10000), (10001, 100000), (100001, 999999999)],
                lambda s, e: f"{s}-{e}" if e < 999999999 else f"{s}+")

        if comments:
            result["comments"] = stats(comments)

        if shares:
            result["shares"] = stats(shares)

        if favorites:
            result["favorites"] = stats(favorites)

        if plays:
            result["plays"] = stats(plays)

        # 互动率 = (点赞+评论+分享+收藏) / 播放量
        if plays and likes:
            ratios = []
            for v in self.videos:
                p = v.get('plays', 0)
                if isinstance(p, (int, float)) and p > 0:
                    total_int = sum(v.get(k, 0) for k in ['likes', 'comments', 'shares', 'favorites']
                                    if isinstance(v.get(k), (int, float)))
                    if total_int > 0:
                        ratios.append(total_int / p)
            if ratios:
                result["engagement_rate"] = {
                    "avg": f"{sum(ratios)/len(ratios)*100:.1f}%",
                    "max": f"{max(ratios)*100:.1f}%",
                    "min": f"{min(ratios)*100:.1f}%",
                }

        return result

    def analyze_content_length(self) -> dict:
        """分析标题长度"""
        if not self.videos:
            return {"error": "没有数据可分析"}

        lengths = [len(v.get('title', '')) for v in self.videos if v.get('title')]
        if not lengths:
            return {"error": "没有有效标题"}

        avg = sum(lengths) / len(lengths)
        mx = max(lengths)
        mn = min(lengths)

        ranges = [(0, 10), (11, 20), (21, 30), (31, 50), (51, 100), (101, 999)]
        distribution = []
        for start, end in ranges:
            count = sum(1 for x in lengths if start <= x <= end)
            label = f"{start}-{end}字" if end < 999 else f"{start}字以上"
            distribution.append({"label": label, "count": count, "pct": round(count / len(lengths) * 100, 1)})

        return {
            "total": len(lengths),
            "avg": round(avg, 1),
            "max": mx,
            "min": mn,
            "distribution": distribution,
        }

    def analyze_keywords(self, top_n: int = 50) -> dict:
        """提取高频关键词"""
        if not self.videos:
            return {"error": "没有数据可分析"}

        all_text = ' '.join(v.get('title', '') for v in self.videos if v.get('title'))
        if not all_text.strip():
            return {"error": "没有有效文本"}

        stop_words = {
            '的', '了', '是', '在', '我', '有', '和', '就', '都', '而', '及', '与',
            '着', '或', '等', '为', '一个', '没有', '这个', '那个', '但是', '而且',
            '只是', '不过', '这样', '一样', '一直', '一些', '这', '那', '也', '你',
            '我们', '他们', '它们', '把', '被', '让', '向', '往', '但', '去', '又',
            '能', '好', '给', '到', '看', '想', '要', '会', '多', '这些', '那些',
            '什么', '怎么', '如何', '为什么', '可以', '因为', '所以', '应该', '可能',
            '不', '是', '的', '了', '在', '有', '和', '就', '都', '而', '也',
            '上', '下', '大', '小', '中', '很', '用', '还', '对', '做', '其',
        }

        words = [w for w in jieba.cut(all_text) if len(w) > 1 and w not in stop_words]
        if not words:
            return {"error": "分词后无有效词汇"}

        counter = Counter(words)
        total_words = len(words)
        top_words = []
        for rank, (word, count) in enumerate(counter.most_common(top_n), 1):
            top_words.append({
                "rank": rank,
                "word": word,
                "count": count,
                "frequency": round(count / total_words * 100, 2),
            })

        return {
            "total_videos": len(self.videos),
            "total_words": total_words,
            "unique_words": len(counter),
            "keywords": top_words,
        }

    def analyze_completion(self) -> dict:
        """分析完播率数据（优先用整体完播率，其次用5秒完播率）"""
        rates = [v.get('completion_rate') for v in self.videos
                 if isinstance(v.get('completion_rate'), (int, float)) and v.get('completion_rate', 0) > 0]
        using_5s = False
        if not rates:
            # 没有整体完播率时，用5秒完播率作为参考
            rates = [v.get('comp_5s') for v in self.videos
                     if isinstance(v.get('comp_5s'), (int, float)) and v.get('comp_5s', 0) > 0]
            if rates:
                using_5s = True
            else:
                return {"error": "没有完播率数据。请确认导出数据包含「完播率」或「5s完播率」列。"}

        avg = sum(rates) / len(rates) * 100
        mx = max(rates) * 100
        mn = min(rates) * 100

        ranges = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 50), (50, 100)]
        distribution = []
        for start, end in ranges:
            count = sum(1 for r in rates if start <= r * 100 <= end)
            label = f"{start}-{end}%" if end < 100 else f"{start}%+"
            distribution.append({"label": label, "count": count})

        # 3秒/5秒完播率
        comp_3s = [v.get('comp_3s') for v in self.videos
                   if isinstance(v.get('comp_3s'), (int, float)) and v.get('comp_3s', 0) > 0]
        comp_5s = [v.get('comp_5s') for v in self.videos
                   if isinstance(v.get('comp_5s'), (int, float)) and v.get('comp_5s', 0) > 0]

        result = {
            "avg": round(avg, 1),
            "max": round(mx, 1),
            "min": round(mn, 1),
            "count": len(rates),
            "distribution": distribution,
            "has_data": True,
            "using_5s": using_5s,
        }

        if comp_3s:
            result["avg_3s"] = round(sum(comp_3s) / len(comp_3s) * 100, 1)
            result["count_3s"] = len(comp_3s)
        if comp_5s:
            result["avg_5s"] = round(sum(comp_5s) / len(comp_5s) * 100, 1)
            result["count_5s"] = len(comp_5s)

        return result

    def analyze_play_duration(self) -> dict:
        """分析平均播放时长"""
        durations = [v.get('avg_play_duration') for v in self.videos
                     if isinstance(v.get('avg_play_duration'), (int, float)) and v.get('avg_play_duration', 0) > 0]
        if not durations:
            return {"error": "没有平均播放时长数据。请确认导出数据包含「平均播放时长」列。"}

        avg = sum(durations) / len(durations)
        mx = max(durations)
        mn = min(durations)

        ranges = [(0, 15), (15, 30), (30, 60), (60, 120), (120, 999999)]
        distribution = []
        for start, end in ranges:
            count = sum(1 for d in durations if start <= d <= end)
            label = f"{start}-{end}秒" if end < 999999 else f"{start}秒+"
            distribution.append({"label": label, "count": count, "pct": round(count / len(durations) * 100, 1)})

        return {
            "avg": round(avg, 1),
            "max": round(mx, 1),
            "min": round(mn, 1),
            "count": len(durations),
            "distribution": distribution,
        }

    def analyze_fan_ratio(self) -> dict:
        """分析粉丝播放占比"""
        ratios = [v.get('fan_play_ratio') for v in self.videos
                  if isinstance(v.get('fan_play_ratio'), (int, float)) and v.get('fan_play_ratio', 0) > 0]
        if not ratios:
            return {"error": "没有粉丝播放占比数据"}

        avg = sum(ratios) / len(ratios) * 100
        return {
            "avg": round(avg, 1),
            "count": len(ratios),
            "has_data": True,
        }

    def get_summary(self) -> dict:
        """数据摘要"""
        fields_present = []
        if self.videos:
            sample = self.videos[0]
            for f in ['title', 'likes', 'plays', 'completion_rate', 'avg_play_duration',
                       'comp_3s', 'favorites', 'fan_play_ratio', 'drop_off_rate']:
                if f in sample and sample[f] is not None:
                    log_val = sample[f]
                    if isinstance(log_val, float) and log_val < 1:
                        log_val = f"{log_val*100:.1f}%"
                    fields_present.append({"field": f, "sample": log_val})

        return {
            "videos_count": len(self.videos),
            "users_count": len(self.users),
            "fields_present": fields_present,
            "last_updated": datetime.now().isoformat(),
        }

    def full_analysis(self) -> dict:
        """全维度分析 + AI 建议"""
        result = {
            "interaction": self.analyze_interaction(),
            "content_length": self.analyze_content_length(),
            "keywords": self.analyze_keywords(30),
            "completion": self.analyze_completion(),
            "play_duration": self.analyze_play_duration(),
            "fan_ratio": self.analyze_fan_ratio(),
            "summary": self.get_summary(),
        }
        result["advice"] = self._generate_advice(result)
        result["sample_count"] = len(self.videos)
        return result

    # ─── 基于规则生成结论和建议 ────────────────────────────

    def _generate_advice(self, result: dict) -> dict:
        """根据分析结果自动生成中文结论和改进建议"""
        advice = {"summary": "", "conclusions": [], "suggestions": [], "warnings": []}
        n = len(self.videos)

        # 样本量警告
        if n == 0:
            advice["summary"] = "暂无数据，请上传文件后重试。"
            return advice
        if n < 5:
            advice["warnings"].append(f"⚠️ 当前仅 {n} 条视频数据，统计结果仅供参考。建议积累 10 条以上再下结论。")

        # ── 互动数据 ──
        interaction = result.get("interaction", {})
        if interaction and "error" not in interaction:
            likes = interaction.get("likes", {})
            plays = interaction.get("plays", {})
            eng = interaction.get("engagement_rate", {})

            if likes:
                avg_likes = likes.get("raw_avg", 0)
                if avg_likes > 0:
                    if avg_likes < 500:
                        advice["conclusions"].append("🔻 平均点赞偏低（<500），说明内容吸引力不足，需优化选题或开头。")
                        advice["suggestions"].append("尝试在视频前3秒设置更强钩子（如反常识提问、数据冲击），参考抖音热门同行的开头方式。")
                    elif avg_likes < 5000:
                        advice["conclusions"].append("📊 点赞表现中等（500-5000），内容有一定吸引力，有提升空间。")
                        advice["suggestions"].append("保持当前标题风格，增加互动引导（如「你属于哪种？评论区告诉我」）提升评论区活跃度。")
                    else:
                        advice["conclusions"].append("🔥 点赞表现优秀（>5000），内容能引起用户共鸣，值得分析爆款规律。")
                        advice["suggestions"].append("总结这条爆款的标题公式和结构，复制到后续视频创作中。")

            if plays:
                avg_plays = plays.get("raw_avg", 0)
                if avg_plays > 0 and avg_plays < 10000:
                    advice["conclusions"].append("📉 平均播放量偏低（<1万），可能是选题受众窄或封面/标题不够吸引点击。")
                    advice["suggestions"].append("优化封面图和标题：标题用数字+痛点+反常识公式，封面用高对比色+大字。")

            if eng:
                try:
                    eng_val = float(eng.get("avg", "0%").replace("%", ""))
                    if eng_val > 0:
                        if eng_val < 3:
                            advice["conclusions"].append("📊 互动率偏低（<3%），用户看完但没有行动欲望。")
                            advice["suggestions"].append("视频结尾增加明确行动号召：点赞/关注/收藏引导，可用「下期拆解XXX，先关注不错过」。")
                        elif eng_val < 10:
                            advice["conclusions"].append("👍 互动率中等（3-10%），有一定互动基础。")
                        else:
                            advice["conclusions"].append("💥 互动率优秀（>10%），用户参与度高。")
                except ValueError:
                    pass

        # ── 完播率 ──
        completion = result.get("completion", {})
        if completion and completion.get("has_data"):
            cr_avg = completion.get("avg", 0)
            label = "5秒完播率" if completion.get("using_5s") else "完播率"
            if cr_avg > 0:
                if cr_avg < 15:
                    advice["conclusions"].append(f"⏱️ {label}偏低（<15%），绝大多数用户在开头就划走了。")
                    advice["suggestions"].append("重点优化前5秒：去掉冗长铺垫，直接给核心结论或悬念。前5秒决定80%的留存率。")
                elif cr_avg < 30:
                    advice["conclusions"].append(f"⏱️ {label} {cr_avg}%，处于抖音平均水平，有优化空间。")
                    advice["suggestions"].append("检查视频节奏：每15-20秒设置一个小高潮或信息增量，减少用户中途划走的动力。")
                else:
                    advice["conclusions"].append(f"⏱️ {label} {cr_avg}%，高于抖音平均水平，内容留存能力强！")

        # ── 跳出率 ──
        drop_rates = [v.get('drop_off_rate') for v in self.videos
                      if isinstance(v.get('drop_off_rate'), (int, float)) and v.get('drop_off_rate', 0) > 0]
        if drop_rates:
            avg_drop = sum(drop_rates) / len(drop_rates) * 100
            if avg_drop > 40:
                advice["conclusions"].append(f"📉 2秒跳出率 {avg_drop:.1f}%（较高），超过四成用户在2秒内划走。")
                advice["suggestions"].append("开头0-2秒放最抓眼球的内容：视觉冲击画面、强冲突提问、或反常识数据，不要logo和片头。")

        # ── 播放时长 ──
        duration = result.get("play_duration", {})
        if duration and "error" not in duration:
            pd_avg = duration.get("avg", 0)
            if pd_avg > 0 and pd_avg < 20:
                advice["conclusions"].append("🕐 平均播放时长很短（<20秒），用户快速划走。")
                advice["suggestions"].append("尝试缩短视频至30-60秒，信息密度提高，去掉所有废话。每句话都要有信息增量。")
            elif pd_avg > 0 and pd_avg > 60:
                advice["conclusions"].append(f"🕐 平均播放时长 {pd_avg}秒，观众愿意看较长时间，内容深度够。")

        # ── 粉丝播放占比 ──
        fan = result.get("fan_ratio", {})
        if fan and fan.get("has_data"):
            fan_avg = fan.get("avg", 0)
            if fan_avg > 0:
                if fan_avg > 50:
                    advice["conclusions"].append("👥 粉丝播放占比高（>50%），主要靠粉丝播放，破圈能力弱。")
                    advice["suggestions"].append("尝试更泛人群的选题方向，或蹭热点话题来获取非粉丝流量。标题加入大众搜索词。")
                else:
                    advice["conclusions"].append(f"👥 粉丝播放占比 {fan_avg}%，有一定破圈能力。")

        # ── 标题 ──
        cl = result.get("content_length", {})
        if cl and "error" not in cl:
            avg_len = cl.get("avg", 0)
            if avg_len > 0:
                if avg_len < 10:
                    advice["suggestions"].append("标题偏短（平均" + str(avg_len) + "字），建议增加到15-25字，包含关键词+痛点+解决方案。")
                elif avg_len > 30:
                    advice["suggestions"].append("标题偏长（平均" + str(avg_len) + "字），建议精简到15-25字，确保在搜索结果中完整显示。")

        # ── 生成总结 ──
        total = len(advice["conclusions"]) + len(advice["suggestions"])
        if total == 0:
            advice["summary"] = "✅ 数据质量良好，建议多积累数据后重新分析获取更完整的诊断。"
        elif n >= 5:
            advice["summary"] = f"共发现 {len(advice['conclusions'])} 个关键结论，{len(advice['suggestions'])} 条改进建议。"
        else:
            advice["summary"] = f"基于 {n} 条视频的初步分析（数据较少，结论仅供参考）。"

        return advice

    def clear(self):
        """清空数据"""
        self.videos = []
        self.users = []

    # ================================================================
    # 内部工具
    # ================================================================

    def _build_distribution(self, data, ranges, label_fn):
        total = len(data)
        dist = []
        for start, end in ranges:
            count = sum(1 for x in data if start <= x <= end)
            dist.append({"label": label_fn(start, end), "count": count, "pct": round(count / total * 100, 1)})
        return dist

    def _extract_video_items(self, soup) -> list[dict]:
        """从 HTML 提取视频数据（在线搜索用）"""
        results = []
        items = soup.select('li.SwZLHMKk')
        for item in items:
            try:
                title_el = item.select_one('div.VDYK8Xd7')
                author_el = item.select_one('span.MZNczJmS')
                link_el = item.select_one('a.hY8lWHgA')
                likes_el = item.select_one('span.cIiU4Muu')

                title = title_el.get_text(strip=True) if title_el else ''
                author = author_el.get_text(strip=True) if author_el else ''
                link = ''
                if link_el:
                    href = link_el.get('href', '')
                    link = 'https:' + href if href.startswith('//') else href
                likes = likes_el.get_text(strip=True) if likes_el else '0'

                if title:
                    results.append({
                        'title': title,
                        'author': author,
                        'video_link': link,
                        'likes': _parse_num(likes),
                        'comments': 0,
                        'shares': 0,
                        'publish_time': '',
                        'collected_at': datetime.now().isoformat(),
                    })
            except Exception:
                continue
        return results
