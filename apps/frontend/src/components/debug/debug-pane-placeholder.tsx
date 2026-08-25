import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

const DEBUG_TABS = [
  { value: "overview", label: "Overview" },
  { value: "state", label: "State" },
  { value: "memory", label: "Memory" },
  { value: "trace", label: "Trace" },
  { value: "raw", label: "Raw" },
] as const

function DebugPanePlaceholder() {
  return (
    <Tabs defaultValue="overview" className="flex min-h-0 flex-1 flex-col gap-2 p-3">
      <TabsList className="w-fit">
        {DEBUG_TABS.map((tab) => (
          <TabsTrigger key={tab.value} value={tab.value} className="text-xs">
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {DEBUG_TABS.map((tab) => (
        <TabsContent key={tab.value} value={tab.value} className="min-h-0 flex-1">
          <p className="font-mono text-xs text-fg-tertiary">
            [{tab.label}] Phase 2 提供
          </p>
        </TabsContent>
      ))}
    </Tabs>
  )
}

export { DebugPanePlaceholder }
