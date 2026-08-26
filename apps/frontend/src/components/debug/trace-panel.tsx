import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { JsonViewer } from "@/features/json-viewer/json-viewer"
import { useTurnTrace, isTraceNotFound, PendingTraceSignal } from "@/hooks/use-observability"
import { formatDurationMs } from "@/lib/format"
import { cn } from "@/lib/utils"
import { buildWaterfallRows } from "@/lib/waterfall"
import { useChatStore } from "@/stores/chat-store"
import { useUiStore } from "@/stores/ui-store"

function StepDot({ status }: { status: string }) {
  const cls =
    status === "warn"
      ? "bg-status-warn"
      : status === "error"
        ? "bg-status-error"
        : "bg-status-ok"
  return <span data-testid={`dot-${status}`} className={cn("inline-block size-2 rounded-full", cls)} />
}

const STATUS_LABEL: Record<string, string> = {
  ok: "ok",
  warn: "degraded",
  error: "error",
}

function TraceSkeleton() {
  return (
    <div data-testid="trace-skeleton" className="flex flex-col gap-2">
      {[0, 1].map((i) => (
        <div key={i} className="h-6 animate-pulse rounded border border-dashed border-border bg-muted/30" />
      ))}
    </div>
  )
}

function TracePanel({
  turnId,
  pollIntervalMs,
}: {
  turnId: string | null
  pollIntervalMs?: number
}) {
  const query = useTurnTrace(turnId, pollIntervalMs ? { pollIntervalMs } : undefined)
  const [selectedName, setSelectedName] = useState<string | null>(null)

  if (turnId === null) {
    return <p className="font-mono text-xs text-fg-tertiary">发送消息后，这里将展示该轮的完整证据链。</p>
  }

  if (isTraceNotFound(query.error)) {
    return (
      <div data-testid="trace-notfound" className="rounded-md border border-status-warn/50 p-3">
        <p className="text-xs text-status-warn">该轮数据已被清理，重发一轮以采集</p>
      </div>
    )
  }

  if (query.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <p className="font-mono text-[10px] text-fg-tertiary">加载 trace…</p>
        <TraceSkeleton />
      </div>
    )
  }

  if (query.isError) {
    if (query.error instanceof PendingTraceSignal) {
      return (
        <div data-testid="trace-timeout" className="flex flex-col gap-2 rounded-md border border-status-warn/50 p-3">
          <p className="text-xs text-status-warn">后处理未完成（轮询超时）</p>
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            手动刷新
          </Button>
        </div>
      )
    }
    return (
      <div data-testid="trace-error" className="rounded-md border border-status-error/50 p-3">
        <p className="text-xs text-status-error">{String(query.error)}</p>
        <Button size="sm" variant="outline" onClick={() => query.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  const trace = query.data
  const rows = buildWaterfallRows(trace.steps)
  const degradedCount = rows.filter((r) => r.step.status === "warn").length
  const selected = trace.steps.find((s) => s.name === selectedName) ?? null

  let backgroundDividerRendered = false

  return (
    <div data-testid="trace-panel" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span data-testid="trace-summary" className="font-mono text-[10px] text-fg-tertiary">
          总耗时 {formatDurationMs(trace.totalMs)} · {rows.length} 步
          {degradedCount > 0 ? ` · ⚠${degradedCount} 项降级` : ""}
          {trace.status === "pending" ? " · 后处理进行中…" : ""}
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 font-mono text-[10px]"
          data-testid="trace-refresh"
          onClick={() => query.refetch()}
        >
          刷新
        </Button>
      </div>

      <div className="flex flex-col gap-1" data-testid="trace-waterfall">
        {rows.map((row) => {
          const divider = row.isBackground && !backgroundDividerRendered
          if (divider) backgroundDividerRendered = true
          return (
            <div key={row.step.name} data-testid={`trace-row-${row.step.name}`}>
              {divider ? (
                <div className="my-1 flex items-center gap-2">
                  <span className="h-px flex-1 border-t border-dashed border-border" />
                  <span className="font-mono text-[9px] text-fg-tertiary">done 之后 · 异步后处理</span>
                </div>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  setSelectedName(row.step.name)
                  if (row.step.name === "llm") {
                    const aiMessage = useChatStore
                      .getState()
                      .messages.find(
                        (m) => m.role === "ai" && m.turnId === trace.turnId,
                      )
                    if (aiMessage !== undefined) {
                      useUiStore.getState().setHighlightMessageId(aiMessage.id)
                    }
                  }
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-1 py-0.5 text-left hover:bg-accent",
                  row.isBackground && "border border-dashed border-border/70",
                  selectedName === row.step.name && "bg-accent",
                )}
              >
                <StepDot status={row.step.status} />
                <span
                  className={cn(
                    "w-32 shrink-0 truncate font-mono text-[11px]",
                    row.isUnknown && "italic text-fg-tertiary",
                  )}
                  title={row.step.name}
                >
                  {row.isParallel ? "∥ " : ""}
                  {row.step.name}
                </span>
                <span className="h-1.5 min-w-[4%] rounded-full bg-primary/70" style={{ width: `${row.barPct}%` }} />
                <span className="ml-auto shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                  {formatDurationMs(row.step.durationMs)}
                  {row.step.firstTokenMs !== null ? (
                    <span className="ml-1 text-fg-tertiary">
                      · 首字{formatDurationMs(row.step.firstTokenMs)}
                    </span>
                  ) : null}
                </span>
                {row.step.status !== "ok" ? (
                  <Badge
                    variant="outline"
                    className={cn(
                      "shrink-0 font-mono text-[9px]",
                      row.step.status === "warn"
                        ? "bg-amber-500/15 text-amber-300 border-amber-500/40"
                        : "bg-red-500/15 text-red-300 border-red-500/40",
                    )}
                  >
                    {STATUS_LABEL[row.step.status]}
                  </Badge>
                ) : null}
              </button>
            </div>
          )
        })}
      </div>

      {selected !== null ? (
        <div
          data-testid="trace-step-detail"
          className="rounded-md border border-border p-3 text-xs"
        >
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[11px] font-semibold">{selected.name}</span>
            <Button
              size="sm"
              variant="ghost"
              className="h-5 px-1.5 font-mono text-[10px]"
              onClick={() => setSelectedName(null)}
            >
              关闭
            </Button>
          </div>
          <dl className="grid grid-cols-[64px_1fr] items-baseline gap-y-1 font-mono text-[10px]">
            <dt className="text-fg-tertiary">status</dt>
            <dd>{STATUS_LABEL[selected.status]}</dd>
            <dt className="text-fg-tertiary">duration</dt>
            <dd className="tabular-nums">{formatDurationMs(selected.durationMs)}</dd>
            {selected.firstTokenMs !== null ? (
              <>
                <dt className="text-fg-tertiary">first token</dt>
                <dd className="tabular-nums">{formatDurationMs(selected.firstTokenMs)}</dd>
              </>
            ) : null}
          </dl>
          {selected.status === "error" && selected.error ? (
            <pre className="mt-2 whitespace-pre-wrap break-all rounded bg-status-error/10 p-2 font-mono text-[10px] text-status-error">
              {selected.error}
            </pre>
          ) : null}
          {selected.status === "warn" ? (
            <p className="mt-2 text-[10px] text-status-warn">
              该步骤走了降级路径（默认值 / 规则兜底），回答仍正常生成。
            </p>
          ) : null}
          <details className="mt-2">
            <summary className="cursor-pointer font-mono text-[10px] text-fg-tertiary">
              input / output（后端暂未记录明细）
            </summary>
            <JsonViewer data={{ note: "step payload 未采集" }} />
          </details>
        </div>
      ) : null}
    </div>
  )
}

export { TracePanel }
