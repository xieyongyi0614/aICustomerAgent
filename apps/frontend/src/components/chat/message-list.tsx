import { MessageItem } from "@/components/chat/message-item"
import { useChatStore } from "@/stores/chat-store"
import { useUiStore } from "@/stores/ui-store"

function EmptyConversationGuide() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
      <p className="text-sm text-muted-foreground">和亚丝娜打个招呼吧</p>
      <p className="font-mono text-xs text-fg-tertiary">
        试试：今天加班到现在，有点撑不住了
      </p>
    </div>
  )
}

function MessageList() {
  const messages = useChatStore((s) => s.messages)
  const highlightMessageId = useUiStore((s) => s.highlightMessageId)
  if (messages.length === 0) {
    return <EmptyConversationGuide />
  }
  return (
    <div data-testid="messages-container" className="flex flex-col gap-3 p-4">
      {messages.map((message) => (
        <MessageItem
          key={message.id}
          message={message}
          highlighted={highlightMessageId === message.id}
        />
      ))}
    </div>
  )
}

export { MessageList }
