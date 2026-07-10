"use client"

import { FileText, Lightbulb, Layers, ArrowUpRight } from "lucide-react"
import { script } from "@/lib/agent-data"

export function ScriptWorkspace() {
  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground">
            <FileText className="size-5" />
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              已生成脚本
            </p>
            <h3 className="mt-0.5 text-lg font-semibold text-foreground">
              {script.title}
            </h3>
            <p className="mt-1 font-mono text-xs text-muted-foreground">
              {script.wordCount} 字 · 约 60 秒口播
            </p>
          </div>
        </div>
        <button
          type="button"
          className="flex items-center gap-1.5 rounded-xl border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
        >
          打开脚本
          <ArrowUpRight className="size-4" />
        </button>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-secondary/60 p-4">
          <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Lightbulb className="size-3.5 text-brand" />
            关键洞察
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-foreground">
            {script.insight}
          </p>
        </div>
        <div className="rounded-xl bg-secondary/60 p-4">
          <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Layers className="size-3.5 text-brand" />
            采用策略
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-foreground">
            {script.strategy}
          </p>
        </div>
      </div>
    </div>
  )
}
