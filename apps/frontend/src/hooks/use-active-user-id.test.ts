// @vitest-environment jsdom
import { renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { useActiveUserId } from "./use-active-user-id"
import { useChatStore } from "@/stores/chat-store"

describe("useActiveUserId", () => {
  it("returns empty before session hydration (no fabricated identity)", () => {
    useChatStore.setState({ sessionId: null })
    const { result } = renderHook(() => useActiveUserId())
    expect(result.current).toBe("")
  })

  it("follows the active session identity once hydrated", () => {
    useChatStore.setState({ sessionId: "fp-device-1" })
    const { result } = renderHook(() => useActiveUserId())
    expect(result.current).toBe("fp-device-1")
    useChatStore.setState({ sessionId: null })
  })
})