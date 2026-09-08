// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { setupServer } from "msw/node"
import type { ReactNode } from "react"
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest"

import { TurnBadge } from "@/components/chat/turn-badge"
import { Workbench } from "@/components/shell/workbench"
import { restHandlers } from "@/mocks/msw-handlers"
import { useChatStore } from "@/stores/chat-store"
import { useUiStore } from "@/stores/ui-store"
import type { ChatMessage } from "@/types/domain/chat-message"

const server = setupServer(...restHandlers)

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }))
afterEach(() => {
  server.resetHandlers()
  cleanup()
})
afterAll(() => server.close())

beforeEach(() => {
  useChatStore.setState({
    messages: [],
    streamingMessageId: null,
    sessionId: null,
    connectionStatus: "idle",
    turnMeta: null,
    lastTurnId: null,
  })
  useUiStore.setState({
    activeTab: "overview",
    selectedTurnId: null,
    highlightMessageId: null,
  })
  window.localStorage.clear()
})

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

const BADGED_MESSAGE: ChatMessage = {
  id: "ai-1",
  role: "ai",
  content: "回答内容",
  status: "complete",
  createdAt: Date.now(),
  turnId: "t-42",
  badge: { mode: "immersive", behavior: "comfort", durationMs: 5200 },
}

describe("turn badge forward linkage", () => {
  it("opens the trace tab with the message's turn id on click", async () => {
    render(<TurnBadge message={BADGED_MESSAGE} />)
    fireEvent.click(screen.getByTestId("turn-badge-ai-1"))
    expect(useUiStore.getState().activeTab).toBe("trace")
    expect(useUiStore.getState().selectedTurnId).toBe("t-42")
  })

  it("renders a disabled placeholder when no observation data exists", () => {
    render(
      <TurnBadge
        message={{ ...BADGED_MESSAGE, turnId: undefined, badge: undefined }}
      />,
    )
    const badge = screen.getByTestId("turn-badge-ai-1") as HTMLButtonElement
    expect(badge.disabled).toBe(true)
    expect(badge.textContent).toContain("无观测数据")
  })
})

describe("reverse linkage", () => {
  it("highlights the ai message when the llm step is clicked in trace", async () => {
    useChatStore.setState({ messages: [BADGED_MESSAGE] })
    useUiStore.getState().openTurnInTrace("t-42")

    const wrapper = makeWrapper()
    render(
      <div>
        <div data-testid="message-list">
          <div data-testid="message-ai-1" />
        </div>
      </div>,
      { wrapper },
    )

    await waitFor(() =>
      expect(useUiStore.getState().selectedTurnId).toBe("t-42"),
    )
    void screen
  })
})

describe("collapsed pane auto-expand", () => {
  it("expands the debug pane when a turn is opened from a badge", async () => {
    window.localStorage.setItem("asuna-debug.debugPaneCollapsed", "true")
    render(<Workbench />, { wrapper: makeWrapper() })
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()

    act(() => {
      useUiStore.getState().openTurnInTrace("t-9")
    })
    await waitFor(() =>
      expect(screen.queryByTestId("debug-pane-inline")).not.toBeNull(),
    )
    expect(screen.getByRole("tab", { name: "Trace" }).getAttribute("aria-selected")).toBe(
      "true",
    )
  }, 15_000)
})
