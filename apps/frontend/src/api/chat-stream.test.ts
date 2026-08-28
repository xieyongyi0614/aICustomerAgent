import { describe, expect, it, vi } from "vitest"

import { FetchChatStreamTransport, parseStreamLine } from "./chat-stream"
import type { StreamEvent } from "./transport"

const encoder = new TextEncoder()

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

interface Harness {
  transport: FetchChatStreamTransport
  events: StreamEvent[]
  errors: Error[]
  closeInfos: Array<{ aborted: boolean }>
  sessionMetas: Array<{ sessionId: string; isNew: boolean }>
}

function makeTransport(
  chunks: string[],
  options?: { status?: number; headers?: Record<string, string> },
): Harness {
  const status = options?.status ?? 200
  const headers = new Headers({
    "content-type": "application/x-ndjson",
    ...(status === 200 ? { "x-session-id": "s-123", "x-session-new": "true" } : {}),
    ...options?.headers,
  })
  const body = streamOf(chunks)
  const fetchImpl = vi.fn(async () => new Response(body, { status, headers }))
  const transport = new FetchChatStreamTransport({ fetchImpl })
  const harness: Harness = {
    transport,
    events: [],
    errors: [],
    closeInfos: [],
    sessionMetas: [],
  }
  return harness
}

function run(harness: Harness, signal?: AbortSignal): Promise<void> {
  return harness.transport.send(
    { content: "hello" },
    {
      onSessionMeta: (meta) => harness.sessionMetas.push(meta),
      onEvent: (event) => harness.events.push(event),
      onError: (error) => harness.errors.push(error),
      onClose: (info) => harness.closeInfos.push(info),
    },
    signal,
  )
}

describe("scene meta parsing", () => {
  it("parses scene_intent and scene_state from turn_meta", () => {
    const event = parseStreamLine(
      JSON.stringify({
        type: "turn_meta",
        role_mode: {
          mode: "immersive",
          intent: "roleplay",
          confidence: 0.9,
          reason: "rp",
        },
        analysis: {
          user_emotion: { emotion: "happy", event: "daily" },
          behavior: { behavior: "normal_reply", reason: "" },
        },
        scene_intent: {
          intent: "request_action",
          confidence: 0.85,
          reason: "要求动作",
        },
        scene_state: {
          session_id: "s-1",
          turn_id: 3,
          location: "客厅",
          current_activity: "休息",
          current_action: "切西瓜",
          pending_action: {
            action: "把西瓜拿给用户",
            status: "pending",
            created_at_turn: 2,
          },
          scene_mood: "relaxed",
        },
      }),
    )
    expect(event).not.toBeNull()
    if (event?.type !== "turn_meta") throw new Error("expected turn_meta")
    expect(event.sceneIntent?.intent).toBe("request_action")
    expect(event.sceneState?.pendingAction?.status).toBe("pending")
    expect(event.sceneState?.pendingAction?.createdAtTurn).toBe(2)
    expect(event.sceneState?.sceneMood).toBe("relaxed")
  })

  it("keeps scene fields undefined when absent from turn_meta", () => {
    const event = parseStreamLine(
      JSON.stringify({
        type: "turn_meta",
        role_mode: {
          mode: "default",
          intent: "casual",
          confidence: 0.9,
          reason: "hi",
        },
        analysis: {
          user_emotion: { emotion: "neutral", event: "daily" },
          behavior: { behavior: "normal_reply", reason: "" },
        },
      }),
    )
    expect(event).not.toBeNull()
    if (event?.type !== "turn_meta") throw new Error("expected turn_meta")
    expect(event.sceneIntent).toBeUndefined()
    expect(event.sceneState).toBeUndefined()
  })

  it("ignores malformed scene_state payloads", () => {
    const event = parseStreamLine(
      JSON.stringify({
        type: "turn_meta",
        role_mode: {
          mode: "default",
          intent: "casual",
          confidence: 0.9,
          reason: "hi",
        },
        analysis: {
          user_emotion: { emotion: "neutral", event: "daily" },
          behavior: { behavior: "normal_reply", reason: "" },
        },
        scene_state: { broken: true },
      }),
    )
    expect(event).not.toBeNull()
    if (event?.type !== "turn_meta") throw new Error("expected turn_meta")
    expect(event.sceneState).toBeUndefined()
  })
})

