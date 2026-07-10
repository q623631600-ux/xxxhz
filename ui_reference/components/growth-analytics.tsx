"use client"

import { Video, Eye, TrendingUp, Trophy, Sparkles } from "lucide-react"
import { analytics } from "@/lib/agent-data"

function TrendChart({ data }: { data: number[] }) {
  const max = Math.max(...data)
  const min = Math.min(...data)
  const w = 100
  const h = 40
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w
    const y = h - ((v - min) / (max - min || 1)) * h
    return [x, y] as const
  })
  const line = pts.map(([x, y]) => `${x},${y}`).join(" ")
  const area = `0,${h} ${line} ${w},${h}`

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="h-20 w-full"
      aria-hidden="true"
    >
      <polygon points={area} fill="var(--brand)" opacity="0.1" />
      <polyline
        points={line}
        fill="none"
        stroke="var(--brand)"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Video
  label: string
  value: string
}) {
  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="size-4" />
        <span className="text-xs font-medium">{label}</span>
      </div>
      <p className="mt-2 font-mono text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </p>
    </div>
  )
}

export function GrowthAnalytics() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <StatCard icon={Video} label="累计创作视频" value={String(analytics.totalVideos)} />
      <StatCard icon={Eye} label="平均播放量" value={analytics.avgViews} />
      <div className="rounded-2xl border border-border bg-card p-5">
        <div className="flex items-center gap-2 text-muted-foreground">
          <TrendingUp className="size-4 text-brand" />
          <span className="text-xs font-medium">表现趋势 · 近 12 周</span>
        </div>
        <TrendChart data={analytics.trend} />
      </div>

      <div className="rounded-2xl border border-border bg-card p-5 lg:col-span-1">
        <p className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Trophy className="size-4 text-brand" />
          高表现选题
        </p>
        <ul className="mt-3 flex flex-col gap-3">
          {analytics.topTopics.map((t, i) => (
            <li key={t.title} className="flex items-center gap-3">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-secondary font-mono text-xs font-semibold text-foreground">
                {i + 1}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-foreground">
                {t.title}
              </span>
              <span className="font-mono text-xs tabular-nums text-muted-foreground">
                {t.views}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-2xl border border-border bg-card p-5 lg:col-span-2">
        <p className="flex items-center gap-2 text-sm font-medium text-foreground">
          <Sparkles className="size-4 text-brand" />
          Agent 增长建议
        </p>
        <ul className="mt-3 flex flex-col gap-2.5">
          {analytics.recommendations.map((r) => (
            <li
              key={r}
              className="flex items-start gap-2.5 rounded-xl bg-secondary/60 px-4 py-3 text-sm leading-relaxed text-foreground"
            >
              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-brand" />
              {r}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
