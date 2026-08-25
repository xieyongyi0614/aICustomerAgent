// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { OverviewPanel } from "./overview-panel"
import { useChatStore } from "@/stores/chat-store"
import type { ChatMessage, MessageRole, MessageStatus } from "@/types/domain/chat-message"
import type { RoleMode, TurnAnalysis } from "@/types/domain/chat-meta"

const IMMERSIVE_META: { roleMode: RoleMode; analysis: TurnAnalysis } = {
  roleMode: {
    mode: "immersive",
    intent: "emotional",
    confidence: 0.88,
    reason: "情绪倾诉",
  },
  analysis: {
    userEmotion: { emotion: "sad", event: "setback" },
    behavior: { behavior: "comfort", reason: "先接住情绪" },
  },
}

function seed(
  meta: typeof IMMERSIVE_META | null,
  messages: Array<Partial<ChatMessage> & { id: string; role: MessageRole }> = [],
): void {
  useChatStore.setState({
    turnMeta: meta,
    messages: messages.map((m) => ({
      content: "",
      status: "complete" as MessageStatus,
      createdAt: 0,
      ...m,
    })),
  })
}

afterEach(() => {
  cleanup()
  useChatStore.setState({ turnMeta: null, messages: [], streamingMessageId: null })
})

describe("OverviewPanel", () => {
  it("guides before the first message", () => {
    render(<OverviewPanel />)
    expect(screen.getByText(/发送第一条消息后/)).toBeTruthy()
  })

  it("shows missing-meta warning after a completed turn without turn_meta", () => {
    seed(null, [{ id: "h1", role: "human" }, { id: "a1", role: "ai" }])
    render(<OverviewPanel />)
    expect(screen.getByTestId("meta-missing")).toBeTruthy()
  })

  it("renders role mode and analysis cards with enum badges", () => {
    seed(IMMERSIVE_META, [{ id: "h1", role: "human", content: "压力好大" }])
    render(<OverviewPanel />)
    expect(screen.getByText("immersive")).toBeTruthy()
    expect(screen.getByText("0.88")).toBeTruthy()
    expect(screen.getByText("情绪倾诉")).toBeTruthy()
    expect(screen.getByText("sad")).toBeTruthy()
    expect(screen.getByText("comfort")).toBeTruthy()
    expect(screen.queryByTestId("degraded-alert")).toBeNull()
  })

  it("raises the degraded alert for low-confidence routing", () => {
    seed({
      roleMode: { ...IMMERSIVE_META.roleMode, confidence: 0.2, mode: "default" },
      analysis: IMMERSIVE_META.analysis,
    })
    render(<OverviewPanel />)
    expect(screen.getByTestId("degraded-alert")).toBeTruthy()
    expect(screen.getByText("default")).toBeTruthy()
  })

  it("marks default-analysis combo with a weak hint badge instead of an alert", () => {
    seed({
      roleMode: IMMERSIVE_META.roleMode,
      analysis: {
        userEmotion: { emotion: "neutral", event: "daily" },
        behavior: { behavior: "normal_reply", reason: "" },
      },
    })
    render(<OverviewPanel />)
    expect(screen.getByText("默认分析")).toBeTruthy()
    expect(screen.queryByTestId("degraded-alert")).toBeNull()
  })
})
