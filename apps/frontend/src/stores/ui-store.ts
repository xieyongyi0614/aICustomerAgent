import { create } from "zustand"

export type DebugTabValue =
  | "overview"
  | "scene"
  | "state"
  | "memory"
  | "trace"
  | "raw"

interface UiState {
  activeTab: DebugTabValue
  selectedTurnId: string | null
  selectedStepName: string | null
  highlightMessageId: string | null
  setActiveTab(tab: DebugTabValue): void
  setSelectedTurnId(turnId: string | null): void
  setSelectedStepName(step: string | null): void
  setHighlightMessageId(messageId: string | null): void
  openTurnInTrace(turnId: string | null): void
}

export const useUiStore = create<UiState>()((set) => ({
  activeTab: "overview",
  selectedTurnId: null,
  selectedStepName: null,
  highlightMessageId: null,
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedTurnId: (turnId) => set({ selectedTurnId: turnId }),
  setSelectedStepName: (step) => set({ selectedStepName: step }),
  setHighlightMessageId: (messageId) => set({ highlightMessageId: messageId }),
  openTurnInTrace: (turnId) =>
    set({
      selectedTurnId: turnId,
      activeTab: "trace",
      selectedStepName: null,
      highlightMessageId: null,
    }),
}))
