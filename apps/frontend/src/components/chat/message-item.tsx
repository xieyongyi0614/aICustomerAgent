import { memo, useEffect, useRef } from "react"

import { TurnBadge } from "@/components/chat/turn-badge"
import { formatRelativeTime } from "@/lib/format"
import type { ChatMessage } from "@/types/domain/chat-message"
import { cn } from "@/lib/utils"

function MessageItemImpl({
  message,
  highlighted = false,
}: {
  message: ChatMessage
  highlighted?: boolean
}) {
  const wrapperRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (highlighted) {
      wrapperRef.current?.scrollIntoView({ block: "center" })
    }
  }, [highlighted])

  const isHuman = message.role === "human"
  return (
    <div
      ref={wrapperRef}
      className={cn(
        "flex w-full",
        isHuman ? "justify-end" : "justify-start",
        highlighted && "rounded-lg ring-2 ring-sky-400/70",
      )}
      data-highlighted={highlighted ? "true" : undefined}
    >
      <div
        data-testid={`message-${message.id}`}
        className={cn(
          "max-w-[85%] rounded-lg border px-3 py-2 text-sm leading-relaxed",
          isHuman
            ? "self-end border-transparent bg-secondary text-secondary-foreground"
            : "self-start border-border bg-card text-card-foreground",
          message.status === "error" && "border-status-error/60",
        )}
      >
        {message.status === "pending" && message.content.length === 0 ? (
          <span className="font-mono text-xs text-muted-foreground">思考中…</span>
        ) : (
          <span className="whitespace-pre-wrap break-words">
            {message.content}
            {message.status === "streaming" ? (
              <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-status-ok align-text-bottom" />
            ) : null}
          </span>
        )}

        {message.status === "stopped" ? (
          <p className="mt-1 font-mono text-[10px] text-fg-tertiary">已停止</p>
        ) : null}
        {message.status === "error" && message.errorText ? (
          <p className="mt-1 break-all font-mono text-[10px] text-status-error">
            {message.errorText}
          </p>
        ) : null}

        {!isHuman && (message.status === "complete" || message.status === "stopped") ? (
          <TurnBadge message={message} />
        ) : null}

        <p
          className={cn(
            "mt-1 text-right font-mono text-[10px] text-fg-tertiary",
            isHuman && "text-secondary-foreground/70",
          )}
        >
          {formatRelativeTime(message.createdAt)}
        </p>
      </div>
    </div>
  )
}

const MessageItem = memo(MessageItemImpl)

export { MessageItem }
