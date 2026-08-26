// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

const { chatTransport } = vi.hoisted(() => {
  return {
    chatTransport: {
      send: vi.fn(async () => {}),
    },
  }
})

vi.mock("@/api", () => ({ chatTransport }))

const { ChatInputBar } = await import("./chat-input-bar")
const { useChatStore } = await import("@/stores/chat-store")

function input(): HTMLTextAreaElement {
  return screen.getByTestId("chat-input") as HTMLTextAreaElement
}

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
  useChatStore.getState()._hardReset()
})

describe("ChatInputBar", () => {
  it("sends on Enter and clears the draft", async () => {
    const user = userEvent.setup()
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    await user.type(input(), "你好{Enter}")

    expect(chatTransport.send).toHaveBeenCalledTimes(1)
    const [request] = (chatTransport.send as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(request).toMatchObject({ content: "你好", sessionId: null })
    expect(input().value).toBe("")
    expect(useChatStore.getState().messages[0]?.content).toBe("你好")
  })

  it("keeps the draft on Shift+Enter newline", async () => {
    const user = userEvent.setup()
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    await user.type(input(), "第一行{Shift>}{Enter}{/Shift}第二行")

    expect(chatTransport.send).not.toHaveBeenCalled()
    expect(input().value).toBe("第一行\n第二行")
  })

  it("blocks Enter while IME composition is active", async () => {
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    fireEvent.compositionStart(input())
    fireEvent.keyDown(input(), { key: "Enter" })
    fireEvent.compositionEnd(input())

    expect(chatTransport.send).not.toHaveBeenCalled()
  })

  it("disables Send for blank drafts and switches to Stop while streaming", async () => {
    const user = userEvent.setup()
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    expect((screen.getByTestId("send-button") as HTMLButtonElement).disabled).toBe(true)

    await user.type(input(), "   ")
    expect((screen.getByTestId("send-button") as HTMLButtonElement).disabled).toBe(true)

    act(() => {
      useChatStore.setState({ streamingMessageId: "a-1" })
    })
    expect(screen.queryByTestId("send-button")).toBeNull()
    expect(screen.getByTestId("stop-button")).toBeTruthy()

    fireEvent.click(screen.getByTestId("stop-button"))
    expect(useChatStore.getState().streamingMessageId).toBe("a-1")
  })

  it("does not send when Enter pressed during streaming", async () => {
    act(() => {
      useChatStore.setState({ streamingMessageId: "a-1" })
    })
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    fireEvent.keyDown(input(), { key: "Enter" })
    expect(chatTransport.send).not.toHaveBeenCalled()
  })

  it("disables retry without human messages and triggers resend via store", async () => {
    const user = userEvent.setup()
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    expect((screen.getByTestId("global-retry") as HTMLButtonElement).disabled).toBe(true)

    act(() => {
      useChatStore.setState({
        messages: [
          { id: "h1", role: "human", content: "旧问题", status: "complete", createdAt: 0 },
          { id: "a1", role: "ai", content: "", status: "error", createdAt: 1 },
        ],
      })
    })
    expect((screen.getByTestId("global-retry") as HTMLButtonElement).disabled).toBe(false)
    await user.click(screen.getByTestId("global-retry"))

    expect(chatTransport.send).toHaveBeenCalledTimes(1)
    expect(useChatStore.getState().messages[0].content).toBe("旧问题")
  })

  it("clears the conversation only after confirmation", async () => {
    const user = userEvent.setup()
    act(() => {
      useChatStore.setState({
        sessionId: "s-old",
        messages: [
          { id: "h1", role: "human", content: "x", status: "complete", createdAt: 0 },
        ],
      })
    })
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)

    await user.click(screen.getByTestId("clear-button"))
    await user.click(screen.getByTestId("clear-cancel"))
    expect(useChatStore.getState().sessionId).toBe("s-old")

    await user.click(screen.getByTestId("clear-button"))
    await user.click(screen.getByTestId("clear-confirm"))
    expect(useChatStore.getState().sessionId).toBeNull()
    expect(useChatStore.getState().messages).toHaveLength(0)
  })

  it("blocks clear while streaming and shows hint text", () => {
    act(() => {
      useChatStore.setState({ streamingMessageId: "a-1" })
    })
    render(<ChatInputBar autoScrollEnabled onToggleAutoScroll={() => {}} />)
    expect((screen.getByTestId("clear-button") as HTMLButtonElement).disabled).toBe(true)
  })
})
