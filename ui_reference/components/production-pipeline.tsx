"use client"

import { Check, Loader2 } from "lucide-react"
import { pipeline } from "@/lib/agent-data"
import { cn } from "@/lib/utils"

export function ProductionPipeline() {
  const doneCount = pipeline.filter((s) => s.status === "done").length
  const progress = Math.round((doneCount / pipeline.length) * 100)

  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      <div className="mb-5 flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          总进度 ·{" "}
          <span className="font-medium text-foreground">{progress}%</span>
        </p>
        <div className="h-1.5 w-40 overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-brand transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <ol className="flex flex-wrap items-center gap-y-4">
        {pipeline.map((step, i) => (
          <li key={step.name} className="flex items-center">
            <div className="flex flex-col items-center gap-2">
              <span
                className={cn(
                  "flex size-9 items-center justify-center rounded-full border text-sm font-medium",
                  step.status === "done" &&
                    "border-brand bg-brand text-brand-foreground",
                  step.status === "active" &&
                    "border-brand bg-accent text-accent-foreground",
                  step.status === "pending" &&
                    "border-border bg-card text-muted-foreground",
                )}
              >
                {step.status === "done" ? (
                  <Check className="size-4" />
                ) : step.status === "active" ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  i + 1
                )}
              </span>
              <span
                className={cn(
                  "whitespace-nowrap text-xs",
                  step.status === "pending"
                    ? "text-muted-foreground"
                    : "font-medium text-foreground",
                )}
              >
                {step.name}
              </span>
            </div>
            {i < pipeline.length - 1 && (
              <span
                className={cn(
                  "mx-1.5 mb-5 h-px w-6 sm:w-10",
                  step.status === "done" ? "bg-brand" : "bg-border",
                )}
                aria-hidden="true"
              />
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}
