import { useRef, useState } from "react"

import type { KeyboardEvent } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Textarea } from "@/components/ui/textarea"
import { useChat } from "@/hooks/use-chat"
import { useChatStore } from "@/stores/chat-store"
import { cn } from "@/lib/utils"

function ChatInputBar({
  autoScrollEnabled,
  onToggleAutoScroll,
}: {
  autoScrollEnabled: boolean
  onToggleAutoScroll: () => void
}) {
  const { send, stop, isStreaming } = useChat()
  const retry = useChatStore((s) => s.retry)
  const newSession = useChatStore((s) => s.newSession)
  const hasHumanMessage = useChatStore((s) =>
    s.messages.some((m) => m.role === "human"),
  )
  const [draft, setDraft] = useState("")
  const [clearOpen, setClearOpen] = useState(false)
  const composingRef = useRef(false)

  const canSend = draft.trim().length > 0 && !isStreaming
  const canRetry = hasHumanMessage && !isStreaming
  const canClear = !isStreaming

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
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            data-testid="autoscroll-toggle"
            onClick={onToggleAutoScroll}
          >
            AutoScroll {autoScrollEnabled ? "✓" : "✗"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            data-testid="global-retry"
            disabled={!canRetry}
            onClick={() => retry()}
          >
            Retry
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <Dialog
            open={clearOpen}
            onOpenChange={(next) => {
              if (isStreaming) return
              setClearOpen(next)
            }}
          >
            <DialogTrigger
              render={
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid="clear-button"
                  disabled={!canClear}
                />
              }
            >
              Clear
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle className="text-sm">清空当前会话？</DialogTitle>
                <DialogDescription>
                  将清空本地聊天视图并开启新会话；后端已保存的记录不会被删除。
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid="clear-cancel"
                  onClick={() => setClearOpen(false)}
                >
                  取消
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  data-testid="clear-confirm"
                  onClick={() => {
                    setClearOpen(false)
                    newSession()
                  }}
                >
                  确认清空
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          {isStreaming ? (
            <Button
              size="sm"
              variant="destructive"
              data-testid="stop-button"
              onClick={() => stop()}
            >
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
