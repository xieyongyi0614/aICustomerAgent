// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest"

const { fingerprintLoad } = vi.hoisted(() => ({
  fingerprintLoad: vi.fn(),
}))

vi.mock("@fingerprintjs/fingerprintjs", () => ({ load: fingerprintLoad }))

const { readStoredSessionId, writeStoredSessionId, clearStoredSessionId, resolveInitialSessionId } =
  await import("./session-id-storage")

describe("session-id-storage", () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it("resolves the initial session id from the device fingerprint and persists it", async () => {
    fingerprintLoad.mockResolvedValue({ get: async () => ({ visitorId: "abc123def456" }) })

    const first = await resolveInitialSessionId()

    expect(first).toBe("abc123def456")
    expect(readStoredSessionId()).toBe("abc123def456")

    fingerprintLoad.mockRejectedValue(new Error("should not be called again"))
    const second = await resolveInitialSessionId()
    expect(second).toBe("abc123def456")
  })

  it("prefers the stored custom session id over the fingerprint", async () => {
    writeStoredSessionId("my-custom-session")
    fingerprintLoad.mockResolvedValue({ get: async () => ({ visitorId: "abc123def456" }) })

    const resolved = await resolveInitialSessionId()

    expect(resolved).toBe("my-custom-session")
  })

  it("falls back to a random id when fingerprinting fails", async () => {
    fingerprintLoad.mockRejectedValue(new Error("fp unavailable"))

    const resolved = await resolveInitialSessionId()

    expect(resolved).toMatch(/^fallback-session-/)
    expect(readStoredSessionId()).toBe(resolved)
  })

  it("rejects blank values when writing", () => {
    writeStoredSessionId("   ")
    expect(readStoredSessionId()).toBeNull()
  })

  it("clears the stored value back to nothing", () => {
    writeStoredSessionId("to-be-cleared")
    clearStoredSessionId()
    expect(readStoredSessionId()).toBeNull()
  })
})
