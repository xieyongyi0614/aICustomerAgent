import { describe, expect, it } from "vitest"

import { formatDurationMs, formatRelativeTime } from "./format"

const NOW = Date.UTC(2026, 7, 25, 12, 0, 0)

describe("formatRelativeTime", () => {
  it("formats recent deltas in Chinese", () => {
    expect(formatRelativeTime(NOW - 30_000, NOW)).toBe("刚刚")
    expect(formatRelativeTime(NOW - 5 * 60_000, NOW)).toBe("5 分钟前")
    expect(formatRelativeTime(NOW - 3 * 3600_000, NOW)).toBe("3 小时前")
  })

  it("falls back to absolute date-time beyond a day", () => {
    const ts = Date.UTC(2026, 7, 24, 9, 5, 0)
    const rendered = formatRelativeTime(ts, NOW)
    expect(rendered).toMatch(/^\d{1,2}-\d{1,2} \d{2}:\d{2}$/)
    expect(rendered.startsWith("8-24")).toBe(true)
    expect(rendered.endsWith(":05")).toBe(true)
  })
})

describe("formatDurationMs", () => {
  it("switches unit at one second", () => {
    expect(formatDurationMs(4820)).toBe("4.8s")
    expect(formatDurationMs(120)).toBe("120ms")
  })
})
