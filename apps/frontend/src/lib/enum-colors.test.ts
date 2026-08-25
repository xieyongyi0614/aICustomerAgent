import { describe, expect, it } from "vitest"

import {
  BEHAVIOR_VALUES,
  DEGRADED_BADGE_CLASS,
  EMOTION_VALUES,
  MODE_VALUES,
  NEUTRAL_BADGE_CLASS,
  STAGE_VALUES,
  enumBadgeClass,
} from "./enum-colors"

describe("enum color maps", () => {
  it("covers the full backend enum sets", () => {
    expect(MODE_VALUES).toHaveLength(3)
    expect(EMOTION_VALUES).toHaveLength(8)
    expect(BEHAVIOR_VALUES).toHaveLength(7)
    expect(STAGE_VALUES).toHaveLength(4)
  })

  it("returns a defined class for every known value", () => {
    const cases: Array<[Parameters<typeof enumBadgeClass>[0], readonly string[]]> = [
      ["mode", MODE_VALUES],
      ["emotion", EMOTION_VALUES],
      ["behavior", BEHAVIOR_VALUES],
      ["stage", STAGE_VALUES],
    ]
    for (const [kind, values] of cases) {
      for (const value of values) {
        expect(enumBadgeClass(kind, value)).toBeTruthy()
      }
    }
    expect(enumBadgeClass("mode", "professional")).toContain("sky")
    expect(enumBadgeClass("stage", "partner")).toContain("pink")
  })

  it("falls back to neutral class for unknown values", () => {
    expect(enumBadgeClass("mode", "__unknown__")).toBe(NEUTRAL_BADGE_CLASS)
    expect(enumBadgeClass("emotion", "")).toBe(NEUTRAL_BADGE_CLASS)
  })

  it("keeps neutral and degraded classes visually distinct", () => {
    expect(DEGRADED_BADGE_CLASS).not.toBe(NEUTRAL_BADGE_CLASS)
    expect(DEGRADED_BADGE_CLASS).toContain("amber")
  })
})
