import { beforeEach, describe, expect, it } from "vitest"

import { createChatStore } from "./chat-store-factory"
import type {
  ChatSendRequest,
  ChatStreamListeners,
  ChatStreamTransport,
  StreamEvent,
} from "@/api/transport"
import type { SessionMeta } from "@/api/transport"

class ControlledTransport implements ChatStreamTransport {
  lastRequest: ChatSendRequest | null = null
  lastSignal: AbortSignal | null = null
  private listeners: ChatStreamListeners | null = null

  async send(
    request: ChatSendRequest,
    listeners: ChatStreamListeners,
    signal?: AbortSignal,
  ): Promise<void> {
    this.lastRequest = request
    this.lastSignal = signal ?? null
    this.listeners = listeners
  }

  meta(sessionId: string, isNew = true): void {
    const m: SessionMeta = { sessionId, isNew }
    this.listeners?.onSessionMeta?.(m)
  }

  emit(event: StreamEvent): void {
    this.listeners?.onEvent(event)
  }

  fail(error: Error): void {
    this.listeners?.onError?.(error)
  }

  close(aborted: boolean): void {
    this.listeners?.onClose?.({ aborted })
  }
}

function setup() {
  const transport = new ControlledTransport()
  const store = createChatStore(transport)
  return { transport, store }
}

const DELTA_A: StreamEvent = { type: "delta", text: "你好" }
const DELTA_B: StreamEvent = { type: "delta", text: "，我是亚丝娜。" }

function assistantOf(store: ReturnType<typeof createChatStore>) {
  const state = store.getState()
  return state.messages.find((m) => m.role === "ai")
}

