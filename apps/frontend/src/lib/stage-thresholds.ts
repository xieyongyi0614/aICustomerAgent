import type { RelationshipView } from "@/types/domain/observability"

export const STAGE_TICKS = [0.35, 0.55, 0.75] as const

export const STAGE_HYSTERESIS = 0.1

export interface StageProgress {
  targetStage: string
  gaps: Array<{ dim: "intimacy" | "trust" | "familiarity"; missing: number }>
}

export function nextStageProgress(
  relationship: Pick<RelationshipView, "intimacy" | "trust" | "familiarity" | "stage">,
): StageProgress | null {
  switch (relationship.stage) {
    case "stranger":
      return gapFor("friend", [
        ["familiarity", relationship.familiarity, 0.35],
      ])
    case "friend":
      return gapFor("close_friend", [
        ["intimacy", relationship.intimacy, 0.55],
        ["trust", relationship.trust, 0.55],
      ])
    case "close_friend":
      return gapFor("partner", [
        ["intimacy", relationship.intimacy, 0.75],
        ["trust", relationship.trust, 0.75],
      ])
    default:
      return null
  }
}

function gapFor(
  targetStage: string,
  dims: Array<["intimacy" | "trust" | "familiarity", number, number]>,
): StageProgress | null {
  const gaps = dims
    .map(([dim, value, threshold]) => ({ dim, missing: threshold - value }))
    .filter((g) => g.missing > 0)
  if (gaps.length === 0) return null
  return { targetStage, gaps }
}
