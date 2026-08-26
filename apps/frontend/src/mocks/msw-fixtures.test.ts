import { describe, expect, it } from "vitest"

import { EMPTY_USER, NEAR_UPGRADE_USER, RICH_USER } from "./fixtures"
import { STAGE_TICKS } from "@/lib/stage-thresholds"

type Persona = typeof EMPTY_USER

const PERSONAS: Array<[string, Persona]> = [
  ["empty-user", EMPTY_USER],
  ["rich-user", RICH_USER],
  ["near-upgrade-user", NEAR_UPGRADE_USER],
]

function inUnitRange(value: number): boolean {
  return Number.isFinite(value) && value >= 0 && value <= 1
}

describe("persona fixtures domain constraints", () => {
  it("keeps all numeric state fields within [0,1]", () => {
    for (const [, persona] of PERSONAS) {
      const cs = persona.state.character_state
      expect(inUnitRange(cs.energy)).toBe(true)
      const rs = persona.state.relationship_state
      for (const v of [rs.intimacy, rs.trust, rs.familiarity]) {
        expect(inUnitRange(v)).toBe(true)
      }
      for (const h of persona.state.emotion_history) {
        expect(inUnitRange(h.energy_after)).toBe(true)
      }
    }
  })

  it("keeps importance values within [0,1]", () => {
    for (const [, persona] of PERSONAS) {
      for (const m of persona.memories.memories) {
        expect(inUnitRange(m.importance)).toBe(true)
      }
    }
  })

  it("near-upgrade persona sits just below the close_friend thresholds", () => {
    const rs = NEAR_UPGRADE_USER.state.relationship_state
    expect(rs.stage).toBe("friend")
    expect(rs.intimacy).toBeLessThan(STAGE_TICKS[1])
    expect(rs.trust).toBeLessThan(STAGE_TICKS[1])
    expect(rs.intimacy).toBeGreaterThan(0.5)
    expect(rs.trust).toBeGreaterThan(0.5)
  })

  it("rich persona already qualifies for close_friend", () => {
    const rs = RICH_USER.state.relationship_state
    expect(rs.stage).toBe("close_friend")
    expect(rs.intimacy).toBeGreaterThanOrEqual(STAGE_TICKS[1])
    expect(rs.trust).toBeGreaterThanOrEqual(STAGE_TICKS[1])
  })
})
