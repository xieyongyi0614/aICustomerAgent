// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import { setupServer } from "msw/node"
import type { ReactNode } from "react"
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest"

import {
  PendingTraceSignal,
  TRACE_POLL_MAX_FETCHES,
  isTraceNotFound,
  useCharacterState,
  useMemories,
  useTurnTrace,
} from "./use-observability"
import { restHandlers } from "@/mocks/msw-handlers"

const server = setupServer(...restHandlers)

beforeAll(() => server.listen({ onUnhandledRequest: "error" }))
afterEach(() => {
  server.resetHandlers()
  vi.useRealTimers()
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

describe("observability hooks", () => {
  it("maps state snapshot to camelCase domain view", async () => {
    const wrapper = makeWrapper()
    const { result } = renderHook(() => useCharacterState("rich-user"), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.characterState.currentTopic).toBe(
      "用户的 Debug Console 项目",
    )
    expect(result.current.data?.relationship.stage).toBe("close_friend")
    expect(result.current.data?.emotionHistory[0].emotion).toBe("sad")
  })

  it("maps memories with hitThisTurn defaulting to false", async () => {
    const wrapper = makeWrapper()
    const { result } = renderHook(() => useMemories("rich-user"), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(3)
    expect(result.current.data?.[0].hitThisTurn).toBe(false)
    expect(result.current.data?.[0].memoryType).toBe("goal")
  })

  it("returns complete trace immediately when backend is done", async () => {
    const wrapper = makeWrapper()
    const { result } = renderHook(() => useTurnTrace("t-rich-1"), { wrapper })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.status).toBe("complete")
    expect(result.current.data?.steps.map((s) => s.name)).toContain("llm")
    expect(
      result.current.data?.steps.find((s) => s.status === "warn")?.name,
    ).toBe("turn_analyzer")
  })

  it("polls a forever-pending trace only up to the bounded attempts", async () => {
    let traceFetches = 0
    server.events.on("request:end", ({ request }) => {
      if (new URL(request.url).pathname.includes("/debug/turns/")) traceFetches += 1
    })

    const wrapper = makeWrapper()
    const { result } = renderHook(
      () => useTurnTrace("__pending__", { pollIntervalMs: 5 }),
      { wrapper },
    )

    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 3000 })

    expect(traceFetches).toBeLessThanOrEqual(TRACE_POLL_MAX_FETCHES)
    expect(result.current.error).toBeInstanceOf(PendingTraceSignal)
    expect(isTraceNotFound(result.current.error)).toBe(false)

    server.events.removeAllListeners()
  }, 20_000)

  it("stops polling on 404 and exposes not-found error", async () => {
    const wrapper = makeWrapper()
    const { result } = renderHook(() => useTurnTrace("no-such-turn"), { wrapper })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(isTraceNotFound(result.current.error)).toBe(true)
  })

  it("caches different users under separate query keys", async () => {
    const wrapper = makeWrapper()
    const rich = renderHook(() => useMemories("rich-user"), { wrapper })
    const empty = renderHook(() => useMemories("empty-user"), { wrapper })
    await waitFor(() => expect(rich.result.current.isSuccess).toBe(true))
    await waitFor(() => expect(empty.result.current.isSuccess).toBe(true))
    expect(rich.result.current.data?.length).toBe(3)
    expect(empty.result.current.data?.length).toBe(0)
  })
})
