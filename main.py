#!/usr/bin/env python3
"""
讲书增长 Agent — CLI 入口

BookGrowthAgent 模式（V1 新增）:
  python main.py --produce --book "认知觉醒"                     # Agent内容生产
  python main.py --analyze --file ./data.xlsx                     # 数据分析
  python main.py --analyze --file ./data.csv --book "认知觉醒"     # 数据分析（关联书籍）
  python main.py --review                                         # 全部复盘
  python main.py --review --book "认知觉醒"                       # 单书复盘

原有 Workflow 模式（向后兼容）:
  python main.py --book "毛选" --plan-only                        # 生成大纲
  python main.py --book "毛选" --kp-id 1 --script-only            # 生成脚本
  python main.py --book "毛选" --kp-id 1 --full                   # 完整视频
  python main.py --book "认知觉醒"                                 # 整书概述
"""
import argparse
import json
import sys

from config import check_config
from utils.logger import log
from services.orchestrator import Orchestrator
from services.script_generator import ANALYSIS_ANGLES


def main():
    angles_desc = "\n".join(
        f"    {k:12s} - {v.split(chr(10))[0] if chr(10) in v else v}"
        for k, v in ANALYSIS_ANGLES.items()
    )

    parser = argparse.ArgumentParser(
        description="Book Growth Agent - 讲书增长Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
使用示例:
  # ---- Agent 模式 (V1) ----
  python main.py --produce --book "认知觉醒"                   Agent主导内容生产
  python main.py --analyze --file ./data.xlsx                  数据分析
  python main.py --review --book "认知觉醒"                    增长复盘

  # ---- Workflow 模式 (原有) ----
  python main.py --book "毛选" --plan-only                     生成大纲
  python main.py --book "毛选" --kp-id 1 --script-only         生成脚本

分析角度（仅整书概述模式使用）:
{angles_desc}
        """,
    )

    # ---- Agent 模式参数 (V1) ----
    parser.add_argument("--produce", action="store_true", help="[Agent] 内容生产：分类→提炼→策略→选题池→选择→批量/单个深度生产")
    parser.add_argument("--analyze", action="store_true", help="[Agent] 数据分析：导入Excel/CSV → 诊断/复盘 → 归因 → 建议")
    parser.add_argument("--review", action="store_true", help="[Agent] 增长复盘：查询历史策略+效果+建议")

    # ---- 必选 ----
    parser.add_argument("--book", "-b", type=str, default="", help="书名")
    parser.add_argument("--file", "-f", type=str, default="", help="数据文件路径（Excel/CSV）")

    # ---- 模式选择 (Workflow) ----
    parser.add_argument("--plan-only", action="store_true", help="只生成视频选题大纲")
    parser.add_argument("--kp-id", type=int, default=0, help="指定知识点 ID")
    parser.add_argument("--script-only", action="store_true", help="只生成脚本（默认行为）")
    parser.add_argument("--full", action="store_true", help="生成完整视频（需图片API）")

    # ---- Agent 生产模式参数 ----
    parser.add_argument("--topic-id", type=int, default=0, help="[Agent] 选题ID: N(单个) / -3(Top3) / -5(Top5)，不指定则交互式选择")

    # ---- 可选输入 ----
    parser.add_argument("--toc", type=str, default="", help="目录文件路径")
    parser.add_argument("--source", type=str, default="", help="原文/笔记文件路径")
    parser.add_argument("--focus", type=str, default="", help="聚焦方向指引")

    # ---- 整书概述模式参数 ----
    parser.add_argument("--segments", "-s", type=int, default=8, help="分段数（仅整书概述）")
    parser.add_argument("--angle", "-a", type=str, default="auto", choices=list(ANALYSIS_ANGLES.keys()), help="分析角度（仅整书概述）")
    parser.add_argument("--style", type=str, default="", help="图片风格")
    parser.add_argument("--dry-run", action="store_true", help="仅生成脚本（仅整书概述）")
    parser.add_argument("--skip-safety", action="store_true", help="跳过安全审核")

    args = parser.parse_args()

    # ================================================================
    # Agent 模式 (V1)
    # ================================================================

    # 模式 1: Agent 内容生产（两阶段：选题池 → 用户选择 → 深度生产）
    if args.produce:
        if not args.book:
            log.error("--produce 模式需要 --book 参数")
            sys.exit(1)

        from agent import BookGrowthAgent
        agent = BookGrowthAgent()

        # Phase 1: 生成选题池
        result = agent.produce(
            book_name=args.book,
            toc=args.toc,
            source=args.source,
            focus=args.focus,
        )
        topics = result.get("topics", [])

        if not topics:
            log.error("选题池生成为空，无法继续")
            sys.exit(1)

        # 展示选题池
        _print_topic_pool(result)

        # Phase 2: 用户选择选题
        strategy_params = {
            "category": result.get("classification", {}).get("category", ""),
            "strategy_name": result.get("strategy", {}).get("strategy_name", ""),
        }

        # 支持 --topic-id=0(默认) / --topic-id=N(单个) / --topic-id=-3(Top3) / --topic-id=-5(Top5)
        if args.topic_id and args.topic_id > 0:
            # 单个选题
            selected_topic = next((t for t in topics if t.get("topic_id") == args.topic_id), topics[0])
            log.info(f"自动选择选题 #{args.topic_id}")
            strategy_params.update({
                "tone": selected_topic.get("tone", ""),
                "hook_type": selected_topic.get("hook_type", ""),
                "structure_emphasis": selected_topic.get("structure_emphasis", ""),
                "visual_style": selected_topic.get("visual_style", ""),
            })
            final_result = agent.produce_with_topic(
                book_name=args.book,
                topic=selected_topic,
                strategy_params=strategy_params,
                toc=args.toc,
                source=args.source,
                focus=args.focus,
            )
            _print_produce_final(final_result)
            return

        elif args.topic_id and args.topic_id < 0:
            # 批量：--topic-id=-3 表示 Top3
            count = min(abs(args.topic_id), len(topics))
            log.info(f"自动选择 Top{count}")
            final_result = agent.produce_topics(
                book_name=args.book,
                topics=topics,
                count=count,
                strategy_params=strategy_params,
                toc=args.toc,
                source=args.source,
                focus=args.focus,
            )
            _print_batch_result(final_result)
            return

        # 交互式选择
        try:
            print(f"\n  可选模式:")
            print(f"    输入数字 1-{len(topics)} → 生成单个选题")
            print(f"    输入 3 → 生成 Top3 选题（前3个）")
            print(f"    输入 5 → 生成 Top5 选题（全部）")
            print(f"    输入逗号分隔如 1,3,5 → 生成指定选题")
            print(f"    直接按Enter → 默认生成 Top1")
            choice = input(f"\n  请选择 > ").strip()
        except (EOFError, KeyboardInterrupt):
            choice = ""

        if not choice:
            # 默认 Top1（走单个生产逻辑，深度注入）
            selected_topic = topics[0]
            print(f"  已默认选择选题 #1")
            strategy_params.update({
                "tone": selected_topic.get("tone", ""),
                "hook_type": selected_topic.get("hook_type", ""),
                "structure_emphasis": selected_topic.get("structure_emphasis", ""),
                "visual_style": selected_topic.get("visual_style", ""),
            })
            final_result = agent.produce_with_topic(
                book_name=args.book,
                topic=selected_topic,
                strategy_params=strategy_params,
                toc=args.toc,
                source=args.source,
                focus=args.focus,
            )
            _print_produce_final(final_result)
            return

        # 解析用户输入
        if "," in choice:
            # 逗号分隔：生成指定选题
            try:
                ids = [int(x.strip()) for x in choice.split(",") if x.strip()]
                selected = [t for t in topics if t.get("topic_id") in ids]
                if not selected:
                    print(f"  [FAIL] 无效的选题ID，默认生成 Top1")
                    selected = [topics[0]]
                count = len(selected)
                final_result = agent.produce_topics(
                    book_name=args.book,
                    topics=selected,
                    count=count,
                    strategy_params=strategy_params,
                    toc=args.toc,
                    source=args.source,
                    focus=args.focus,
                )
                _print_batch_result(final_result)
                return
            except ValueError:
                print(f"  [FAIL] 输入格式错误，默认生成 Top1")
                selected_topic = topics[0]
        else:
            try:
                num = int(choice)
                if num == 1:
                    selected_topic = topics[0]
                elif 2 <= num <= len(topics):
                    # TopN 批量生产
                    final_result = agent.produce_topics(
                        book_name=args.book,
                        topics=topics,
                        count=num,
                        strategy_params=strategy_params,
                        toc=args.toc,
                        source=args.source,
                        focus=args.focus,
                    )
                    _print_batch_result(final_result)
                    return
                else:
                    print(f"  [FAIL] 输入超出范围 (1-{len(topics)})，默认生成 Top1")
                    selected_topic = topics[0]
            except ValueError:
                print(f"  [FAIL] 输入格式错误，默认生成 Top1")
                selected_topic = topics[0]

        # 兜底：Top1 单个生产
        if not isinstance(selected_topic, dict):
            selected_topic = topics[0]
        strategy_params.update({
            "tone": selected_topic.get("tone", ""),
            "hook_type": selected_topic.get("hook_type", ""),
            "structure_emphasis": selected_topic.get("structure_emphasis", ""),
            "visual_style": selected_topic.get("visual_style", ""),
        })
        final_result = agent.produce_with_topic(
            book_name=args.book,
            topic=selected_topic,
            strategy_params=strategy_params,
            toc=args.toc,
            source=args.source,
            focus=args.focus,
        )
        _print_produce_final(final_result)
        return

    # 模式 2: Agent 数据分析
    if args.analyze:
        if not args.file:
            log.error("--analyze 模式需要 --file 参数（Excel 或 CSV 文件路径）")
            sys.exit(1)
        from agent import BookGrowthAgent
        agent = BookGrowthAgent()
        result = agent.analyze(
            file_path=args.file,
            book_name=args.book or "",
        )
        _print_analyze_result(result)
        return

    # 模式 3: Agent 增长复盘
    if args.review:
        from agent import BookGrowthAgent
        agent = BookGrowthAgent()
        result = agent.review(book_name=args.book or "")
        _print_review_result(result)
        return

    # ================================================================
    # Workflow 模式 (原有，向后兼容)
    # ================================================================

    orch = Orchestrator()

    # 模式 4: 大纲规划
    if args.plan_only:
        if not args.book:
            log.error("--plan-only 模式需要 --book 参数")
            sys.exit(1)
        orch.plan_book(args.book, toc=args.toc, source=args.source, focus=args.focus)
        return

    # 模式 5: 单知识点脚本
    if args.kp_id > 0:
        if not args.book:
            log.error("--kp-id 模式需要 --book 参数")
            sys.exit(1)
        full = args.full
        orch.run_knowledge_point(args.book, args.kp_id, full_pipeline=full)
        return

    # 模式 6: 整书概述（默认行为）
    if args.book:
        issues = check_config()
        if issues and not args.dry_run:
            log.warn("配置问题：")
            for issue in issues:
                print(f"  - {issue}")
            if any("IMAGE" in i for i in issues) and not any("LLM" in i for i in issues):
                log.info("LLM 配置正常，可以运行 --plan-only 或 --kp-id --script-only")
            print("\n正确使用流程:")
            print(f"  python main.py --book \"{args.book}\" --plan-only")
            print(f"  python main.py --book \"{args.book}\" --kp-id 1 --script-only")
            sys.exit(1)

        orch.run_book_script(
            book_name=args.book,
            num_segments=args.segments,
            image_style=args.style,
            angle=args.angle,
            dry_run=args.dry_run,
            skip_safety=args.skip_safety,
        )
        return

    # 无参数：显示帮助
    parser.print_help()


# ================================================================
# 输出格式化
# ================================================================

def _print_batch_result(result: dict):
    """格式化输出批量生产结果"""
    print(f"\n{'='*60}")
    print(f"  [OK] Book Growth Agent — 批量内容生产完成")
    print(f"{'='*60}")

    print(f"\n  共选择: {result.get('total_selected', 0)} 个选题")
    print(f"  成功: {result.get('success_count', 0)} | 失败: {result.get('fail_count', 0)}")

    for r in result.get("results", []):
        status = "[OK]" if r.get("success") else "[FAIL]"
        tid = r.get("topic_id", "?")
        title = r.get("topic_title", "")[:50]
        if r.get("success"):
            print(f"\n  {status} [{tid}] {title}")
            print(f"      脚本: {r.get('script_words', 0)} 字")
            print(f"      目录: {r.get('kp_dir', '')}")
        else:
            print(f"\n  {status} [{tid}] {title}")
            print(f"      错误: {r.get('error', '未知')[:80]}")

    book_name = result.get("book_name", "")
    print(f"\n  下一步:")
    print(f"    工作台: http://127.0.0.1:8000/work?book={book_name}")
    print(f"{'='*60}\n")

def _print_topic_pool(result: dict):
    """格式化输出 Agent 选题池"""
    cls = result.get("classification", {})
    ins = result.get("insights", {})
    strat = result.get("strategy", {})
    topics = result.get("topics", [])

    print(f"\n{'='*60}")
    print(f"  Book Growth Agent — 选题池生成")
    print(f"{'='*60}")

    print(f"\n  [BOOK] 书籍分类: {cls.get('category', '?')}")
    print(f"     受众: {cls.get('target_audience', '?')}")

    print(f"\n  [IDEA] 核心观点")
    for i, insight in enumerate(ins.get("insights", []), 1):
        print(f"     [{i}] {insight.get('insight_text', '')}")

    print(f"\n  [TARGET] 推荐策略: {strat.get('strategy_name', '?')} | {strat.get('tone', '?')}")

    print(f"\n  {'='*40}")
    print(f"   [LIST] Top {len(topics)} 选题候选")
    print(f"  {'='*40}")
    for t in topics:
        tid = t.get("topic_id", "?")
        title = t.get("topic_title", "")
        score = t.get("score", "?")
        angle = t.get("content_angle", "")
        hook = t.get("hook_type", "")
        print(f"\n     [{tid}] [STAR] {score}/10")
        print(f"         {title}")
        print(f"         切入: {angle[:40]}{'...' if len(angle or '') > 40 else ''}")
        print(f"         钩子: {hook}")
    print(f"\n  {'='}60\n")


def _print_produce_final(result: dict):
    """格式化输出 Agent 深度生产最终结果"""
    topic = result.get("selected_topic", {})
    plan = result.get("plan", {})
    context = result.get("agent_context", {})

    print(f"\n{'='*60}")
    print(f"  [OK] Book Growth Agent — 深度内容生产完成")
    print(f"{'='*60}")

    print(f"\n  📌 选题")
    print(f"     {topic.get('topic_title', '')}")
    print(f"     评分: {topic.get('score', '?')}/10")

    print(f"\n  [TARGET] 深度注入的 Agent 策略参数")
    for key, val in context.items():
        if val:
            print(f"     {key}: {str(val)[:60]}")

    total_kps = result.get("total_kps", 0)
    print(f"\n  [LIST] 选题大纲: {total_kps} 个知识点")
    print(f"     已保存到 output/{result.get('book_name', '')}/knowledge_plan.json")

    print(f"\n  下一步:")
    book_name = result.get("book_name", "")
    print(f"    生成讲稿: python main.py --book \"{book_name}\" --kp-id 1 --script-only")
    print(f"    工作台:   http://127.0.0.1:8000/work?book={book_name}")
    print(f"{'='*60}\n")


def _print_analyze_result(result: dict):
    """格式化输出 Agent 分析结果"""
    if not result.get("success"):
        print(f"\n[FAIL] 分析失败: {result.get('error', '未知错误')}\n")
        return

    print(f"\n{'='*60}")
    print(f"  Book Growth Agent — 数据分析完成")
    print(f"{'='*60}")

    mode = result.get("mode", "?")
    count = result.get("video_count", 0)
    print(f"\n  模式: {'单视频诊断' if mode == 'single' else '批量复盘'}")
    print(f"  视频数: {count}")

    if mode == "single":
        diag = result.get("diagnosis", {})
        print(f"\n  [DATA] 诊断评分: {diag.get('overall_score', '?')}")
        for dim, data in diag.get("dimensions", {}).items():
            print(f"     {dim}: {data.get('score', '?')}分 — {data.get('comment', '')[:40]}")
        print(f"\n  优势: {', '.join(diag.get('strengths', []))}")
        print(f"  不足: {', '.join(diag.get('weaknesses', []))}")

    else:
        analysis = result.get("analysis", {})
        stats = analysis.get("overall_stats", {})
        print(f"\n  [DATA] 总览")
        print(f"     平均播放: {stats.get('avg_plays', 0):.0f}")
        print(f"     平均点赞: {stats.get('avg_likes', 0):.0f}")
        print(f"     最高播放: {stats.get('max_plays', 0)}")

        top = analysis.get("top_videos", [])
        bottom = analysis.get("bottom_videos", [])
        if top:
            print(f"\n  [TOP] Top 视频")
            for v in top[:3]:
                print(f"     [{v.get('plays', 0)}] {v.get('title', '')[:40]}")
        if bottom:
            print(f"\n  [DOWN] Bottom 视频")
            for v in bottom[:3]:
                print(f"     [{v.get('plays', 0)}] {v.get('title', '')[:40]}")

    attr = result.get("attribution", {})
    if attr.get("key_drivers"):
        print(f"\n  [FIND] 关键驱动因素")
        for d in attr["key_drivers"]:
            print(f"     [{d.get('impact', '?')}] {d.get('factor', '')}")

    advice = result.get("advice", {})
    if advice.get("priorities"):
        print(f"\n  [TALK] 增长建议")
        for p in advice["priorities"]:
            print(f"     [{p.get('rank', '?')}] {p.get('action', '')}")

    print(f"\n{'='*60}\n")


def _print_review_result(result: dict):
    """格式化输出 Agent 复盘结果"""
    print(f"\n{'='*60}")
    print(f"  Book Growth Agent — 增长复盘")
    print(f"{'='*60}")

    print(f"\n  书籍: {result.get('book_name', '全部')}")
    print(f"  共生产: {result.get('total_produced', 0)} 次")
    print(f"  共分析: {result.get('total_analyzed', 0)} 次")

    if result.get("strategy_summary"):
        print(f"\n  [LIST] 策略使用统计")
        for key, info in result["strategy_summary"].items():
            print(f"     {key}: {info.get('count', 0)} 次使用, {info.get('with_metrics', 0)} 次有效果数据")

    if result.get("recent_strategies"):
        print(f"\n  🕐 最近策略")
        for e in reversed(result["recent_strategies"][-3:]):
            metrics = e.get("metrics", {})
            metric_str = f" | 均播:{metrics.get('avg_plays', '?')}" if metrics else ""
            print(f"     [{e.get('book_name', '')}] {e.get('strategy_name', '?')}{metric_str}")

    if result.get("recent_analyses"):
        print(f"\n  🕐 最近分析")
        for s in reversed(result["recent_analyses"][-3:]):
            print(f"     [{s.get('date', '')[:10]}] {s.get('mode', '?')} - {s.get('video_count', 0)} 条视频")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
