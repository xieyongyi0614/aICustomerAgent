import { Badge } from "@/components/ui/badge"
import { formatDurationMs } from "@/lib/format"
import { useUiStore } from "@/stores/ui-store"
import type { ChatMessage } from "@/types/domain/chat-message"

function TurnBadge({ message }: { message: ChatMessage }) {
  const openTurnInTrace = useUiStore((s) => s.openTurnInTrace)

  if (message.status !== "complete") return null

  const clickable = message.turnId !== undefined

  function handleClick() {
    if (clickable) {
      openTurnInTrace(message.turnId ?? null)
    }
  }

  if (message.badge === undefined) {
    return (
      <button
        type="button"
        data-testid={`turn-badge-${message.id}`}
        disabled={!clickable}
        onClick={handleClick}
        className="mt-1 inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 font-mono text-[9px] text-fg-tertiary hover:bg-accent disabled:cursor-default disabled:opacity-70"
      >
        {clickable ? "—" : "无观测数据"}
      </button>
    )
  }

  return (
    <button
      type="button"
      data-testid={`turn-badge-${message.id}`}
      onClick={handleClick}
      title={clickable ? "查看本轮 Trace" : undefined}
      className="mt-1 inline-flex items-center gap-1.5 self-start rounded border border-border bg-card px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground transition-colors hover:border-ring hover:text-foreground"
    >
      <Badge variant="outline" className="h-auto px-1 py-0 text-[9px]">
        {message.badge.mode}
      </Badge>
      <span>{message.badge.behavior}</span>
      <span className="tabular-nums">{formatDurationMs(message.badge.durationMs)}</span>
    </button>
  )
}

export { TurnBadge }
