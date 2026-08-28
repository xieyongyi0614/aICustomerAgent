import type { ApiError } from '@/api/http'
import type {
  RoleMode,
  SceneIntentResult,
  SceneState,
  TurnAnalysis,
} from '@/types/domain/chat-meta'

export interface ChatSendRequest {
  sessionId?: string | null
  content: string
  profileId?: string | null
}

export interface SessionMeta {
  sessionId: string
  isNew: boolean
}

export interface TurnMetaEvent {
  type: 'turn_meta'
  roleMode: RoleMode
  analysis: TurnAnalysis
  sceneIntent?: SceneIntentResult
  sceneState?: SceneState
}

export type StreamEvent =
  | { type: 'delta'; text: string }
  | TurnMetaEvent
  | { type: 'done'; sessionId?: string; turnId?: string }
  | { type: 'error'; message: string; code?: string }

export interface ChatStreamListeners {
  onSessionMeta?(meta: SessionMeta): void
  onEvent(event: StreamEvent): void
  onError?(error: ApiError): void
  onClose?(info: { aborted: boolean }): void
}

export interface ChatStreamTransport {
  send(
    request: ChatSendRequest,
    listeners: ChatStreamListeners,
    signal?: AbortSignal,
  ): Promise<void>
}
