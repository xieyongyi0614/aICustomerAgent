import { describe, expect, it } from "vitest"

import { isDefaultAnalysisCombo, isPossiblyDegradedRouter } from "./degradation"
import type { RoleMode, TurnAnalysis } from "@/types/domain/chat-meta"

function makeRoleMode(confidence: number): RoleMode {
  return { mode: "immersive", intent: "emotional", confidence, reason: "情绪对话" }
}

function makeAnalysis(partial?: Partial<TurnAnalysis>): TurnAnalysis {
  return {
    userEmotion: partial?.userEmotion ?? { emotion: "sad", event: "setback" },
    behavior: partial?.behavior ?? { behavior: "comfort", reason: "接住情绪" },
  }
}

describe("degradation heuristics", () => {
  it("flags low-confidence router results", () => {
    expect(isPossiblyDegradedRouter(makeRoleMode(0.49))).toBe(true)
    expect(isPossiblyDegradedRouter(makeRoleMode(0.5))).toBe(false)
  })

  it("detects the default analysis combo emitted on turn-analyzer failure", () => {
    expect(
      isDefaultAnalysisCombo(
        makeAnalysis({
          userEmotion: { emotion: "neutral", event: "daily" },
          behavior: { behavior: "normal_reply", reason: "" },
        }),
      ),
    ).toBe(true)
  })

  it("does not flag a genuine neutral reply that carries a reason", () => {
    expect(
      isDefaultAnalysisCombo(
        makeAnalysis({
          userEmotion: { emotion: "neutral", event: "daily" },
          behavior: { behavior: "normal_reply", reason: "日常闲聊" },
        }),
      ),
    ).toBe(false)
  })

  it("does not flag non-default analyses", () => {
    expect(isDefaultAnalysisCombo(makeAnalysis())).toBe(false)
  })
})
