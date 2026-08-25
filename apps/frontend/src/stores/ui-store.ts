import { create } from "zustand"

export type DebugTabValue = "overview" | "state" | "memory" | "trace" | "raw"

interface UiState {
  activeTab: DebugTabValue
  selectedTurnId: string | null
  setActiveTab(tab: DebugTabValue): void
  setSelectedTurnId(turnId: string | null): void
}

export const useUiStore = create<UiState>()((set) => ({
  activeTab: "overview",
  selectedTurnId: null,
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedTurnId: (turnId) => set({ selectedTurnId: turnId }),
}))
