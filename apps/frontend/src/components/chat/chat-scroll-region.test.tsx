// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { ChatScrollRegion } from "./chat-scroll-region"
import { useChatStore } from "@/stores/chat-store"
import type { ChatMessage } from "@/types/domain/chat-message"

function msg(partial: Partial<ChatMessage> & { id: string; role: "human" | "ai" }): ChatMessage {
  return {
    content: "",
    status: "complete",
    createdAt: 0,
    ...partial,
  }
}

function fakeMetrics(
  el: HTMLElement,
  metrics: { scrollTop: number; scrollHeight: number; clientHeight: number },
): void {
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    writable: true,
    value: metrics.scrollTop,
  })
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    value: metrics.scrollHeight,
  })
  Object.defineProperty(el, "clientHeight", {
    configurable: true,
    value: metrics.clientHeight,
  })
}

beforeEach(() => {
  useChatStore.setState({
    messages: [],
    streamingMessageId: null,
    sessionId: null,
    connectionStatus: "idle",
  })
})

afterEach(() => {
  cleanup()
})

describe("ChatScrollRegion auto-scroll", () => {
  it("follows new content while at the bottom and enabled", () => {
    const { container } = render(<ChatScrollRegion enabled />)
    const scroller = container.querySelector('[data-testid="chat-scroll-container"]') as HTMLElement
    fakeMetrics(scroller, { scrollTop: 0, scrollHeight: 1500, clientHeight: 300 })

    act(() => {
      useChatStore.setState({
        messages: [msg({ id: "h1", role: "human", content: "hi" })],
      })
    })

    expect(scroller.scrollTop).toBe(1500)
  })

  it("pauses following when the user scrolls up and offers jump back", () => {
    const { container } = render(<ChatScrollRegion enabled />)
    const scroller = container.querySelector('[data-testid="chat-scroll-container"]') as HTMLElement
    fakeMetrics(scroller, { scrollTop: 0, scrollHeight: 2000, clientHeight: 400 })

    act(() => {
      fireEvent.scroll(scroller)
    })

    expect(screen.queryByTestId("jump-to-bottom")).not.toBeNull()

    act(() => {
      fireEvent.click(screen.getByTestId("jump-to-bottom"))
    })
    expect((scroller as HTMLElement & { scrollTop: number }).scrollTop).toBe(2000)
    expect(screen.queryByTestId("jump-to-bottom")).toBeNull()
  })

  it("never force-scrolls while paused even as content streams", () => {
    const { container } = render(<ChatScrollRegion enabled />)
    const scroller = container.querySelector('[data-testid="chat-scroll-container"]') as HTMLElement
    fakeMetrics(scroller, { scrollTop: 0, scrollHeight: 2000, clientHeight: 400 })
    act(() => {
      fireEvent.scroll(scroller)
    })

    const before = (scroller as HTMLElement & { scrollTop: number }).scrollTop
    act(() => {
      useChatStore.setState({
        messages: [
          msg({ id: "h1", role: "human", content: "hi" }),
          msg({ id: "a1", role: "ai", content: "partial", status: "streaming" }),
        ],
      })
    })
    expect((scroller as HTMLElement & { scrollTop: number }).scrollTop).toBe(before)
    expect(screen.getByTestId("jump-to-bottom")).toBeTruthy()
  })

  it("ignores everything when AutoScroll is disabled", () => {
    const { container } = render(<ChatScrollRegion enabled={false} />)
    const scroller = container.querySelector('[data-testid="chat-scroll-container"]') as HTMLElement
    fakeMetrics(scroller, { scrollTop: 0, scrollHeight: 2000, clientHeight: 400 })
    act(() => {
      fireEvent.scroll(scroller)
    })
    expect(screen.queryByTestId("jump-to-bottom")).toBeNull()
  })

  it("resets follow mode when the conversation is cleared", async () => {
    const user = userEvent.setup()
    const { container } = render(<ChatScrollRegion enabled />)
    const scroller = container.querySelector('[data-testid="chat-scroll-container"]') as HTMLElement
    fakeMetrics(scroller, { scrollTop: 0, scrollHeight: 2000, clientHeight: 400 })
    act(() => {
      useChatStore.setState({ messages: [msg({ id: "h1", role: "human", content: "hi" })] })
      fireEvent.scroll(scroller)
    })
    expect(screen.queryByTestId("jump-to-bottom")).not.toBeNull()

    await user.click(screen.getByTestId("jump-to-bottom"))
    expect(screen.queryByTestId("jump-to-bottom")).toBeNull()
  })
})
