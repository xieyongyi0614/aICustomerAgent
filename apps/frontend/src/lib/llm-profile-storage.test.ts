// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"

import {
  clearStoredLlmProfile,
  readStoredLlmProfile,
  resolveActiveLlmProfileId,
  writeStoredLlmProfile,
} from "./llm-profile-storage"

const PROFILES = [
  { id: "longcat", default: true },
  { id: "minimax-m3", default: false },
]

afterEach(() => {
  clearStoredLlmProfile()
})

describe("llm profile storage", () => {
  it("falls back to the default profile when nothing is stored", () => {
    expect(resolveActiveLlmProfileId(PROFILES)).toBe("longcat")
  })

  it("keeps a stored selection while it stays valid", () => {
    writeStoredLlmProfile("minimax-m3")
    expect(resolveActiveLlmProfileId(PROFILES)).toBe("minimax-m3")
    expect(readStoredLlmProfile()).toBe("minimax-m3")
  })

  it("clears stale stored ids and falls back to the default profile", () => {
    writeStoredLlmProfile("ghost")
    expect(resolveActiveLlmProfileId(PROFILES)).toBe("longcat")
    expect(readStoredLlmProfile()).toBeNull()
  })
})