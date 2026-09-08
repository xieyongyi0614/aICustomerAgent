// @vitest-environment jsdom
import { renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { useActiveUserId } from "./use-active-user-id"
import { useChatStore } from "@/stores/chat-store"

describe("useActiveUserId", () => {
  it("falls back to default-user before session hydration", () => {
    useChatStore.setState({ sessionId: null })
    const { result } = renderHook(() => useActiveUserId())
    expect(result.current).toBe("default-user")
  })

  it("follows the active session identity once hydrated", () => {
    useChatStore.setState({ sessionId: "fp-device-1" })
    const { result } = renderHook(() => useActiveUserId())
    expect(result.current).toBe("fp-device-1")
    useChatStore.setState({ sessionId: null })
  })
})