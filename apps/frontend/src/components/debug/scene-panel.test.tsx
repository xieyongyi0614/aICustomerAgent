// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { ScenePanel } from "./scene-panel"
import { useChatStore } from "@/stores/chat-store"
import type { SceneIntentResult, SceneState } from "@/types/domain/chat-meta"

const SCENE_INTENT: SceneIntentResult = {
  intent: "correct_scene",
  confidence: 0.9,
  reason: "指出未完成动作",
}

const SCENE_STATE: SceneState = {
  sessionId: "s-1",
  turnId: 3,
  location: "客厅",
  currentActivity: "休息",
  currentAction: "切西瓜",
  pendingAction: {
    action: "把西瓜拿给用户",
    status: "pending",
    createdAtTurn: 2,
  },
  sceneMood: "relaxed",
}

function seed(
  turnMeta:
    | {
        roleMode: { mode: "immersive"; intent: "roleplay"; confidence: number; reason: string }
        analysis: {
          userEmotion: { emotion: "happy"; event: "daily" }
          behavior: { behavior: "normal_reply"; reason: string }
        }
        sceneIntent?: SceneIntentResult
        sceneState?: SceneState
      }
    | null,
): void {
  useChatStore.setState({ turnMeta, messages: [] })
}

afterEach(() => {
  cleanup()
  useChatStore.setState({ turnMeta: null, messages: [], streamingMessageId: null })
})

describe("ScenePanel", () => {
  it("guides before the first message", () => {
    render(<ScenePanel />)
    expect(screen.getByText(/发送第一条消息后/)).toBeTruthy()
  })

  it("renders scene intent and scene state", () => {
    seed({
      roleMode: { mode: "immersive", intent: "roleplay", confidence: 0.9, reason: "rp" },
      analysis: {
        userEmotion: { emotion: "happy", event: "daily" },
        behavior: { behavior: "normal_reply", reason: "" },
      },
      sceneIntent: SCENE_INTENT,
      sceneState: SCENE_STATE,
    })
    render(<ScenePanel />)
    expect(screen.getByTestId("scene-panel")).toBeTruthy()
    expect(screen.getByText("correct_scene")).toBeTruthy()
    expect(screen.getByText("客厅")).toBeTruthy()
    expect(screen.getByText("切西瓜")).toBeTruthy()
    expect(screen.getAllByText("pending").length).toBeGreaterThan(0)
    expect(screen.getByText("relaxed")).toBeTruthy()
  })

  it("shows placeholder when scene fields are absent", () => {
    seed({
      roleMode: { mode: "immersive", intent: "roleplay", confidence: 0.9, reason: "rp" },
      analysis: {
        userEmotion: { emotion: "happy", event: "daily" },
        behavior: { behavior: "normal_reply", reason: "" },
      },
    })
    render(<ScenePanel />)
    expect(screen.getByText(/本轮未下发场景状态/)).toBeTruthy()
  })
})