import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest"
import { setupServer } from "msw/node"

import { restHandlers } from "./msw-handlers"

const server = setupServer(...restHandlers)

beforeAll(() => server.listen({ onUnhandledRequest: "error" }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

function base(path: string): string {
  return `http://localhost:5175${path}`
}

describe("msw handler scenarios", () => {
  it("returns 500 for memories when the error scenario is enabled", async () => {
    const resp = await fetch(base("/api/v1/memories?user_id=rich-user&__scenario=error500"))
    expect(resp.status).toBe(500)
    const body = (await resp.json()) as { detail: string }
    expect(body.detail).toContain("memories")
  })

  it("serves the near-upgrade persona on demand", async () => {
    const resp = await fetch(base("/api/v1/state?user_id=near-upgrade-user"))
    const body = (await resp.json()) as {
      relationship_state: { stage: string }
      emotion_history: Array<{ event: string }>
    }
    expect(body.relationship_state.stage).toBe("friend")
    expect(body.emotion_history[0].event).toBe("achievement")
  })

  it("simulates latency via the delay switch", async () => {
    const started = Date.now()
    await fetch(base("/api/v1/state?user_id=rich-user&__delay=120"))
    expect(Date.now() - started).toBeGreaterThanOrEqual(100)
  })

  it("returns 404 only for unknown conversation ids", async () => {
    const ghost = await fetch(base("/api/v1/conversations/ghost-session/messages"))
    expect(ghost.status).toBe(404)
    const known = await fetch(base("/api/v1/conversations/s-1/messages"))
    expect(known.status).toBe(200)
  })

  it("exposes the forever-pending trace id for timeout drills", async () => {
    const resp = await fetch(base("/api/v1/debug/turns/__timeout__/trace"))
    const body = (await resp.json()) as { status: string; steps: unknown[] }
    expect(body.status).toBe("pending")
    expect(body.steps).toHaveLength(0)
  })
})
