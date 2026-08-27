// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { TopBar } from "./top-bar"
import { API_MODE_STORAGE_KEY } from "@/api/api-mode"
import { useChatStore } from "@/stores/chat-store"

const { copyText } = vi.hoisted(() => ({
  copyText: vi.fn(),
}))

vi.mock("@/lib/copy-text", () => ({ copyText }))
function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

const reloadStub = vi.fn()

beforeEach(() => {
  vi.clearAllMocks()
  cleanup()
  window.localStorage.clear()
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: { ...window.location, reload: reloadStub },
  })
  useChatStore.setState({
    messages: [],
    streamingMessageId: null,
    sessionId: null,
    connectionStatus: "idle",
    turnMeta: null,
    lastTurnId: null,
  })
})

afterEach(() => {
  cleanup()
})

describe("TopBar", () => {
  it("shows no-session placeholder and the idle lamp", () => {
    render(<TopBar />, { wrapper: makeWrapper() })
    expect(screen.getByTestId("session-id").textContent).toBe("no-session")
    const dot = screen.getByTestId("connection-dot")
    expect(dot.className).toContain("bg-neutral-500")
  })

  it("reflects the live session id and connection status", () => {
    act(() => {
      useChatStore.setState({ sessionId: "sess-abc-123", connectionStatus: "open" })
    })
    render(<TopBar />, { wrapper: makeWrapper() })
    expect(screen.getByTestId("session-id").textContent).toBe("sess-abc-123")
    const dot = screen.getByTestId("connection-dot")
    expect(dot.className).toContain("bg-status-ok")

    act(() => {
      useChatStore.setState({ connectionStatus: "error" })
    })
    expect((screen.getByTestId("connection-dot") as HTMLElement).className).toContain(
      "bg-status-error",
    )
  })

  it("copies the session id on click", async () => {
    act(() => {
      useChatStore.setState({ sessionId: "copy-me" })
    })
    const user = userEvent.setup()
    render(<TopBar />, { wrapper: makeWrapper() })
    await user.click(screen.getByTestId("session-id"))
    expect(copyText).toHaveBeenCalledWith("copy-me")
  })

  it("starts a new session and clears chat state", async () => {
    act(() => {
      useChatStore.setState({
        sessionId: "old",
        messages: [
          { id: "h", role: "human", content: "x", status: "complete", createdAt: 0 },
          { id: "a", role: "ai", content: "y", status: "complete", createdAt: 1 },
        ],
      })
    })
    const user = userEvent.setup()
    render(<TopBar />, { wrapper: makeWrapper() })
    await user.click(screen.getByTestId("new-session"))
    expect(useChatStore.getState().sessionId).toBeNull()
    expect(useChatStore.getState().messages).toHaveLength(0)
  })

  it("disables new session while streaming", () => {
    act(() => {
      useChatStore.setState({ streamingMessageId: "a-1" })
    })
    render(<TopBar />, { wrapper: makeWrapper() })
    expect((screen.getByTestId("new-session") as HTMLButtonElement).disabled).toBe(true)
  })

  it("switches api mode after confirmation: persists then reloads", async () => {
    const user = userEvent.setup()
    render(<TopBar />, { wrapper: makeWrapper() })
    await user.click(screen.getByTestId("mode-switch-trigger"))
    await user.click(screen.getByTestId("mode-switch-confirm"))

    expect(window.localStorage.getItem(API_MODE_STORAGE_KEY)).toBe("mock")
    expect(reloadStub).toHaveBeenCalledTimes(1)
  })

  it("keeps current mode when cancelling the switch dialog", async () => {
    const user = userEvent.setup()
    render(<TopBar />, { wrapper: makeWrapper() })
    await user.click(screen.getByTestId("mode-switch-trigger"))
    fireEvent.click(screen.getByText("取消"))
    expect(window.localStorage.getItem(API_MODE_STORAGE_KEY)).toBeNull()
    expect(reloadStub).not.toHaveBeenCalled()
  })
})
