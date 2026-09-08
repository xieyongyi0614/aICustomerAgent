import { useChatStore } from "@/stores/chat-store"

const FALLBACK_USER_ID = "default-user"

export function useActiveUserId(): string {
  const sessionId = useChatStore((s) => s.sessionId)
  return sessionId ?? FALLBACK_USER_ID
}