import { describe, expect, it } from "vitest"

import { buildWaterfallRows } from "./waterfall"
import type { TraceStep, TraceStepStatus } from "@/types/domain/observability"

function step(name: string, durationMs: number, status: TraceStepStatus = "ok"): TraceStep {
  return { name, status, durationMs, firstTokenMs: null, error: null }
}

describe("buildWaterfallRows", () => {
  it("scales bar widths with sqrt and clamps minimums", () => {
    const rows = buildWaterfallRows([
      step("llm", 4820),
      step("role_router", 120),
      step("context_builder", 0),
    ])
    const byName = new Map(rows.map((r) => [r.step.name, r.barPct]))
    expect(byName.get("llm")).toBe(100)
    expect(byName.get("role_router")).toBe(Math.max(Math.sqrt(120 / 4820) * 100 | 0, 4))
    expect(byName.get("context_builder")).toBe(6)
  })

  it("orders canonical steps first and appends unknown names neutrally", () => {
    const rows = buildWaterfallRows([
      step("tool:search", 40),
      step("memory_extractor", 300),
      step("llm", 1000),
    ])
    expect(rows.map((r) => r.step.name)).toEqual([
      "llm",
      "memory_extractor",
      "tool:search",
    ])
    expect(rows[2].isUnknown).toBe(true)
    expect(rows[0].isUnknown).toBe(false)
  })

  it("tags parallel and background steps", () => {
    const rows = buildWaterfallRows([
      step("role_router", 10),
      step("turn_analyzer", 10),
      step("llm", 10),
      step("state_update", 10),
    ])
    const flags = new Map(rows.map((r) => [r.step.name, r]))
    expect(flags.get("role_router")?.isParallel).toBe(true)
    expect(flags.get("turn_analyzer")?.isParallel).toBe(true)
    expect(flags.get("llm")?.isParallel).toBe(false)
    expect(flags.get("state_update")?.isBackground).toBe(true)
  })
})
