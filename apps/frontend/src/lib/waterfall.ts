import type { TraceStep } from "@/types/domain/observability"

export const CANONICAL_STEP_ORDER = [
  "role_router",
  "turn_analyzer",
  "memory_retrieval",
  "context_builder",
  "prompt_builder",
  "llm",
  "state_update",
  "memory_extractor",
] as const

export const PARALLEL_STEP_NAMES = new Set<string>(["role_router", "turn_analyzer"])

export const BACKGROUND_STEP_NAMES = new Set<string>(["state_update", "memory_extractor"])

const MIN_BAR_PCT = 4
const ZERO_DURATION_BAR_PCT = 6

export interface WaterfallRow {
  step: TraceStep
  barPct: number
  isParallel: boolean
  isBackground: boolean
  isUnknown: boolean
}

function sqrtScalePct(durationMs: number, maxDurationMs: number): number {
  if (durationMs <= 0) return ZERO_DURATION_BAR_PCT
  if (maxDurationMs <= 0) return MIN_BAR_PCT
  const pct = (Math.sqrt(durationMs / maxDurationMs) * 100) | 0
  return Math.max(pct, MIN_BAR_PCT)
}

export function buildWaterfallRows(steps: readonly TraceStep[]): WaterfallRow[] {
  const maxDuration = steps.reduce((acc, s) => Math.max(acc, s.durationMs), 0)
  const known = new Map<string, TraceStep>()
  const extras: TraceStep[] = []
  const canonicalSet = new Set<string>(CANONICAL_STEP_ORDER)

  for (const step of steps) {
    if (canonicalSet.has(step.name)) known.set(step.name, step)
    else extras.push(step)
  }

  const rows: WaterfallRow[] = CANONICAL_STEP_ORDER.filter((name) =>
    known.has(name),
  ).map((name) => {
    const step = known.get(name) as TraceStep
    return {
      step,
      barPct: sqrtScalePct(step.durationMs, maxDuration),
      isParallel: PARALLEL_STEP_NAMES.has(name),
      isBackground: BACKGROUND_STEP_NAMES.has(name),
      isUnknown: false,
    }
  })

  for (const step of extras) {
    rows.push({
      step,
      barPct: sqrtScalePct(step.durationMs, maxDuration),
      isParallel: false,
      isBackground: false,
      isUnknown: true,
    })
  }
  return rows
}
