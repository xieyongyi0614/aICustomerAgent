import { useChatStore } from "@/stores/chat-store"

export function useChat() {
  const send = useChatStore((s) => s.send)
  const stop = useChatStore((s) => s.stop)
  const isStreaming = useChatStore((s) => s.streamingMessageId !== null)

  return { send, stop, isStreaming }
}
