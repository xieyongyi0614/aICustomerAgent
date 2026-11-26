export const qk = {
  state: (userId: string) => ["state", userId] as const,
  memories: (userId: string) => ["memories", userId] as const,
  messages: (conversationId: string) => ["messages", conversationId] as const,
  turnTrace: (turnId: string) => ["trace", turnId] as const,
  llmProfiles: ["llm-profiles"] as const,
  worldSimulation: (userId: string) => ["world-simulation", userId] as const,
  worldPlan: (userId: string, date: string) => ["world-plan", userId, date] as const,
  worldSituations: (userId: string, includeExpired: boolean) =>
    ["world-situations", userId, includeExpired] as const,
}
