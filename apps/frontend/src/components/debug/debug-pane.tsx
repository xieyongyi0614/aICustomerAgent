import { OverviewPanel } from "@/components/debug/overview-panel"
import { StatePanel } from "@/components/debug/state-panel"
import { MemoryPanel } from "@/components/debug/memory-panel"
import { TracePanel } from "@/components/debug/trace-panel"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useUiStore } from "@/stores/ui-store"
import type { DebugTabValue } from "@/stores/ui-store"

const DEBUG_TABS = [
  { value: "overview", label: "Overview" },
  { value: "state", label: "State" },
  { value: "memory", label: "Memory" },
  { value: "trace", label: "Trace" },
  { value: "raw", label: "Raw" },
] as const satisfies ReadonlyArray<{ value: DebugTabValue; label: string }>

function TabPlaceholder({ tab }: { tab: string }) {
  return <p className="font-mono text-xs text-fg-tertiary">[{tab}] Phase 2 提供</p>
}

function DebugPane() {
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const selectedTurnId = useUiStore((s) => s.selectedTurnId)

  return (
    <Tabs
      value={activeTab}
      onValueChange={(v) => setActiveTab(v as DebugTabValue)}
      className="flex min-h-0 flex-1 flex-col gap-2 p-3"
    >
      <TabsList className="w-fit">
        {DEBUG_TABS.map((tab) => (
          <TabsTrigger key={tab.value} value={tab.value} className="text-xs">
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="overview" className="min-h-0 flex-1 overflow-y-auto">
        <OverviewPanel />
      </TabsContent>
      <TabsContent value="state" className="min-h-0 flex-1 overflow-y-auto">
        <StatePanel />
      </TabsContent>
      <TabsContent value="memory" className="min-h-0 flex-1 overflow-y-auto">
        <MemoryPanel />
      </TabsContent>
      <TabsContent value="trace" className="min-h-0 flex-1 overflow-y-auto">
        <TracePanel turnId={selectedTurnId} />
      </TabsContent>
      {DEBUG_TABS.filter(
        (t) =>
          t.value !== "overview" &&
          t.value !== "state" &&
          t.value !== "memory" &&
          t.value !== "trace",
      ).map((tab) => (
        <TabsContent key={tab.value} value={tab.value} className="min-h-0 flex-1 overflow-y-auto">
          <TabPlaceholder tab={tab.label} />
        </TabsContent>
      ))}
    </Tabs>
  )
}

export { DebugPane }
export { DEBUG_TABS }
