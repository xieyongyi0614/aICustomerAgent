// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"

import { copyText } from "./copy-text"

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ""
})

describe("copyText", () => {
  it("prefers the async clipboard API when available", async () => {
    const original = navigator.clipboard
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    })
    try {
      const ok = copyText("abc")
      await Promise.resolve()
      expect(ok).toBe(true)
      expect(writeText).toHaveBeenCalledWith("abc")
    } finally {
      if (original === undefined) {
        Reflect.deleteProperty(navigator, "clipboard")
      } else {
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: original,
        })
      }
    }
  })

  it("falls back to execCommand and cleans up the helper node", () => {
    const execCommand = vi.fn(() => true)
    document.execCommand = execCommand as unknown as typeof document.execCommand
    const ok = copyText("legacy")
    expect(ok).toBe(true)
    expect(execCommand).toHaveBeenCalledWith("copy")
    expect(document.body.querySelectorAll("textarea")).toHaveLength(0)
  })

  it("returns false when every strategy fails", () => {
    const originalClipboard = navigator.clipboard
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: undefined,
    })
    document.execCommand = vi.fn(() => false) as unknown as typeof document.execCommand
    try {
      expect(copyText("nope")).toBe(false)
    } finally {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: originalClipboard,
      })
    }
  })
})
