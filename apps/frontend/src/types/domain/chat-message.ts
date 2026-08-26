export type MessageRole = "human" | "ai"

export type MessageStatus =
  | "pending"
  | "streaming"
  | "complete"
  | "stopped"
  | "error"

export type ConnectionStatus = "idle" | "connecting" | "open" | "closed" | "error"

export interface TurnBadgeInfo {
  mode: string
  behavior: string
  durationMs: number
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  status: MessageStatus
  createdAt: number
  errorText?: string
  turnId?: string
  badge?: TurnBadgeInfo
}

export const TERMINAL_MESSAGE_STATUSES: readonly MessageStatus[] = [
  "complete",
  "stopped",
  "error",
]

export function isTerminalMessage(status: MessageStatus): boolean {
  return TERMINAL_MESSAGE_STATUSES.includes(status)
}
