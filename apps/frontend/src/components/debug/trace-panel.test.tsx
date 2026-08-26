// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { setupServer } from "msw/node"
import { http, HttpResponse } from "msw"
import type { ReactNode } from "react"
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest"

import { TracePanel } from "./trace-panel"
import { restHandlers } from "@/mocks/msw-handlers"

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

function renderTrace(turnId: string | null, pollIntervalMs?: number) {
  return render(
    <TracePanel turnId={turnId} pollIntervalMs={pollIntervalMs} />,
    { wrapper: makeWrapper() },
  )
}

describe("TracePanel", () => {
  it("renders the full waterfall with degraded badge and background divider", async () => {
    renderTrace("t-rich-1")
    await waitFor(() =>
      expect(screen.queryByTestId("trace-skeleton")).toBeNull(),
    )

    for (const name of [
      "role_router",
      "turn_analyzer",
      "memory_retrieval",
      "prompt_builder",
      "llm",
      "state_update",
      "memory_extractor",
    ]) {
      expect(screen.getByTestId(`trace-row-${name}`)).toBeTruthy()
    }
    expect(screen.getAllByText(/∥/).length).toBe(2)
    expect(screen.getByText(/done 之后 · 异步后处理/)).toBeTruthy()
    expect(screen.getByText("degraded")).toBeTruthy()
    expect(screen.getByText(/总耗时 5.8s/)).toBeTruthy()
    expect(screen.getByText(/⚠1 项降级/)).toBeTruthy()
    expect(screen.getAllByText(/首字/).length).toBeGreaterThanOrEqual(1)
  })

  it("shows step detail with error block when a failing step is clicked", async () => {
    server.use(
      http.get("*/api/v1/debug/turns/:turnId/trace", () =>
        HttpResponse.json({
          turn_id: "t-err",
          status: "complete",
          role_mode: null,
          analysis: null,
          total_ms: 500,
          steps: [
            { name: "llm", status: "error", durationMs: 400, firstTokenMs: null, error: "upstream timeout" },
          ],
        }),
      ),
    )
    renderTrace("t-err")
    const row = await screen.findByTestId("trace-row-llm")
    fireEvent.click(row.querySelector("button")!)

    expect(await screen.findByTestId("trace-step-detail")).toBeTruthy()
    expect(screen.getByText("upstream timeout")).toBeTruthy()
    expect(screen.getByTestId("dot-error")).toBeTruthy()
  })

  it("appends unknown step names at the end in a neutral style", async () => {
    server.use(
      http.get("*/api/v1/debug/turns/:turnId/trace", () =>
        HttpResponse.json({
          turn_id: "t-x",
          status: "complete",
          role_mode: null,
          analysis: null,
          total_ms: 100,
          steps: [
            { name: "llm", status: "ok", durationMs: 80, firstTokenMs: null, error: null },
            { name: "tool:search", status: "ok", durationMs: 20, firstTokenMs: null, error: null },
          ],
        }),
      ),
    )
    renderTrace("t-x")
    const row = await screen.findByTestId("trace-row-tool:search")
    expect(row).toBeTruthy()
    const rows = document.querySelectorAll("[data-testid^='trace-row-']")
    expect(rows[rows.length - 1].getAttribute("data-testid")).toBe("trace-row-tool:search")
  })

  it("shows skeleton then timeout card for a forever-pending turn", async () => {
    renderTrace("__pending__", 5)
    expect(await screen.findByTestId("trace-skeleton", {}, { timeout: 2000 })).toBeTruthy()
    await waitFor(
      () => expect(screen.queryByTestId("trace-timeout")).not.toBeNull(),
      { timeout: 3000 },
    )
    expect(screen.getByText(/后处理未完成（轮询超时）/)).toBeTruthy()
    expect(screen.getByRole("button", { name: "手动刷新" })).toBeTruthy()
  }, 15_000)

  it("explains cleaned-up turns on 404", async () => {
    renderTrace("no-such-turn")
    expect(await screen.findByTestId("trace-notfound")).toBeTruthy()
    expect(screen.getByText(/重发一轮以采集/)).toBeTruthy()
  })
})
