import { useChatStore } from "@/stores/chat-store"

export function useActiveUserId(): string {
  const sessionId = useChatStore((s) => s.sessionId)
  return sessionId ?? ""
}
