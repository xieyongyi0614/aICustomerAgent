import { useState } from "react"

import { DebugPanePlaceholder } from "@/components/debug/debug-pane-placeholder"
import { Button } from "@/components/ui/button"
import {
  Drawer,
  DrawerContent,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"
import { ScrollArea } from "@/components/ui/scroll-area"
import { usePersistedState } from "@/hooks/use-persisted-state"

const DEBUG_COLLAPSED_KEY = "asuna-debug.debugPaneCollapsed"

function Workbench() {
  const [collapsed, setCollapsed] = usePersistedState<boolean>(
    DEBUG_COLLAPSED_KEY,
    false,
  )
  const [drawerOpen, setDrawerOpen] = useState(false)

  return (
    <div className="flex h-screen flex-col bg-background text-foreground">
      <header
        data-testid="topbar-slot"
        className="flex h-12 shrink-0 items-center border-b border-border px-4"
      >
        <span className="font-mono text-xs text-muted-foreground">Asuna Debug Console</span>
      </header>

      <p
        data-testid="mobile-banner"
        className="hidden max-md:block px-4 py-1.5 text-center font-mono text-xs text-status-warn"
      >
        请使用桌面端获得完整调试体验
      </p>

      <div className="flex min-h-0 flex-1">
        <section
          data-testid="chat-pane"
          className="flex min-h-0 min-w-0 flex-col lg:flex-1 lg:basis-0 min-[1200px]:basis-[42%] min-[1200px]:grow-0"
        >
          <ScrollArea className="min-h-0 flex-1">
            <div className="p-4 font-mono text-xs text-fg-tertiary">[chat] Phase 1 后续任务</div>
          </ScrollArea>
        </section>

        {!collapsed ? (
          <section
            data-testid="debug-pane-inline"
            className="hidden min-h-0 min-w-0 flex-col border-l border-border lg:flex lg:w-[480px] lg:shrink-0 min-[1200px]:w-auto min-[1200px]:flex-1"
          >
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
              <span className="font-mono text-xs text-fg-tertiary">Agent Debug</span>
              <Button
                variant="ghost"
                size="sm"
                data-testid="debug-collapse"
                onClick={() => setCollapsed(true)}
              >
                »
              </Button>
            </div>
            <DebugPanePlaceholder />
          </section>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            data-testid="debug-restore"
            className="self-start"
            onClick={() => setCollapsed(false)}
          >
            «
          </Button>
        )}
      </div>

      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DrawerTrigger
          render={
            <Button
              variant="outline"
              size="sm"
              data-testid="debug-drawer-trigger"
              className="fixed right-4 bottom-4 z-40 lg:hidden"
            />
          }
        >
          Debug
        </DrawerTrigger>
        <DrawerContent className="h-[70vh]">
          <DrawerHeader>
            <DrawerTitle className="font-mono text-sm">Agent Debug</DrawerTitle>
          </DrawerHeader>
          <div className="min-h-0 flex-1 overflow-hidden">
            <DebugPanePlaceholder />
          </div>
        </DrawerContent>
      </Drawer>
    </div>
  )
}

export { Workbench }
