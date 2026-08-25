import { useEffect } from "react"

import { MessageList } from "@/components/chat/message-list"
import { Button } from "@/components/ui/button"
import { useAutoScroll } from "@/hooks/use-auto-scroll"
import { useChatStore } from "@/stores/chat-store"

function ChatScrollRegion({ enabled }: { enabled: boolean }) {
  const messages = useChatStore((s) => s.messages)
  const { containerRef, isFollowing, handleScroll, scrollToBottom, resetFollow } =
    useAutoScroll({ contentKey: messages, enabled })

  useEffect(() => {
    if (messages.length === 0) resetFollow()
  }, [messages.length, resetFollow])

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={containerRef}
        data-testid="chat-scroll-container"
        className="h-full overflow-y-auto"
        onScroll={handleScroll}
      >
        <MessageList />
      </div>
      {enabled && !isFollowing ? (
        <Button
          size="sm"
          variant="outline"
          data-testid="jump-to-bottom"
          className="absolute bottom-3 right-4 shadow-sm"
          onClick={() => scrollToBottom()}
        >
          ↓ 回到底部
        </Button>
      ) : null}
    </div>
  )
}

export { ChatScrollRegion }
