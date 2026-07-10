"use client"

import { useState } from "react"
import { Lightbulb, FileText, Workflow, LineChart } from "lucide-react"
import { AppSidebar } from "@/components/app-sidebar"
import { AgentConsole } from "@/components/agent-console"
import { TopicPool } from "@/components/topic-pool"
import { ScriptWorkspace } from "@/components/script-workspace"
import { ProductionPipeline } from "@/components/production-pipeline"
import { GrowthAnalytics } from "@/components/growth-analytics"
import type { NavId } from "@/lib/agent-data"

function SectionHeader({
  icon: Icon,
  eyebrow,
  title,
  desc,
}: {
  icon: typeof Lightbulb
  eyebrow: string
  title: string
  desc: string
}) {
  return (
    <div className="mb-5 flex items-start gap-3">
      <div className="flex size-9 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-brand">
        <Icon className="size-[18px]" />
      </div>
      <div>
        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {eyebrow}
        </p>
        <h2 className="text-xl font-semibold tracking-tight text-foreground">
          {title}
        </h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{desc}</p>
      </div>
    </div>
  )
}

export default function Page() {
  const [active, setActive] = useState<NavId>("dashboard")

  return (
    <div className="flex min-h-svh bg-background">
      <AppSidebar active={active} onSelect={setActive} />

      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-6xl px-5 py-10 sm:px-8 lg:py-16">
          <AgentConsole />

          <div className="mt-16 flex flex-col gap-16">
            <section aria-labelledby="topics">
              <SectionHeader
                icon={Lightbulb}
                eyebrow="选题池"
                title="推荐视频选题"
                desc="Agent 基于书籍洞察与平台热度筛选的 5 个高潜力选题"
              />
              <TopicPool />
            </section>

            <section aria-labelledby="script">
              <SectionHeader
                icon={FileText}
                eyebrow="脚本工作区"
                title="生成的脚本"
                desc="围绕选定方向产出的完整短视频脚本"
              />
              <ScriptWorkspace />
            </section>

            <section aria-labelledby="pipeline">
              <SectionHeader
                icon={Workflow}
                eyebrow="生产流水线"
                title="从脚本到成片"
                desc="Agent 编排的端到端制作流程与实时进度"
              />
              <ProductionPipeline />
            </section>

            <section aria-labelledby="analytics">
              <SectionHeader
                icon={LineChart}
                eyebrow="数据分析"
                title="增长表现"
                desc="持续追踪表现并给出可执行的优化建议"
              />
              <GrowthAnalytics />
            </section>
          </div>
        </div>
      </main>
    </div>
  )
}
