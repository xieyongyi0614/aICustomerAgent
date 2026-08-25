import { describe, expect, it } from "vitest"

import { MockChatStreamTransport } from "./mock-chat-stream"
import { matchStreamScript } from "./stream-scripts"
import type { StreamEvent } from "@/api/transport"

function lastEvent(events: StreamEvent[]): StreamEvent | undefined {
  return events[events.length - 1]
}

interface RunResult {
  sessionMetas: Array<{ sessionId: string; isNew: boolean }>
  events: StreamEvent[]
  errors: unknown[]
  closeInfos: Array<{ aborted: boolean }>
}

async function runScript(content: string): Promise<RunResult> {
  const transport = new MockChatStreamTransport({ stepDelayMs: 0 })
  const result: RunResult = {
    sessionMetas: [],
    events: [],
    errors: [],
    closeInfos: [],
  }
  await transport.send(
    { content },
    {
      onSessionMeta: (meta) => result.sessionMetas.push(meta),
      onEvent: (event) => result.events.push(event),
      onError: (error) => result.errors.push(error),
      onClose: (info) => result.closeInfos.push(info),
    },
  )
  return result
}

async function runScriptWithSession(
  content: string,
  sessionId: string,
): Promise<RunResult> {
  const transport = new MockChatStreamTransport({ stepDelayMs: 0 })
  const result: RunResult = {
    sessionMetas: [],
    events: [],
    errors: [],
    closeInfos: [],
  }
  await transport.send(
    { content, sessionId },
    {
      onSessionMeta: (meta) => result.sessionMetas.push(meta),
      onEvent: () => {},
    },
  )
  return result
}

describe("mock stream scripts", () => {
  it("routes comfort script by keyword with immersive/comfort meta", async () => {
    expect(matchStreamScript("我最近压力很大").id).toBe("comfort")
    const result = await runScript("我最近压力很大")
    expect(result.sessionMetas[0].isNew).toBe(true)
    expect(result.events[0].type).toBe("turn_meta")
    if (result.events[0].type === "turn_meta") {
      expect(result.events[0].roleMode.mode).toBe("immersive")
      expect(result.events[0].analysis.behavior.behavior).toBe("comfort")
      expect(result.events[0].analysis.userEmotion.event).toBe("setback")
    }
    expect(lastEvent(result.events)?.type).toBe("done")
  })

  it("routes celebrate script by achievement keywords", async () => {
    const result = await runScript("项目今天上线成功了！")
    expect(result.events[0].type).toBe("turn_meta")
    if (result.events[0].type === "turn_meta") {
      expect(result.events[0].analysis.userEmotion.emotion).toBe("excited")
      expect(result.events[0].analysis.userEmotion.event).toBe("achievement")
      expect(result.events[0].analysis.behavior.behavior).toBe("celebrate")
    }
  })

  it("falls back to daily script for unmatched input", async () => {
    expect(matchStreamScript("随便说点什么").id).toBe("daily")
    const result = await runScript("随便说点什么")
    if (result.events[0].type === "turn_meta") {
      expect(result.events[0].roleMode.mode).toBe("default")
      expect(result.events[0].analysis.userEmotion.emotion).toBe("neutral")
      expect(result.events[0].analysis.behavior.behavior).toBe("normal_reply")
    }
  })

  it("legacy script omits turn_meta entirely", async () => {
    expect(matchStreamScript("用旧契约兼容流试试").id).toBe("legacy")
    const result = await runScript("用旧契约兼容流试试")
    expect(result.events[0]?.type).not.toBe("turn_meta")
    expect(lastEvent(result.events)?.type).toBe("done")
  })

  it("error script terminates with error event and never reaches done", async () => {
    const result = await runScript("触发错误看看界面")
    const last = lastEvent(result.events)
    expect(last?.type).toBe("error")
    if (last?.type === "error") {
      expect(last.message).toBe("LLM 调用失败")
      expect(last.code).toBe("mock_upstream_error")
    }
    expect(result.events.some((e) => e.type === "done")).toBe(false)
    expect(result.closeInfos).toEqual([{ aborted: false }])
  })

  it("stops silently when signal is already aborted", async () => {
    const controller = new AbortController()
    controller.abort()
    const transport = new MockChatStreamTransport({ stepDelayMs: 0 })
    const events: StreamEvent[] = []
    const closes: Array<{ aborted: boolean }> = []
    await transport.send(
      { content: "你好" },
      { onEvent: (e) => events.push(e), onClose: (i) => closes.push(i) },
      controller.signal,
    )
    expect(events).toHaveLength(0)
    expect(closes).toEqual([{ aborted: true }])
  })

  it("keeps existing sessionId instead of minting a new one", async () => {
    const result = await runScriptWithSession("你好", "existing-session")
    expect(result.sessionMetas).toEqual([
      { sessionId: "existing-session", isNew: false },
    ])
  })
})
