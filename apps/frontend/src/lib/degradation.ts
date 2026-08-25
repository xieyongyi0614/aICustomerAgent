import type { RoleMode } from "@/types/domain/chat-meta"
import type { TurnAnalysis } from "@/types/domain/chat-meta"

export const DEGRADED_CONFIDENCE_THRESHOLD = 0.5

export function isPossiblyDegradedRouter(roleMode: RoleMode): boolean {
  return roleMode.confidence < DEGRADED_CONFIDENCE_THRESHOLD
}

const DEFAULT_TRIO = {
  emotion: "neutral",
  event: "daily",
  behavior: "normal_reply",
} as const

export function isDefaultAnalysisCombo(analysis: TurnAnalysis): boolean {
  return (
    analysis.userEmotion.emotion === DEFAULT_TRIO.emotion &&
    analysis.userEmotion.event === DEFAULT_TRIO.event &&
    analysis.behavior.behavior === DEFAULT_TRIO.behavior &&
    analysis.behavior.reason.trim().length === 0
  )
}

export type RouterDegradationReason =
  | "low-confidence"
  | "missing-mode"
  | null

export function inspectRoleMode(roleMode: RoleMode | null): RouterDegradationReason {
  if (roleMode === null) return "missing-mode"
  if (isPossiblyDegradedRouter(roleMode)) return "low-confidence"
  return null
}
