import { ApiError, resolveApiBase } from '@/api/http'
import type {
  ChatSendRequest,
  ChatStreamListeners,
  ChatStreamTransport,
  StreamEvent,
} from '@/api/transport'
import type {
  RoleModeDto,
  TurnAnalysisDto,
} from '@/types/backend/chat-meta'
import type {
  BehaviorDecision,
  RoleMode,
  TurnAnalysis,
} from '@/types/domain/chat-meta'

const CHAT_ENDPOINT = '/api/v1/chat/message'

interface FetchDeps {
  fetchImpl?: typeof fetch
  baseUrl?: string
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null) return null
  return value as Record<string, unknown>
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function asId(value: unknown): string | undefined {
  if (typeof value === 'string') return value
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return undefined
}

export function toRoleMode(dto: RoleModeDto): RoleMode {
  return dto
}

export function toTurnAnalysis(dto: TurnAnalysisDto): TurnAnalysis {
  const userEmotion = {
    emotion: dto.user_emotion.emotion,
    event: dto.user_emotion.event,
  }
  const behavior: BehaviorDecision = {
    behavior: dto.behavior.behavior,
    reason: dto.behavior.reason,
  }
  return { userEmotion, behavior }
}

function parseTypedEvent(record: Record<string, unknown>): StreamEvent | null {
  switch (record.type) {
    case 'delta': {
      const text = asString(record.text)
      if (text === undefined) return null
      return { type: 'delta', text }
    }
    case 'turn_meta': {
      const roleMode = asRecord(record.role_mode) as unknown as RoleModeDto | null
      const analysis = asRecord(record.analysis) as unknown as TurnAnalysisDto | null
      if (roleMode === null || analysis === null) return null
      if (
        typeof roleMode.mode !== 'string' ||
        typeof analysis.user_emotion?.emotion !== 'string' ||
        typeof analysis.behavior?.behavior !== 'string'
      ) {
        return null
      }
      return {
        type: 'turn_meta',
        roleMode: toRoleMode(roleMode),
        analysis: toTurnAnalysis(analysis),
      }
    }
    case 'done': {
      return {
        type: 'done',
        sessionId: asId(record.session_id),
        turnId: asId(record.turn_id),
      }
    }
    case 'error': {
      const message =
        asString(record.message) ?? asString(record.detail) ?? 'unknown stream error'
      return { type: 'error', message, code: asString(record.code) }
    }
    default:
      return null
  }
}

function parseLegacyEvent(record: Record<string, unknown>): StreamEvent | null {
  if ('delta' in record && typeof record.delta === 'string') {
    return { type: 'delta', text: record.delta }
  }
  if (record.done === true) {
    return {
      type: 'done',
      sessionId: asId(record.session_id),
      turnId: asId(record.turn_id),
    }
  }
  if ('detail' in record) {
    const detail = record.detail
    const message =
      typeof detail === 'string' ? detail : JSON.stringify(detail) ?? 'unknown error'
    const errorBody = asRecord(record.error)
    const code =
      errorBody === null || errorBody.code === undefined
        ? undefined
        : String(errorBody.code)
    return { type: 'error', message, code }
  }
  return null
}

export function parseStreamLine(line: string): StreamEvent | null {
  const trimmed = line.trim()
  if (trimmed.length === 0) return null
  let data: unknown
  try {
    data = JSON.parse(trimmed)
  } catch {
    return null
  }
  const record = asRecord(data)
  if (record === null) return null
  if (typeof record.type === 'string') return parseTypedEvent(record)
  return parseLegacyEvent(record)
}

class LineBuffer {
  private pending = ''

  push(chunk: string): string[] {
    this.pending += chunk
    const parts = this.pending.split(/\r?\n/)
    this.pending = parts.pop() ?? ''
    return parts
  }

  flush(): string | null {
    const rest = this.pending
    this.pending = ''
    return rest.length > 0 ? rest : null
  }
}

export class FetchChatStreamTransport implements ChatStreamTransport {
  private readonly fetchImpl: typeof fetch
  private readonly baseUrl: string

  constructor(deps: FetchDeps = {}) {
    this.fetchImpl = deps.fetchImpl ?? fetch.bind(globalThis)
    this.baseUrl = deps.baseUrl ?? resolveApiBase()
  }

  async send(
    request: ChatSendRequest,
    listeners: ChatStreamListeners,
    signal?: AbortSignal,
  ): Promise<void> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${CHAT_ENDPOINT}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: request.sessionId ?? null,
          content: request.content,
        }),
        signal,
      })

      const sessionId = response.headers.get('x-session-id')
      if (sessionId !== null && sessionId.length > 0) {
        listeners.onSessionMeta?.({
          sessionId,
          isNew: response.headers.get('x-session-new') === 'true',
        })
      }

      if (!response.ok) {
        const apiError = await toApiErrorFromResponse(response)
        listeners.onError?.(apiError)
        listeners.onClose?.({ aborted: false })
        return
      }
      if (response.body === null) {
        listeners.onError?.(new ApiError('empty stream body'))
        listeners.onClose?.({ aborted: false })
        return
      }

      await this.consume(response.body, listeners)

      const aborted = signal?.aborted ?? false
      listeners.onClose?.({ aborted })
    } catch (error) {
      if (signal?.aborted) {
        listeners.onClose?.({ aborted: true })
        return
      }
      listeners.onError?.(
        error instanceof ApiError
          ? error
          : new ApiError(error instanceof Error ? error.message : String(error)),
      )
      listeners.onClose?.({ aborted: false })
    }
  }

  private async consume(
    body: ReadableStream<Uint8Array>,
    listeners: ChatStreamListeners,
  ): Promise<void> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    const buffer = new LineBuffer()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      for (const line of buffer.push(decoder.decode(value, { stream: true }))) {
        const event = parseStreamLine(line)
        if (event !== null) listeners.onEvent(event)
      }
    }
    const rest = buffer.flush()
    if (rest !== null) {
      const event = parseStreamLine(rest)
      if (event !== null) listeners.onEvent(event)
    }
  }
}

async function toApiErrorFromResponse(response: Response): Promise<ApiError> {
  let message = `request failed with status ${response.status}`
  let code: string | undefined
  try {
    const data = asRecord(await response.json())
    if (data !== null) {
      if (typeof data.detail === 'string') message = data.detail
      const errorBody = asRecord(data.error)
      if (errorBody !== null && typeof errorBody.message === 'string') {
        message = errorBody.message
      }
      if (errorBody !== null && errorBody.code !== undefined) {
        code = String(errorBody.code)
      }
    }
  } catch {
    return new ApiError(message, { status: response.status, code })
  }
  return new ApiError(message, { status: response.status, code })
}
