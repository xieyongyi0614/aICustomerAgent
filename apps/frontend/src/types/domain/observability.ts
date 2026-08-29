import type { RoleMode, TurnAnalysis } from "./chat-meta"

export type TraceStepStatus = "ok" | "warn" | "error"
export type TurnTraceStatus = "pending" | "complete"

export interface RelationshipEventView {
  type: string
  magnitude: string
  impactTrust: number
  impactIntimacy: number
  impactFamiliarity: number
  impactTension: number
  source: string
  cause: string
  createdAt: string
}

export interface CharacterStateView {
  mood: string
  energy: number
  currentTopic: string
  innerState: string
  updatedAt: string | null
  intensity: number
  cause: string
  lastEventAt: string | null
}

export interface RelationshipView {
  intimacy: number
  trust: number
  familiarity: number
  tension: number
  stage: string
  updatedAt: string | null
}

export interface EmotionHistoryEntry {
  emotion: string
  event: string
  behavior: string
  moodBefore: string
  moodAfter: string
  energyAfter: number
  stageAfter: string
  createdAt: string
}

export interface StateSnapshot {
  relationshipEvents: RelationshipEventView[]
  characterState: CharacterStateView
  relationship: RelationshipView
  emotionHistory: EmotionHistoryEntry[]
}

export interface ChatHistoryMessage {
  id: number
  role: "human" | "ai"
  content: string
  createdAt: string
}

export type MemoryStatus = "active" | "superseded" | "invalidated"

export interface MemoryRecord {
  id: string
  memory: string
  memoryType: string
  importance: number
  createdAt: string
  hitThisTurn: boolean
  type?: string
  status?: MemoryStatus
  source?: string
  confidence?: number
  supersededBy?: string | null
}

export interface TraceStep {
  name: string
  status: TraceStepStatus
  durationMs: number
  firstTokenMs: number | null
  error: string | null
}

export interface TurnTrace {
  turnId: string | null
  status: TurnTraceStatus
  roleMode: RoleMode | null
  analysis: TurnAnalysis | null
  totalMs: number
  steps: TraceStep[]
  degradedSteps: string[]
}
