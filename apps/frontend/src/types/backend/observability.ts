import type { RoleModeDto, TurnAnalysisDto } from "./chat-meta"

export interface CharacterStateSnapshotDto {
  mood: string
  energy: number
  current_topic: string
  inner_state: string
  updated_at: string | null
}

export interface RelationshipSnapshotDto {
  intimacy: number
  trust: number
  familiarity: number
  stage: string
  updated_at: string | null
}

export interface EmotionHistoryItemDto {
  user_emotion: string
  event: string
  behavior: string
  mood_before: string
  mood_after: string
  energy_after: number
  stage_after: string
  created_at: string
}

export interface StateSnapshotDto {
  character_state: CharacterStateSnapshotDto
  relationship_state: RelationshipSnapshotDto
  emotion_history: EmotionHistoryItemDto[]
}

export interface MessageItemDto {
  id: number
  role: "human" | "ai"
  content: string
  created_at: string
}

export interface ConversationMessagesDto {
  conversation_id: string
  messages: MessageItemDto[]
}

export interface MemoryItemDto {
  id: string
  user_id: string
  memory: string
  memory_type: string
  importance: number
  created_at: string
  updated_at: string
}

export interface MemoriesDto {
  user_id: string
  memories: MemoryItemDto[]
}

export type TraceStepStatusDto = "ok" | "degraded" | "error"

export interface TraceStepDto {
  name: string
  status: TraceStepStatusDto
  durationMs: number
  firstTokenMs?: number | null
  error?: string | null
}

export type TurnTraceStatusDto = "pending" | "complete"

export interface TurnTraceDto {
  turn_id: string | null
  status: TurnTraceStatusDto
  role_mode: RoleModeDto | null
  analysis: TurnAnalysisDto | null
  total_ms: number
  steps: TraceStepDto[]
}
