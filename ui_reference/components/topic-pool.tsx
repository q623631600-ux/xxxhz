"use client"

import { Target, Users, PenLine, ArrowRight } from "lucide-react"
import { topics, type Topic } from "@/lib/agent-data"
import { cn } from "@/lib/utils"

function ScoreRing({ score }: { score: number }) {
  const tone =
    score >= 90
      ? "text-brand"
      : score >= 80
        ? "text-accent-foreground"
        : "text-muted-foreground"
  return (
    <div className="flex flex-col items-end leading-none">
      <span className={cn("font-mono text-2xl font-semibold tabular-nums", tone)}>
        {score}
      </span>
      <span className="mt-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        爆款指数
      </span>
    </div>
  )
}

function TopicCard({ topic }: { topic: Topic }) {
  return (
    <article className="group flex flex-col rounded-2xl border border-border bg-card p-5 transition-colors hover:border-brand/40">
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-pretty text-base font-semibold leading-snug text-foreground">
          {topic.title}
        </h3>
        <ScoreRing score={topic.viralScore} />
      </div>

      <p className="mt-3 flex items-start gap-2 text-sm leading-relaxed text-muted-foreground">
        <Target className="mt-0.5 size-4 shrink-0 text-brand" />
        {topic.reason}
      </p>

      <dl className="mt-4 grid gap-2.5 border-t border-border pt-4 text-sm">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Users className="size-4 shrink-0" />
          <dt className="sr-only">目标受众</dt>
          <dd className="text-foreground">{topic.audience}</dd>
        </div>
        <div className="flex items-center gap-2 text-muted-foreground">
          <PenLine className="size-4 shrink-0" />
          <dt className="sr-only">内容角度</dt>
          <dd className="text-foreground">{topic.angle}</dd>
        </div>
      </dl>

      <button
        type="button"
        className="mt-5 flex items-center justify-center gap-1.5 rounded-xl bg-secondary px-4 py-2.5 text-sm font-medium text-secondary-foreground transition-colors hover:bg-primary hover:text-primary-foreground"
      >
        生成脚本
        <ArrowRight className="size-4" />
      </button>
    </article>
  )
}

export function TopicPool() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {topics.map((t) => (
        <TopicCard key={t.id} topic={t} />
      ))}
    </div>
  )
}
