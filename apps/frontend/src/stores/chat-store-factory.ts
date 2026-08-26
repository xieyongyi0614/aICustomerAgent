import { create } from "zustand"

import type { ChatStreamTransport, StreamEvent } from "@/api/transport"
import type { RoleMode, TurnAnalysis } from "@/types/domain/chat-meta"
import type { ChatMessage, ConnectionStatus } from "@/types/domain/chat-message"

export type ChatStore = ChatState & ChatActions

interface ChatState {
  messages: ChatMessage[]
  streamingMessageId: string | null
  sessionId: string | null
  connectionStatus: ConnectionStatus
  turnMeta: { roleMode: RoleMode; analysis: TurnAnalysis } | null
  lastTurnId: string | null
}

interface ChatActions {
  send(content: string): boolean
  stop(): void
  newSession(): void
  retry(): boolean
  _hardReset(): void
}

function createId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function createChatStore(transport: ChatStreamTransport) {
  let activeController: AbortController | null = null

  return create<ChatStore>()((set, get) => ({
    messages: [],
    streamingMessageId: null,
    sessionId: null,
    connectionStatus: "idle",
    turnMeta: null,
    lastTurnId: null,

    send(content) {
      const trimmed = content.trim()
      if (trimmed.length === 0) return false
      if (get().streamingMessageId !== null) return false
      if (activeController !== null) return false

      const controller = new AbortController()
      activeController = controller
      const assistantId = createId()
      const humanMessage: ChatMessage = {
        id: createId(),
        role: "human",
        content: trimmed,
        status: "complete",
        createdAt: Date.now(),
      }
      const assistantMessage: ChatMessage = {
        id: assistantId,
        role: "ai",
        content: "",
        status: "pending",
        createdAt: Date.now(),
      }

      set((state) => ({
        messages: [...state.messages, humanMessage, assistantMessage],
        streamingMessageId: assistantId,
        connectionStatus: "connecting",
        turnMeta: null,
        lastTurnId: null,
      }))

      let turnActive = true

      const finalizeTerminal = (patch: Partial<ChatMessage>) => {
        if (!turnActive) return
        turnActive = false
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === assistantId ? { ...m, ...patch } : m,
          ),
          streamingMessageId:
            state.streamingMessageId === assistantId ? null : state.streamingMessageId,
        }))
        activeController = null
      }

      const applyDelta = (text: string) => {
        if (!turnActive) return
        set((state) => ({
          messages: state.messages.map((m) =>
            m.id === assistantId
              ? { ...m, content: m.content + text, status: "streaming" as const }
              : m,
          ),
          connectionStatus: "open",
        }))
      }

      const listeners = {
        onSessionMeta: (meta: { sessionId: string; isNew: boolean }) => {
          if (!turnActive) return
          if (get().sessionId === null || meta.isNew) {
            set({ sessionId: meta.sessionId })
          }
        },
        onEvent: (event: StreamEvent) => {
          switch (event.type) {
            case "delta":
              applyDelta(event.text)
              break
            case "turn_meta":
              if (!turnActive) break
              set({
                turnMeta: { roleMode: event.roleMode, analysis: event.analysis },
              })
              break
            case "done":
              if (!turnActive) break
              finalizeTerminal({
                status: "complete",
                turnId: event.turnId,
                badge: {
                  mode: get().turnMeta?.roleMode.mode ?? "—",
                  behavior: get().turnMeta?.analysis.behavior.behavior ?? "—",
                  durationMs: Date.now() - assistantMessage.createdAt,
                },
              })
              set((state) => ({
                connectionStatus: "closed",
                lastTurnId: event.turnId ?? state.lastTurnId,
              }))
              break
            case "error":
              if (!turnActive) break
              finalizeTerminal({ status: "error", errorText: event.message })
              set({ connectionStatus: "error" })
              break
          }
        },
        onError: (error: Error) => {
          if (!turnActive) return
          finalizeTerminal({ status: "error", errorText: error.message })
          set({ connectionStatus: "error" })
        },
        onClose: (info: { aborted: boolean }) => {
          if (!turnActive) {
            activeController = null
            return
          }
          if (info.aborted) {
            finalizeTerminal({ status: "stopped" })
            set({ connectionStatus: "closed" })
          }
        },
      }

      void transport.send(
        { sessionId: get().sessionId, content: trimmed },
        listeners,
        controller.signal,
      )
      return true
    },

    stop() {
      activeController?.abort()
    },

    retry() {
      const state = get()
      if (state.streamingMessageId !== null) return false
      let lastHumanIndex = -1
      for (let i = state.messages.length - 1; i >= 0; i -= 1) {
        if (state.messages[i].role === "human") {
          lastHumanIndex = i
          break
        }
      }
      if (lastHumanIndex === -1) return false
      const content = state.messages[lastHumanIndex].content
      set({
        messages: state.messages.slice(0, lastHumanIndex),
      })
      return get().send(content)
    },

    newSession() {
      if (get().streamingMessageId !== null) return
      activeController?.abort()
      activeController = null
      set({
        messages: [],
        streamingMessageId: null,
        sessionId: null,
        connectionStatus: "idle",
        turnMeta: null,
        lastTurnId: null,
      })
    },

    _hardReset() {
      activeController?.abort()
      activeController = null
      set({
        messages: [],
        streamingMessageId: null,
        sessionId: null,
        connectionStatus: "idle",
        turnMeta: null,
        lastTurnId: null,
      })
    },
  }))
}
