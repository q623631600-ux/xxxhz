"use client"

import {
  LayoutDashboard,
  Sparkles,
  Lightbulb,
  Workflow,
  LineChart,
  Settings,
  BookOpen,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { NavId } from "@/lib/agent-data"

const items: { id: NavId; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "dashboard", label: "总览", icon: LayoutDashboard },
  { id: "agent", label: "Agent 工作台", icon: Sparkles },
  { id: "topics", label: "选题池", icon: Lightbulb },
  { id: "pipeline", label: "生产流水线", icon: Workflow },
  { id: "analytics", label: "数据分析", icon: LineChart },
  { id: "settings", label: "设置", icon: Settings },
]

export function AppSidebar({
  active,
  onSelect,
}: {
  active: NavId
  onSelect: (id: NavId) => void
}) {
  return (
    <aside className="sticky top-0 hidden h-svh w-60 shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3 py-5 md:flex">
      <div className="flex items-center gap-2.5 px-3 pb-6">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <BookOpen className="size-4" />
        </div>
        <div className="leading-tight">
          <p className="text-sm font-semibold tracking-tight text-sidebar-foreground">
            Inkwell
          </p>
          <p className="text-[11px] text-muted-foreground">书籍增长 Agent</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1">
        {items.map((item) => {
          const Icon = item.icon
          const isActive = active === item.id
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item.id)}
              aria-current={isActive ? "page" : undefined}
              className={cn(
                "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-secondary hover:text-sidebar-foreground",
              )}
            >
              <Icon className="size-[18px]" />
              {item.label}
            </button>
          )
        })}
      </nav>

      <div className="mt-auto rounded-xl border border-sidebar-border bg-card p-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-full bg-accent text-accent-foreground text-xs font-semibold">
            林
          </div>
          <div className="min-w-0 leading-tight">
            <p className="truncate text-xs font-medium text-sidebar-foreground">
              林知遥
            </p>
            <p className="truncate text-[11px] text-muted-foreground">
              专业版
            </p>
          </div>
        </div>
      </div>
    </aside>
  )
}
