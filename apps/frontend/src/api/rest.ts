import { requestJson } from "@/api/http"
import type { RoleMode } from "@/types/domain/chat-meta"
import type {
  ChatHistoryMessage,
  EmotionHistoryEntry,
  MemoryRecord,
  RelationshipEventView,
  RelationshipView,
  StateSnapshot,
  TraceStep,
  TraceStepStatus,
  TurnTrace,
} from "@/types/domain/observability"
import { isDefaultAnalysisCombo } from "@/lib/degradation"
import type {
  CharacterStateSnapshotDto,
  ConversationMessagesDto,
  MemoriesDto,
  MemoryItemDto,
  MessageItemDto,
  RelationshipEventDto,
  RelationshipSnapshotDto,
  StateSnapshotDto,
  TraceStepDto,
  TurnTraceDto,
} from "@/types/backend/observability"

function mapCharacterState(dto: CharacterStateSnapshotDto) {
  return {
    mood: dto.mood,
    energy: dto.energy,
    currentTopic: dto.current_topic,
    innerState: dto.inner_state,
    updatedAt: dto.updated_at,
    intensity: dto.intensity ?? 0.3,
    cause: dto.cause ?? "",
    lastEventAt: dto.last_event_at ?? null,
  }
}

function mapRelationship(dto: RelationshipSnapshotDto): RelationshipView {
  return {
    intimacy: dto.intimacy,
    trust: dto.trust,
    familiarity: dto.familiarity,
    tension: dto.tension ?? 0.0,
    stage: dto.stage,
    updatedAt: dto.updated_at,
  }
}

function mapRelationshipEvents(
  items: RelationshipEventDto[],
): RelationshipEventView[] {
  return items.map((item) => ({
    type: item.type,
    magnitude: item.magnitude,
    impactTrust: item.impact_trust,
    impactIntimacy: item.impact_intimacy,
    impactFamiliarity: item.impact_familiarity,
    impactTension: item.impact_tension,
    source: item.source,
    cause: item.cause,
    createdAt: item.created_at,
  }))
}

function mapEmotionHistory(items: StateSnapshotDto["emotion_history"]): EmotionHistoryEntry[] {
  return items.map((item) => ({
    emotion: item.user_emotion,
    event: item.event,
    behavior: item.behavior,
    moodBefore: item.mood_before,
    moodAfter: item.mood_after,
    energyAfter: item.energy_after,
    stageAfter: item.stage_after,
    createdAt: item.created_at,
  }))
}

export async function fetchState(userId: string): Promise<StateSnapshot> {
  const dto = await requestJson<StateSnapshotDto>(
    `/api/v1/state?user_id=${encodeURIComponent(userId)}`,
  )
  return {
    characterState: mapCharacterState(dto.character_state),
    relationship: mapRelationship(dto.relationship_state),
    emotionHistory: mapEmotionHistory(dto.emotion_history),
    relationshipEvents: mapRelationshipEvents(dto.relationship_events ?? []),
  }
}

function mapMessage(dto: MessageItemDto): ChatHistoryMessage {
  return {
    id: dto.id,
    role: dto.role,
    content: dto.content,
    createdAt: dto.created_at,
  }
}

export async function fetchConversationMessages(
  conversationId: string,
  limit = 200,
): Promise<ChatHistoryMessage[]> {
  const dto = await requestJson<ConversationMessagesDto>(
    `/api/v1/conversations/${encodeURIComponent(conversationId)}/messages?limit=${limit}`,
  )
  return dto.messages.map(mapMessage)
}

function mapMemory(dto: MemoryItemDto): MemoryRecord {
  return {
    id: dto.id,
    memory: dto.memory,
    memoryType: dto.memory_type,
    importance: dto.importance,
    createdAt: dto.created_at,
    hitThisTurn: false,
    type: dto.type ?? dto.memory_type,
    status: dto.status ?? "active",
    source: dto.source,
    confidence: dto.confidence,
    supersededBy: dto.superseded_by ?? null,
  }
}

export async function fetchMemories(userId: string, limit = 50): Promise<MemoryRecord[]> {
  const dto = await requestJson<MemoriesDto>(
    `/api/v1/memories?user_id=${encodeURIComponent(userId)}&limit=${limit}`,
  )
  return dto.memories.map(mapMemory)
}

const TRACE_STEP_STATUS_MAP: Record<TraceStepDto["status"], TraceStepStatus> = {
  ok: "ok",
  degraded: "warn",
  error: "error",
}

function mapTurnTrace(dto: TurnTraceDto, turnId: string): TurnTrace {
  const steps: TraceStep[] = dto.steps.map((step) => ({
    name: step.name,
    status: TRACE_STEP_STATUS_MAP[step.status],
    durationMs: step.durationMs,
    firstTokenMs: step.firstTokenMs ?? null,
    error: step.error ?? null,
  }))
  return {
    turnId: dto.turn_id ?? turnId,
    status: dto.status,
    roleMode: (dto.role_mode as unknown as RoleMode) ?? null,
    analysis:
      dto.analysis === null
        ? null
        : {
            userEmotion: dto.analysis.user_emotion,
            behavior: dto.analysis.behavior,
          },
    totalMs: dto.total_ms,
    steps,
    degradedSteps: steps.filter((s) => s.status === "warn").map((s) => s.name),
  }
}

export function traceHasRouterDegradation(trace: TurnTrace | undefined): boolean {
  if (!trace?.roleMode) return false
  if (trace.degradedSteps.includes("role_router")) return true
  if (trace.analysis !== null && isDefaultAnalysisCombo(trace.analysis)) return true
  return (trace.roleMode.confidence ?? 1) < 0.5
}

export async function fetchTurnTrace(turnId: string): Promise<TurnTrace> {
  const dto = await requestJson<TurnTraceDto>(
    `/api/v1/debug/turns/${encodeURIComponent(turnId)}/trace`,
  )
  return mapTurnTrace(dto, turnId)
}
