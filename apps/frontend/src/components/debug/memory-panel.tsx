import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MeterBar } from "@/components/ui/meter-bar"
import { MEMORY_IMPORTANCE_SAVE_THRESHOLD } from "@/lib/memory-thresholds"
import { formatRelativeTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { MemoryRecord, TurnTrace } from "@/types/domain/observability"
import { useMemories } from "@/hooks/use-observability"

const CONTENT_PREVIEW_LENGTH = 24

function MemoryItem({ item }: { item: MemoryRecord }) {
  const [expanded, setExpanded] = useState(false)
  const needsTruncation = item.memory.length > CONTENT_PREVIEW_LENGTH

  return (
    <li className="rounded-md border border-border p-2.5" data-testid="memory-item">
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          className={cn(
            "min-w-0 flex-1 text-left text-xs leading-relaxed",
            !expanded && "truncate",
          )}
          data-testid={`memory-content-${item.id}`}
          onClick={() => setExpanded(!expanded)}
        >
          {item.memory}
        </button>
        <Badge variant="outline" className={cn("shrink-0 font-mono", "bg-slate-400/15 text-slate-300 border-slate-400/40")}>
          {item.memoryType}
        </Badge>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <span className="font-mono text-[10px] uppercase text-fg-tertiary">imp</span>
        <MeterBar
          value={item.importance}
          ticks={[MEMORY_IMPORTANCE_SAVE_THRESHOLD]}
          toneClassName={
            item.importance >= MEMORY_IMPORTANCE_SAVE_THRESHOLD
              ? "bg-status-ok"
              : "bg-status-warn"
          }
          className="max-w-[140px]"
        />
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          {item.importance.toFixed(2)}
        </span>
        <span className="ml-auto font-mono text-[10px] text-fg-tertiary">
          {formatRelativeTime(new Date(item.createdAt).getTime())}
        </span>
      </div>
      {needsTruncation ? (
        <p className="mt-1 font-mono text-[10px] text-fg-tertiary">
          {expanded ? "已展开全部" : "点击查看完整"}
        </p>
      ) : null}
    </li>
  )
}

function ExtractorDecisionCard({ turnTrace }: { turnTrace: TurnTrace | null }) {
  const step =
    turnTrace?.steps.find((s) => s.name === "memory_extractor") ?? null

  return (
    <Card data-testid="extractor-decision-card">
      <CardHeader className="pb-1">
        <CardTitle className="font-mono text-xs">本轮记忆提取</CardTitle>
      </CardHeader>
      <CardContent className="text-xs">
        {step === null ? (
          <p className="font-mono text-[10px] text-fg-tertiary">未记录</p>
        ) : (
          <div className="flex items-center gap-2 font-mono text-[10px]">
            <Badge
              variant="outline"
              className={
                step.status === "error"
                  ? "bg-red-500/15 text-red-300 border-red-500/40"
                  : "bg-emerald-500/15 text-emerald-300 border-emerald-500/40"
              }
            >
              {step.status}
            </Badge>
            <span className="tabular-nums">{step.durationMs.toFixed(1)}ms</span>
            <span className="text-fg-tertiary">决策明细待后端输出</span>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

interface MemoryPanelProps {
  userId?: string
  turnTrace?: TurnTrace | null
}

function MemoryPanelInner({
  userId,
  turnTrace,
}: {
  userId: string
  turnTrace: TurnTrace | null
}) {
  const query = useMemories(userId)
  const [view, setView] = useState<"all" | "hits">("all")

  return (
    <div data-testid="memory-panel" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-fg-tertiary">user: {userId}</span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 font-mono text-[10px]"
          data-testid="memory-refresh"
          onClick={() => query.refetch()}
        >
          刷新
        </Button>
      </div>

      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant={view === "all" ? "secondary" : "ghost"}
          className="h-7 px-2 font-mono text-[10px]"
          data-testid="view-all"
          onClick={() => setView("all")}
        >
          全部记忆
        </Button>
        <span title="依赖后端检索留痕，Phase 后续开放">
          <Button
            size="sm"
            variant={view === "hits" ? "secondary" : "ghost"}
            className="h-7 px-2 font-mono text-[10px]"
            data-testid="view-hits"
            disabled
          >
            本轮命中
          </Button>
        </span>
      </div>

      {query.isPending ? (
        <div data-testid="memory-skeleton" className="h-32 animate-pulse rounded-md border border-border bg-muted/40" />
      ) : query.isError || query.data === undefined ? (
        <div
          data-testid="memory-error"
          className="flex flex-col items-start gap-2 rounded-md border border-status-error/50 p-3"
        >
          <p className="text-xs text-status-error">记忆列表加载失败</p>
          <p className="font-mono text-[10px] text-fg-tertiary">{String(query.error)}</p>
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            重试
          </Button>
        </div>
      ) : view === "all" ? (
        query.data.length === 0 ? (
          <p data-testid="memory-empty" className="font-mono text-xs text-fg-tertiary">
            还没有长期记忆——聊点个人偏好试试
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {query.data.map((item) => (
              <MemoryItem key={item.id} item={item} />
            ))}
          </ul>
        )
      ) : null}

      <ExtractorDecisionCard turnTrace={turnTrace} />
    </div>
  )
}

function MemoryPanel(props: MemoryPanelProps) {
  const userId = props.userId ?? "default-user"
  return (
    <MemoryPanelInner key={userId} userId={userId} turnTrace={props.turnTrace ?? null} />
  )
}

export { MemoryPanel }
export type { MemoryPanelProps }