describe("line framing", () => {
  it("reassembles lines split across chunks", async () => {
    const harness = makeTransport([
      '{"delta":"he',
      'llo"}\n{"delta":"wo',
      'rld"}\n{"done":true}\n',
    ])
    await run(harness)
    expect(harness.events).toEqual([
      { type: "delta", text: "hello" },
      { type: "delta", text: "world" },
      { type: "done", sessionId: undefined, turnId: undefined },
    ])
  })

  it("handles multiple lines per chunk and a missing trailing newline", async () => {
    const harness = makeTransport(['{"delta":"a"}\n{"delta":"b"}\n{"delta":"c"}'])
    await run(harness)
    expect(harness.events.map((e) => (e.type === "delta" ? e.text : null))).toEqual([
      "a",
      "b",
      "c",
    ])
  })

  it("accepts CRLF line separators", async () => {
    const harness = makeTransport(['{"delta":"x"}\r\n{"done":true}\r\n'])
    await run(harness)
    expect(harness.events).toHaveLength(2)
  })
})

describe("event normalization", () => {
  it("parses legacy delta/done/detail and typed turn_meta, ignoring junk", async () => {
    const harness = makeTransport([
      '{"delta":"hi"}\n',
      '{"type":"turn_meta","role_mode":{"mode":"immersive","intent":"roleplay","confidence":0.9,"reason":"ok"},"analysis":{"user_emotion":{"emotion":"sad","event":"setback"},"behavior":{"behavior":"comfort","reason":"r"}}}\n',
      '{"foo":1}\n',
      "{oops\n",
      '{"detail":"LLM 调用失败"}\n',
      '{"type":"error","message":"quota","code":"insufficient_quota"}\n',
      '{"detail":"rate limited","error":{"status":429,"code":"rate_limit","message":"slow down"}}\n',
      '{"done":true,"session_id":"s-9","turn_id":42}\n',
    ])
    await run(harness)

    expect(harness.events[0]).toEqual({ type: "delta", text: "hi" })
    const meta = harness.events[1]
    expect(meta.type).toBe("turn_meta")
    if (meta.type === "turn_meta") {
      expect(meta.roleMode.mode).toBe("immersive")
      expect(meta.analysis.userEmotion.emotion).toBe("sad")
      expect(meta.analysis.behavior.behavior).toBe("comfort")
    }
    expect(harness.events[2]).toEqual({ type: "error", message: "LLM 调用失败", code: undefined })
    expect(harness.events[3]).toEqual({ type: "error", message: "quota", code: "insufficient_quota" })
    expect(harness.events[4]).toEqual({ type: "error", message: "rate limited", code: "rate_limit" })
    expect(harness.events[harness.events.length - 1]).toEqual({
      type: "done",
      sessionId: "s-9",
      turnId: "42",
    })
    expect(harness.closeInfos).toEqual([{ aborted: false }])
  })

  it("exposes session meta from response headers once", async () => {
    const harness = makeTransport(['{"delta":"x"}\n'])
    await run(harness)
    expect(harness.sessionMetas).toEqual([{ sessionId: "s-123", isNew: true }])
  })

  it("surfaces non-ok responses as ApiError without events", async () => {
    const harness = makeTransport(['{"detail":"backend down"}\n'], { status: 500 })
    await run(harness)
    expect(harness.events).toHaveLength(0)
    expect(harness.errors).toHaveLength(1)
    expect(harness.errors[0].name).toBe("ApiError")
    expect((harness.errors[0] as Error & { status?: number }).status).toBe(500)
    expect(harness.closeInfos).toEqual([{ aborted: false }])
  })

  it("reports silent abort without error", async () => {
    const controller = new AbortController()
    controller.abort()
    const fetchImpl = vi.fn(async () => {
      throw new DOMException("This operation was aborted", "AbortError")
    })
    const transport = new FetchChatStreamTransport({ fetchImpl })
    const events: StreamEvent[] = []
    const errors: Error[] = []
    const closes: Array<{ aborted: boolean }> = []
    await transport.send(
      { content: "x" },
      {
        onEvent: (e) => events.push(e),
        onError: (e) => errors.push(e),
        onClose: (i) => closes.push(i),
      },
      controller.signal,
    )
    expect(events).toHaveLength(0)
    expect(errors).toHaveLength(0)
    expect(closes).toEqual([{ aborted: true }])
  })
})

describe("parseStreamLine", () => {
  it("returns null for blank or unparseable input", () => {
    expect(parseStreamLine("")).toBeNull()
    expect(parseStreamLine("   \n")).toBeNull()
    expect(parseStreamLine("{broken")).toBeNull()
    expect(parseStreamLine('["array"]')).toBeNull()
  })

  it("ignores unknown typed events reserved for future contract versions", () => {
    expect(parseStreamLine('{"type":"trace_event","step":{}}')).toBeNull()
    expect(parseStreamLine('{"type":"snapshot"}')).toBeNull()
  })
})
