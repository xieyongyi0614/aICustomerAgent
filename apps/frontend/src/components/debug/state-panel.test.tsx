// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { setupServer } from "msw/node"
import { http, HttpResponse } from "msw"
import type { ReactNode } from "react"
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import { StatePanel } from "./state-panel"
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

describe("StatePanel", () => {
  it("renders rich persona values, stage hint and emotion history", async () => {
    render(<StatePanel userId="rich-user" />, { wrapper: makeWrapper() })
    await waitFor(() =>
      expect(screen.queryByTestId("state-skeleton")).toBeNull(),
    )

    expect(screen.getByTestId("character-state-card")).toBeTruthy()
    expect(screen.getByTestId("emotion-intensity")).toBeTruthy()
    expect(screen.getByText("用户连续熬夜赶工")).toBeTruthy()
    expect(screen.getByTestId("relationship-events-card")).toBeTruthy()
    expect(screen.getAllByTestId("relationship-event-item")).toHaveLength(1)
    expect(screen.getByText("worried")).toBeTruthy()
    expect(screen.getByText("0.42")).toBeTruthy()

    expect(screen.getByText("close_friend")).toBeTruthy()
    const meters = document.querySelectorAll('[data-slot="meter-bar-indicator"]')
    expect(meters.length).toBeGreaterThanOrEqual(3)

    expect(screen.getByTestId("stage-progress-hint").textContent).toContain(
      "partner",
    )
    expect(screen.getByTestId("emotion-history-strip").children.length).toBe(2)
    expect(screen.queryByText(/已超过闲置恢复窗口/)).toBeNull()
  })

  it("shows empty history for the fresh persona", async () => {
    render(<StatePanel />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.queryByTestId("state-skeleton")).toBeNull())
    expect(screen.getByTestId("emotion-history-empty")).toBeTruthy()
    expect(screen.getAllByText("calm").length).toBeGreaterThan(0)
  })

  it("renders error card with working retry after a failed request", async () => {
    server.use(
      http.get("*/api/v1/state", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    )
    render(<StatePanel userId="rich-user" />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.getByTestId("state-error")).toBeTruthy())

    server.use(
      http.get("*/api/v1/state", ({ request }) => {
        void request
        return HttpResponse.json({
          character_state: {
            mood: "happy",
            energy: 0.9,
            current_topic: "t",
            inner_state: "i",
            updated_at: null,
          },
          relationship_state: {
            intimacy: 0.3,
            trust: 0.35,
            familiarity: 0.3,
            stage: "friend",
            updated_at: null,
          },
          emotion_history: [],
        })
      }),
    )
    fireEvent.click(screen.getByRole("button", { name: "重试" }))
    await waitFor(() => expect(screen.getByTestId("state-panel")).toBeTruthy())
    expect(vi.isMockFunction(() => {})).toBe(false)
  })

  it("exposes raw json dialogs per card", async () => {
    render(<StatePanel userId="rich-user" />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.queryByTestId("state-skeleton")).toBeNull())
    const jsonButtons = screen.getAllByRole("button", { name: "json" })
    expect(jsonButtons.length).toBeGreaterThanOrEqual(2)
  })

  it("marks stale updated_at beyond idle recovery window", async () => {
    server.use(
      http.get("*/api/v1/state", () =>
        HttpResponse.json({
          character_state: {
            mood: "calm",
            energy: 0.9,
            current_topic: "",
            inner_state: "平静",
            updated_at: "2020-01-01T00:00:00",
          },
          relationship_state: {
            intimacy: 0.3,
            trust: 0.35,
            familiarity: 0.3,
            stage: "friend",
            updated_at: "2020-01-01T00:00:00",
          },
          emotion_history: [],
        }),
      ),
    )
    render(<StatePanel userId="rich-user" />, { wrapper: makeWrapper() })
    await waitFor(() => expect(screen.queryByTestId("state-skeleton")).toBeNull())
    expect(screen.getByText(/已超过闲置恢复窗口/)).toBeTruthy()
  })
})
