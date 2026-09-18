// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { setupServer } from "msw/node"
import { http, HttpResponse } from "msw"
import type { ReactNode } from "react"
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest"

import { WorldSimPanel } from "./WorldSimPanel"

const server = setupServer()

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

const SIMULATION_ON = {
  enabled: true,
  time_context: { now: "2026-09-14T09:00:00", part_of_day: "morning", time_mode: "real_sync" },
  brief: {
    text: "09-14 周一 上午 09:00。她此刻在客厅。",
    parts: {
      text: "09-14 周一 上午 09:00。她此刻在客厅。",
      time_line: "09-14 周一 上午 09:00",
      place_line: "她此刻在客厅。",
      situations_line: null,
      events_line: null,
    },
  },
  current_block: null,
  active_situations: [],
  recent_events: [],
  flags: {
    world_simulation_enabled: true,
    time_advance_enabled: true,
    daily_life_enabled: true,
    event_detection_enabled: true,
    scene_expansion_enabled: false,
    habit_time_enabled: false,
    world_llm_assist_enabled: false,
    debug_tick_enabled: false,
  },
}

const PLAN_DTO = {
  enabled: true,
  date: "2026-09-14",
  blocks: [
    {
      seq: 0,
      part_of_day: "morning",
      start_minutes: 480,
      end_minutes: 540,
      activity: "晨间整理",
      location_id: "home.living_room",
      variability_source: "fixed",
      status: "completed",
      note: null,
    },
    {
      seq: 1,
      part_of_day: "morning",
      start_minutes: 540,
      end_minutes: 660,
      activity: "工作学习",
      location_id: "home.study",
      variability_source: "variant",
      status: "active",
      note: null,
    },
  ],
}

const SITUATIONS_DTO = {
  enabled: true,
  situations: [
    {
      dimension: "health",
      summary: "用户身体不适",
      intensity: 4,
      status: "active",
      source: "conversation_pattern",
      detected_at: "2026-09-14T08:30:00",
      valid_until: "2026-09-16T08:30:00",
      evidence: { quote: "我今天感冒了", matched: "身体不适" },
    },
  ],
}

function registerHandlers(overrides?: {
  simulation?: unknown
  plan?: unknown
  situations?: unknown
}) {
  server.use(
    http.get("*/api/v1/debug/world/simulation", () =>
      HttpResponse.json(overrides?.simulation ?? SIMULATION_ON),
    ),
    http.get("*/api/v1/debug/world/plan", () =>
      HttpResponse.json(overrides?.plan ?? PLAN_DTO),
    ),
    http.get("*/api/v1/debug/world/situations", () =>
      HttpResponse.json(overrides?.situations ?? SITUATIONS_DTO),
    ),
  )
}

describe("WorldSimPanel", () => {
  it("renders five blocks with plan timeline status colors", async () => {
    registerHandlers()
    render(<WorldSimPanel userId="ws-user" />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByTestId("world-sim-panel")).toBeTruthy())
    expect(screen.getByTestId("world-sim-brief").textContent).toContain("客厅")
    expect(screen.getByTestId("world-sim-block-0")).toBeTruthy()
    expect(screen.getByTestId("world-sim-block-status-1").textContent).toBe("active")
    expect(screen.getByTestId("world-sim-situation-health")).toBeTruthy()
    expect(screen.getByText("我今天感冒了")).toBeTruthy()
    expect(screen.queryByTestId("world-sim-tick")).toBeNull()
  })

  it("shows disabled empty state when master flag is off", async () => {
    registerHandlers({ simulation: { ...SIMULATION_ON, enabled: false } })
    render(<WorldSimPanel userId="ws-off" />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByTestId("world-sim-disabled")).toBeTruthy())
    expect(screen.queryByTestId("world-sim-panel")).toBeNull()
  })

  it("renders empty states when no plan or situations exist", async () => {
    registerHandlers({
      plan: { enabled: true, date: "2026-09-14", blocks: [] },
      situations: { enabled: true, situations: [] },
    })
    render(<WorldSimPanel userId="ws-empty" />, { wrapper: makeWrapper() })

    await waitFor(() => expect(screen.getByTestId("world-sim-plan-empty")).toBeTruthy())
    expect(screen.getByTestId("world-sim-situations-empty")).toBeTruthy()
    expect(screen.getByTestId("world-sim-events-empty")).toBeTruthy()
  })

  it("shows manual tick button and posts when debug tick flag is on", async () => {
    let posted = false
    registerHandlers({
      simulation: {
        ...SIMULATION_ON,
        flags: { ...SIMULATION_ON.flags, debug_tick_enabled: true },
      },
    })
    server.use(
      http.post("*/api/v1/debug/world/simulation/tick", async () => {
        posted = true
        return HttpResponse.json({
          enabled: true,
          result: { advanced_minutes: 12.5, markers: ["real_sync"], plan_summary: null, errors: [] },
        })
      }),
    )
    render(<WorldSimPanel userId="ws-tick" />, { wrapper: makeWrapper() })

    const button = await waitFor(() => screen.getByTestId("world-sim-tick"))
    fireEvent.click(button)
    await waitFor(() => expect(screen.getByTestId("world-sim-tick-result")).toBeTruthy())
    expect(posted).toBe(true)
    expect(screen.getByText("12.5 min")).toBeTruthy()
  })
})
