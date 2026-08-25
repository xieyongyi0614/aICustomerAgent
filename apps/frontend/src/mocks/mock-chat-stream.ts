import type {
  ChatSendRequest,
  ChatStreamListeners,
  ChatStreamTransport,
} from "@/api/transport"

import { matchStreamScript } from "./stream-scripts"

interface MockTransportOptions {
  stepDelayMs?: number
}

let mockSessionCounter = 0

function nextMockSessionId(): string {
  mockSessionCounter += 1
  return `mock-s-${Date.now().toString(36)}-${mockSessionCounter}`
}

function wait(ms: number): Promise<void> {
  if (ms <= 0) return Promise.resolve()
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export class MockChatStreamTransport implements ChatStreamTransport {
  private readonly stepDelayMs: number

  constructor(options: MockTransportOptions = {}) {
    this.stepDelayMs = options.stepDelayMs ?? 24
  }

  async send(
    request: ChatSendRequest,
    listeners: ChatStreamListeners,
    signal?: AbortSignal,
  ): Promise<void> {
    if (signal?.aborted) {
      listeners.onClose?.({ aborted: true })
      return
    }

    listeners.onSessionMeta?.({
      sessionId: request.sessionId ?? nextMockSessionId(),
      isNew: !request.sessionId,
    })

    const script = matchStreamScript(request.content)

    if (script.includeTurnMeta) {
      await wait(this.stepDelayMs)
      if (signal?.aborted) {
        listeners.onClose?.({ aborted: true })
        return
      }
      listeners.onEvent({
        type: "turn_meta",
        roleMode: script.roleMode,
        analysis: script.analysis,
      })
    }

    let emittedLines = 0
    for (const line of script.lines) {
      await wait(this.stepDelayMs)
      if (signal?.aborted) {
        listeners.onClose?.({ aborted: true })
        return
      }
      listeners.onEvent({ type: "delta", text: line })
      emittedLines += 1
    }

    await wait(this.stepDelayMs)
    if (signal?.aborted) {
      listeners.onClose?.({ aborted: true })
      return
    }

    const failure = script.failure
    if (failure && emittedLines >= failure.afterLines) {
      listeners.onEvent({
        type: "error",
        message: failure.message,
        code: failure.code,
      })
      listeners.onClose?.({ aborted: false })
      return
    }

    listeners.onEvent({
      type: "done",
      sessionId: request.sessionId ?? undefined,
      turnId: `mock-turn-${Date.now().toString(36)}`,
    })
    listeners.onClose?.({ aborted: false })
  }
}
