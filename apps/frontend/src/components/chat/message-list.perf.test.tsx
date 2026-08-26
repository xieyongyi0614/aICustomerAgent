// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, render } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("@/api", () => ({
  chatTransport: { send: vi.fn(async () => {}) },
}))

const { MessageList } = await import("@/components/chat/message-list")
const { useChatStore } = await import("@/stores/chat-store")
import type { ChatMessage } from "@/types/domain/chat-message"

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

function makeMessages(count: number): ChatMessage[] {
  const messages: ChatMessage[] = []
  for (let i = 0; i < count; i += 1) {
    messages.push({
      id: `h-${i}`,
      role: "human",
      content: `用户第 ${i} 句话`,
      status: "complete",
      createdAt: i,
    })
    messages.push({
      id: `a-${i}`,
      role: "ai",
      content: `回答 ${i}，较长的模型输出文本用于模拟真实体量与折行。`.repeat(2),
      status: "complete",
      createdAt: i,
    })
  }
  return messages
}

afterEach(() => {
  cleanup()
  useChatStore.getState()._hardReset()
})

describe("long conversation render baseline (jsdom, 非浏览器帧率)", () => {
  it("renders 600 static messages fast without virtual scrolling", () => {
    useChatStore.setState({ messages: makeMessages(300) })

    let elapsedMs = 0
    let renderedNodes = 0
    const started = performance.now()
    const r = render(<MessageList />, { wrapper: makeWrapper() })
    elapsedMs = performance.now() - started
    renderedNodes = r.container.querySelectorAll("[data-testid^='message-']").length

    expect(renderedNodes).toBe(600)
    console.log(`[perf] 600 条静态消息渲染 ${elapsedMs.toFixed(0)}ms`)
    expect(elapsedMs).toBeLessThan(1500)
  })

  it("applies 20 streaming deltas over 301 messages cheaply", () => {
    const messages = makeMessages(150)
    messages.push({
      id: "a-live",
      role: "ai",
      content: "",
      status: "pending",
      createdAt: Date.now(),
    })
    useChatStore.setState({ messages, streamingMessageId: "a-live" })

    let elapsedMs = 0
    let renderedNodes = 0
    const started = performance.now()
    const r = render(<MessageList />, { wrapper: makeWrapper() })
    for (let i = 0; i < 20; i += 1) {
      act(() => {
        useChatStore.setState((s) => ({
          messages: s.messages.map((m) =>
            m.id === "a-live"
              ? { ...m, content: m.content + `块${i}`, status: "streaming" as const }
              : m,
          ),
        }))
      })
    }
    elapsedMs = performance.now() - started
    renderedNodes = r.container.querySelectorAll("[data-testid^='message-']").length

    const liveContent = useChatStore
      .getState()
      .messages.find((m) => m.id === "a-live")?.content
    expect(liveContent).toContain("块19")
    expect(renderedNodes).toBe(301)
    console.log(`[perf] 20 次流式增量 × ${renderedNodes} 条消息 ${elapsedMs.toFixed(0)}ms`)
    expect(elapsedMs).toBeLessThan(1200)
  })
})
