import { useActiveUserId } from "@/hooks/use-active-user-id"
import { OverviewPanel } from "@/components/debug/overview-panel"
import { ScenePanel } from "@/components/debug/scene-panel"
import { StatePanel } from "@/components/debug/state-panel"
import { MemoryPanel } from "@/components/debug/memory-panel"
import { TracePanel } from "@/components/debug/trace-panel"
import { RawPanel } from "@/components/debug/raw-panel"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useUiStore } from "@/stores/ui-store"
import type { DebugTabValue } from "@/stores/ui-store"

const DEBUG_TABS = [
  { value: "overview", label: "Overview" },
  { value: "scene", label: "Scene" },
  { value: "state", label: "State" },
  { value: "memory", label: "Memory" },
  { value: "trace", label: "Trace" },
  { value: "raw", label: "Raw" },
] as const satisfies ReadonlyArray<{ value: DebugTabValue; label: string }>

function DebugPane() {
  const activeTab = useUiStore((s) => s.activeTab)
  const setActiveTab = useUiStore((s) => s.setActiveTab)
  const selectedTurnId = useUiStore((s) => s.selectedTurnId)
  const activeUserId = useActiveUserId()

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
      <TabsContent value="scene" className="min-h-0 flex-1 overflow-y-auto">
        <ScenePanel />
      </TabsContent>
      <TabsContent value="state" className="min-h-0 flex-1 overflow-y-auto">
        <StatePanel userId={activeUserId} />
      </TabsContent>
      <TabsContent value="memory" className="min-h-0 flex-1 overflow-y-auto">
        <MemoryPanel userId={activeUserId} />
      </TabsContent>
      <TabsContent value="trace" className="min-h-0 flex-1 overflow-y-auto">
        <TracePanel turnId={selectedTurnId} />
      </TabsContent>
      <TabsContent value="raw" className="min-h-0 flex-1 overflow-y-auto">
        <RawPanel />
      </TabsContent>
    </Tabs>
  )
}

export { DebugPane }
export { DEBUG_TABS }
