import { useRef, useState } from "react"

import type { KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useChat } from "@/hooks/use-chat"
import { cn } from "@/lib/utils"

function ChatInputBar() {
  const { send, stop, isStreaming } = useChat()
  const [draft, setDraft] = useState("")
  const composingRef = useRef(false)

  const canSend = draft.trim().length > 0 && !isStreaming

  function submit() {
    if (!canSend) return
    const ok = send(draft)
    if (ok) setDraft("")
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || composingRef.current || event.nativeEvent.isComposing) {
      return
    }
    event.preventDefault()
    submit()
  }

  return (
    <div
      data-testid="chat-input-bar"
      className="shrink-0 border-t border-border p-3"
    >
      <Textarea
        data-testid="chat-input"
        placeholder={isStreaming ? "回答生成中…" : "输入消息，Enter 发送 / Shift+Enter 换行"}
        value={draft}
        rows={2}
        className="max-h-40 min-h-[52px] resize-none"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={handleKeyDown}
        onCompositionStart={() => {
          composingRef.current = true
        }}
        onCompositionEnd={() => {
          composingRef.current = false
        }}
      />
      <div className="mt-2 flex items-center justify-end gap-2">
        {isStreaming ? (
          <Button size="sm" variant="destructive" data-testid="stop-button" onClick={() => stop()}>
            Stop
          </Button>
        ) : (
          <Button
            size="sm"
            data-testid="send-button"
            disabled={!canSend}
            onClick={() => submit()}
          >
            Send
          </Button>
        )}
      </div>
      <p
        data-testid="streaming-hint"
        className={cn("mt-1 text-right font-mono text-[10px] text-fg-tertiary", !isStreaming && "invisible")}
      >
        streaming…
      </p>
    </div>
  )
}

export { ChatInputBar }
