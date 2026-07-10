"use client"

import { useEffect, useRef, useState } from "react"
import { ArrowUp, Sparkles, Check, Loader2, BookText } from "lucide-react"
import { cn } from "@/lib/utils"
import { examplePrompts, reasoningSteps } from "@/lib/agent-data"

export function AgentConsole() {
  const [value, setValue] = useState("")
  const [running, setRunning] = useState(false)
  const [doneCount, setDoneCount] = useState(0)
  const [activeQuery, setActiveQuery] = useState<string | null>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  useEffect(() => {
    return () => timers.current.forEach(clearTimeout)
  }, [])

  function run(query: string) {
    if (!query.trim()) return
    timers.current.forEach(clearTimeout)
    timers.current = []
    setActiveQuery(query)
    setRunning(true)
    setDoneCount(0)
    reasoningSteps.forEach((_, i) => {
      const t = setTimeout(
        () => {
          setDoneCount(i + 1)
          if (i === reasoningSteps.length - 1) setRunning(false)
        },
        (i + 1) * 850,
      )
      timers.current.push(t)
    })
  }

  return (
    <section className="mx-auto w-full max-w-3xl">
      <div className="flex flex-col items-center text-center">
        <div className="mb-4 inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
          <Sparkles className="size-3.5 text-brand" />
          AI 内容操作系统
        </div>
        <h1 className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
          把一本书，变成会增长的内容
        </h1>
        <p className="mt-3 max-w-xl text-pretty text-[15px] leading-relaxed text-muted-foreground">
          告诉 Agent 你想分析的书或想创作的内容，它会完成从洞察、选题到成片的全过程，并持续优化表现。
        </p>
      </div>

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          run(value)
        }}
        className="mt-7"
      >
        <div className="rounded-2xl border border-border bg-card p-2.5 shadow-sm transition-shadow focus-within:shadow-md">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                run(value)
              }
            }}
            rows={2}
            placeholder="输入书名，或告诉 Agent 你想创作什么…"
            className="w-full resize-none bg-transparent px-3 pt-2 text-[15px] leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
          />
          <div className="flex items-center justify-between px-1 pt-1">
            <span className="flex items-center gap-1.5 pl-2 text-xs text-muted-foreground">
              <BookText className="size-3.5" />
              支持中文书籍 · 短视频脚本
            </span>
            <button
              type="submit"
              disabled={!value.trim()}
              className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground transition-opacity disabled:opacity-40"
              aria-label="发送给 Agent"
            >
              <ArrowUp className="size-4" />
            </button>
          </div>
        </div>
      </form>

      {/* Examples */}
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {examplePrompts.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => {
              setValue(p)
              run(p)
            }}
            className="rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-muted-foreground transition-colors hover:border-brand/40 hover:text-foreground"
          >
            {p}
          </button>
        ))}
      </div>

      {/* Reasoning */}
      {activeQuery && (
        <div className="mt-6 rounded-2xl border border-border bg-card p-5">
          <div className="flex items-start gap-3 border-b border-border pb-4">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <Sparkles className="size-4" />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-medium text-muted-foreground">你的请求</p>
              <p className="truncate text-sm font-medium text-foreground">{activeQuery}</p>
            </div>
          </div>

          <ol className="mt-4 flex flex-col gap-3">
            {reasoningSteps.map((step, i) => {
              const isDone = i < doneCount
              const isActive = i === doneCount && running
              const visible = i <= doneCount
              return (
                <li
                  key={step.label}
                  className={cn(
                    "flex items-start gap-3 transition-opacity",
                    visible ? "opacity-100" : "opacity-30",
                  )}
                >
                  <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center">
                    {isDone ? (
                      <span className="flex size-5 items-center justify-center rounded-full bg-brand text-brand-foreground">
                        <Check className="size-3" />
                      </span>
                    ) : isActive ? (
                      <Loader2 className="size-4 animate-spin text-brand" />
                    ) : (
                      <span className="size-2 rounded-full bg-border" />
                    )}
                  </span>
                  <div className="leading-tight">
                    <p
                      className={cn(
                        "text-sm",
                        isDone || isActive ? "text-foreground" : "text-muted-foreground",
                      )}
                    >
                      {step.label}
                    </p>
                    {isDone && (
                      <p className="mt-0.5 text-xs text-muted-foreground">{step.detail}</p>
                    )}
                  </div>
                </li>
              )
            })}
          </ol>

          {!running && doneCount === reasoningSteps.length && (
            <div className="mt-4 rounded-xl bg-accent px-4 py-3 text-sm text-accent-foreground">
              已完成分析 · 在下方「选题池」查看推荐结果
            </div>
          )}
        </div>
      )}
    </section>
  )
}
