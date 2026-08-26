// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { setupServer } from "msw/node"
import { http, HttpResponse } from "msw"
import type { ReactNode } from "react"
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest"

import { MemoryPanel } from "./memory-panel"
import { restHandlers } from "@/mocks/msw-handlers"
import type { TurnTrace } from "@/types/domain/observability"

const server = setupServer(...restHandlers)

beforeAll(() => server.listen({ onUnhandledRequest: "error" }))
afterEach(() => {
  server.resetHandlers()
  cleanup()
})
afterAll(() => server.close())

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

function renderPanel(props?: { userId?: string; turnTrace?: TurnTrace | null }) {
  return render(<MemoryPanel {...props} />, { wrapper: makeWrapper() })
}

const EXTRACTOR_TRACE: TurnTrace = {
  turnId: "t-1",
  status: "complete",
  roleMode: null,
  analysis: null,
  totalMs: 100,
  degradedSteps: [],
  steps: [
    { name: "memory_extractor", status: "ok", durationMs: 120.5, firstTokenMs: null, error: null },
  ],
}

describe("MemoryPanel", () => {
  it("renders rich memories with type badge and importance meter", async () => {
    renderPanel({ userId: "rich-user" })
    await waitFor(() => expect(screen.queryByTestId("memory-skeleton")).toBeNull())
    expect(screen.getAllByTestId("memory-item")).toHaveLength(2)
    expect(screen.getByText("goal")).toBeTruthy()
    expect(screen.getAllByText("preference").length).toBeGreaterThan(0)
    expect(screen.getAllByText("0.90")).toBeTruthy()
    expect(
      document.querySelectorAll('[data-slot="meter-bar-indicator"]').length,
    ).toBeGreaterThanOrEqual(2)
  })

  it("truncates long memory text and expands on click", async () => {
    renderPanel({ userId: "rich-user" })
    await waitFor(() =>
      expect(screen.getAllByTestId("memory-item")).toHaveLength(2),
    )
    const content = screen.getByTestId("memory-content-m-1")
    expect(content.className).toContain("truncate")
    fireEvent.click(content)
    expect(content.className).not.toContain("truncate")
  })

  it("shows empty guide for fresh persona", async () => {
    renderPanel({ userId: "empty-user" })
    await waitFor(() => expect(screen.getByTestId("memory-empty")).toBeTruthy())
    expect(screen.getByText(/聊点个人偏好/)).toBeTruthy()
  })

  it("keeps the hits view disabled with an explanation", async () => {
    renderPanel({ userId: "rich-user" })
    const hits = (await screen.findByTestId("view-hits")) as HTMLButtonElement
    expect(hits.disabled).toBe(true)
    expect(hits.parentElement?.getAttribute("title")).toContain("留痕")
  })

  it("recovers via retry after a failed request", async () => {
    server.use(http.get("*/api/v1/memories", () => HttpResponse.json({ detail: "boom" }, { status: 500 })))
    renderPanel({ userId: "empty-user" })
    expect(await screen.findByTestId("memory-error")).toBeTruthy()

    server.use(
      http.get("*/api/v1/memories", () =>
        HttpResponse.json({ user_id: "empty-user", memories: [] }),
      ),
    )
    fireEvent.click(await screen.findByRole("button", { name: "重试" }))
    await waitFor(() => expect(screen.getByTestId("memory-empty")).toBeTruthy())
  })

  it("extractor card reflects trace step or falls back to unrecorded", async () => {
    renderPanel({ userId: "rich-user", turnTrace: EXTRACTOR_TRACE })
    expect(await screen.findByText("120.5ms")).toBeTruthy()
    expect(screen.getByText("ok")).toBeTruthy()

    cleanup()
    renderPanel({ userId: "rich-user" })
    expect((await screen.findByText("未记录")).textContent).toBeTruthy()
  })
})