describe("chat store", () => {
  let harness: ReturnType<typeof setup>

  beforeEach(() => {
    harness = setup()
  })

  it("runs the happy path: pending → streaming → complete with session backfill", () => {
    const { store, transport } = harness
    expect(store.getState().send("你好")).toBe(true)

    expect(store.getState().messages).toHaveLength(2)
    expect(store.getState().messages[0]).toMatchObject({
      role: "human",
      content: "你好",
      status: "complete",
    })
    expect(store.getState().messages[1]).toMatchObject({ role: "ai", status: "pending" })
    expect(store.getState().connectionStatus).toBe("connecting")

    transport.meta("s-new", true)
    expect(store.getState().sessionId).toBe("s-new")

    transport.emit(DELTA_A)
    let assistant = assistantOf(store)
    expect(assistant).toMatchObject({ content: "你好", status: "streaming" })
    expect(store.getState().connectionStatus).toBe("open")

    transport.emit(DELTA_B)
    assistant = assistantOf(store)
    expect(assistant?.content).toBe("你好，我是亚丝娜。")

    transport.emit({
      type: "turn_meta",
      roleMode: {
        mode: "immersive",
        intent: "emotional",
        confidence: 0.9,
        reason: "r",
      },
      analysis: {
        userEmotion: { emotion: "calm", event: "daily" },
        behavior: { behavior: "normal_reply", reason: "" },
      },
    })
    expect(store.getState().turnMeta?.roleMode.mode).toBe("immersive")

    transport.emit({ type: "done", sessionId: "s-new", turnId: "t-1" })
    assistant = assistantOf(store)
    expect(assistant).toMatchObject({ status: "complete", content: "你好，我是亚丝娜。" })
    expect(store.getState().streamingMessageId).toBeNull()
    expect(store.getState().connectionStatus).toBe("closed")
    expect(store.getState().lastTurnId).toBe("t-1")

    transport.close(false)
    expect(store.getState().connectionStatus).toBe("closed")
  })

  it("marks the message stopped on abort and swallows late events", () => {
    const { store, transport } = harness
    store.getState().send("hi")
    transport.emit(DELTA_A)

    store.getState().stop()
    expect(transport.lastSignal?.aborted).toBe(true)

    transport.close(true)
    expect(assistantOf(store)).toMatchObject({ status: "stopped", content: "你好" })
    expect(store.getState().connectionStatus).toBe("closed")
    expect(store.getState().streamingMessageId).toBeNull()

    transport.emit(DELTA_B)
    transport.emit({ type: "done", turnId: "late" })
    expect(assistantOf(store)?.status).toBe("stopped")
    expect(store.getState().lastTurnId).toBeNull()
  })

  it("lands on error terminal and is not overridden by later close", () => {
    const { store, transport } = harness
    store.getState().send("hi")
    transport.emit(DELTA_A)
    transport.emit({ type: "error", message: "LLM 调用失败", code: "x" })

    expect(assistantOf(store)).toMatchObject({ status: "error", errorText: "LLM 调用失败" })
    expect(store.getState().connectionStatus).toBe("error")
    expect(store.getState().streamingMessageId).toBeNull()

    transport.close(false)
    expect(assistantOf(store)?.status).toBe("error")
  })

  it("surfaces onError as an error-terminal message", () => {
    const { store, transport } = harness
    store.getState().send("hi")
    transport.fail(new Error("network down"))
    transport.close(false)

    const assistant = assistantOf(store)
    expect(assistant).toMatchObject({ status: "error", errorText: "network down" })
    expect(store.getState().connectionStatus).toBe("error")
  })

  it("rejects concurrent sends and blank content", () => {
    const { store } = harness
    expect(store.getState().send("第一轮")).toBe(true)
    expect(store.getState().send("并发")).toBe(false)
    expect(store.getState().messages).toHaveLength(2)

    const idleStore = createChatStore(new ControlledTransport())
    expect(idleStore.getState().send("   ")).toBe(false)
    expect(idleStore.getState().messages).toHaveLength(0)
  })

  it("newSession clears state but is refused while streaming", () => {
    const { store, transport } = harness
    store.getState().send("hi")
    transport.meta("s-1", true)
    transport.emit({ type: "done", sessionId: "s-1" })
    transport.close(false)
    expect(store.getState().sessionId).toBe("s-1")

    store.getState().newSession()
    expect(store.getState()).toMatchObject({
      messages: [],
      sessionId: null,
      connectionStatus: "idle",
      turnMeta: null,
    })

    store.getState().send("下一轮")
    store.getState().newSession()
    expect(store.getState().messages).toHaveLength(2)
  })

  it("keeps existing session when meta reports isNew=false", () => {
    const { store, transport } = harness
    store.getState().send("第二轮")
    transport.meta("existing", false)
    expect(store.getState().sessionId).toBe("existing")
  })

  it("setSessionId updates and persists the session id when idle", () => {
    const { store } = harness
    store.getState().setSessionId("fixed-id")
    expect(store.getState().sessionId).toBe("fixed-id")
  })

  it("refuses setSessionId while streaming or blank", () => {
    const { store, transport } = harness
    store.getState().send("进行中")
    store.getState().setSessionId("new-id")
    expect(store.getState().sessionId).toBeNull()

    transport.close(false)
    store.getState()._hardReset()
    store.getState().setSessionId("   ")
    expect(store.getState().sessionId).toBeNull()
  })

  it("retry removes the last turn and resends the same human content", () => {
    const { store, transport } = harness
    store.getState().send("第一问")
    transport.emit(DELTA_A)
    transport.emit({ type: "error", message: "boom" })
    expect(store.getState().messages).toHaveLength(2)

    expect(store.getState().retry()).toBe(true)

    const messages = store.getState().messages
    expect(messages).toHaveLength(2)
    expect(messages[0]).toMatchObject({ role: "human", content: "第一问", status: "complete" })
    expect(messages[1].status === "pending" || messages[1].status === "streaming").toBe(
      true,
    )
    expect(transport.lastRequest?.content).toBe("第一问")

    transport.emit({ type: "delta", text: "修复后回答" })
    transport.emit({ type: "done", turnId: "t-2" })
    expect(assistantOf(store)).toMatchObject({
      status: "complete",
      content: "修复后回答",
    })
  })

  it("refuses retry while streaming or without any human message", () => {
    const { store, transport } = harness
    expect(store.getState().retry()).toBe(false)

    store.getState().send("进行中")
    expect(store.getState().retry()).toBe(false)

    transport.close(true)
    store.getState().newSession()
    expect(store.getState().retry()).toBe(false)
  })
})
