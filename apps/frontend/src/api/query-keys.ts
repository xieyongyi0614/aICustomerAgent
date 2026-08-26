export const qk = {
  state: (userId: string) => ["state", userId] as const,
  memories: (userId: string) => ["memories", userId] as const,
  messages: (conversationId: string) => ["messages", conversationId] as const,
  turnTrace: (turnId: string) => ["trace", turnId] as const,
}
