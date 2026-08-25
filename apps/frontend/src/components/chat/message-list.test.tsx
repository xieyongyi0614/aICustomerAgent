// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { MessageList } from "./message-list"
import { useChatStore } from "@/stores/chat-store"
import type { ChatMessage } from "@/types/domain/chat-message"

function seedMessages(messages: ChatMessage[]): void {
  useChatStore.setState({ messages })
}

function msg(partial: Partial<ChatMessage> & { id: string; role: "human" | "ai" }): ChatMessage {
  return {
    content: "",
    status: "complete",
    createdAt: Date.UTC(2026, 7, 25, 12, 0, 0),
    ...partial,
  }
}

afterEach(() => {
  cleanup()
  useChatStore.setState({
    messages: [],
    streamingMessageId: null,
    sessionId: null,
    connectionStatus: "idle",
  })
})

describe("MessageList", () => {
  it("shows the guide when the conversation is empty", () => {
    render(<MessageList />)
    expect(screen.getByText("和亚丝娜打个招呼吧")).toBeTruthy()
  })

  it("renders human and ai bubbles with distinct alignment", () => {
    seedMessages([
      msg({ id: "h1", role: "human", content: "在吗" }),
      msg({ id: "a1", role: "ai", content: "嗯，我在。" }),
    ])
    const { container } = render(<MessageList />)
    expect(container.querySelector('[data-testid="message-h1"]')?.className).toContain(
      "bg-secondary",
    )
    expect(container.querySelector('[data-testid="message-a1"]')?.className).toContain(
      "bg-card",
    )
    expect(screen.getByText("在吗")).toBeTruthy()
    expect(screen.getByText("嗯，我在。")).toBeTruthy()
  })

  it("renders thinking placeholder for pending empty ai message", () => {
    seedMessages([msg({ id: "a-pending", role: "ai", status: "pending" })])
    render(<MessageList />)
    expect(screen.getByText("思考中…")).toBeTruthy()
  })

  it("renders a blinking cursor only while streaming", () => {
    seedMessages([
      msg({ id: "a-done", role: "ai", content: "完成的话" }),
      msg({ id: "a-stream", role: "ai", content: "正在打字", status: "streaming" }),
    ])
    const { container } = render(<MessageList />)
    const doneBubble = container.querySelector('[data-testid="message-a-done"]')
    const streamBubble = container.querySelector('[data-testid="message-a-stream"]')
    expect(doneBubble?.querySelector(".animate-pulse")).toBeNull()
    expect(streamBubble?.querySelector(".animate-pulse")).not.toBeNull()
  })

  it("surfaces error and stopped terminal states distinctly", () => {
    seedMessages([
      msg({ id: "a-err", role: "ai", status: "error", errorText: "LLM 调用失败" }),
      msg({ id: "a-stop", role: "ai", content: "半截回答", status: "stopped" }),
    ])
    render(<MessageList />)
    expect(screen.getByText("LLM 调用失败")).toBeTruthy()
    expect(screen.getByText("已停止")).toBeTruthy()
  })

  it("keeps completed message DOM node identity across another message's stream update", () => {
    seedMessages([
      msg({ id: "h1", role: "human", content: "hi" }),
      msg({ id: "a1", role: "ai", content: "旧回答", status: "complete" }),
      msg({ id: "a2", role: "ai", content: "", status: "pending" }),
    ])
    const { container } = render(<MessageList />)
    const before = container.querySelector('[data-testid="message-a1"]')

    const streamingId = useChatStore.getState().messages[2].id
    act(() => {
      useChatStore.setState((s) => ({
        messages: s.messages.map((m) =>
          m.id === streamingId ? { ...m, content: "新", status: "streaming" } : m,
        ),
      }))
    })

    const after = container.querySelector('[data-testid="message-a1"]')
    expect(after).toBe(before)
    expect(screen.queryByText("思考中…")).toBeNull()
  })
})
