import { describe, expect, it } from "vitest"

import { resolveApiMode } from "./api-mode"

describe("resolveApiMode", () => {
  it("prefers a valid stored override over env", () => {
    expect(resolveApiMode("real", "mock")).toBe("mock")
    expect(resolveApiMode("mock", "real")).toBe("real")
  })

  it("uses env value when stored is missing or invalid", () => {
    expect(resolveApiMode("mock", null)).toBe("mock")
    expect(resolveApiMode("mock", "bogus")).toBe("mock")
    expect(resolveApiMode(undefined, undefined)).toBe("real")
  })
})
