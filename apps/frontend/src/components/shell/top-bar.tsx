import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { getActiveApiMode, writeStoredApiMode } from "@/api/api-mode"
import type { ApiMode } from "@/api/api-mode"
import { useChatStore } from "@/stores/chat-store"
import type { ConnectionStatus } from "@/types/domain/chat-message"
import { copyText } from "@/lib/copy-text"
import { cn } from "@/lib/utils"
import { useLlmProfiles } from "@/hooks/use-llm-profiles"
import { LlmProfileSelect } from "@/components/shell/llm-profile-select"
import { writeStoredLlmProfile } from "@/lib/llm-profile-storage"

const STATUS_DOT_CLASS: Record<ConnectionStatus, string> = {
  idle: "bg-neutral-500",
  connecting: "bg-status-warn animate-pulse",
  open: "bg-status-ok",
  closed: "bg-neutral-600",
  error: "bg-status-error animate-pulse",
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  closed: "已断开",
  error: "连接错误",
}

function switchApiModeAndReload(mode: ApiMode): void {
  writeStoredApiMode(mode)
  window.location.reload()
}

function ModeSwitchDialog({
  currentMode,
  onSwitched,
}: {
  currentMode: ApiMode
  onSwitched?: (mode: ApiMode) => void
}) {
  const targetMode: ApiMode = currentMode === "real" ? "mock" : "real"
  const [open, setOpen] = useState(false)

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
      }}
    >
      <DialogTrigger
        render={
          <Button variant="outline" size="sm" data-testid="mode-switch-trigger" className="font-mono text-xs">
            {currentMode}
          </Button>
        }
      >
        {currentMode}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="text-sm">切换 API 模式</DialogTitle>
          <DialogDescription>
            切换到 {targetMode} 模式需要刷新页面生效。当前进行中的界面状态将会丢失。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button
            size="sm"
            data-testid="mode-switch-confirm"
            onClick={() => {
              setOpen(false)
              onSwitched?.(targetMode)
              switchApiModeAndReload(targetMode)
            }}
          >
            切换并刷新
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TopBar() {
  const sessionId = useChatStore((s) => s.sessionId)
  const connectionStatus = useChatStore((s) => s.connectionStatus)
  const isStreaming = useChatStore((s) => s.streamingMessageId !== null)
  const newSession = useChatStore((s) => s.newSession)
  const { profiles, activeProfileId } = useLlmProfiles()

  return (
    <TooltipProvider>
      <div className="flex w-full items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs font-semibold">Asuna Debug Console</span>

          <Tooltip>
            <TooltipTrigger
              render={<span data-testid="connection-dot" tabIndex={0} />}
              className={cn(
                "inline-block size-2 rounded-full",
                STATUS_DOT_CLASS[connectionStatus],
              )}
            />
            <TooltipContent>{STATUS_LABEL[connectionStatus]}</TooltipContent>
          </Tooltip>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="session-id"
            className="max-w-[220px] truncate rounded border border-border px-2 py-1 font-mono text-[10px] text-muted-foreground hover:bg-accent"
            title={sessionId ?? "尚未创建会话"}
            onClick={() => {
              if (sessionId !== null) copyText(sessionId)
            }}
          >
            {sessionId ?? "no-session"}
          </button>

          <Button
            size="sm"
            variant="outline"
            data-testid="new-session"
            disabled={isStreaming}
            onClick={() => newSession()}
          >
            +New
          </Button>

          {profiles.length > 0 && activeProfileId !== null && (
            <LlmProfileSelect
              options={profiles}
              value={activeProfileId}
              onChange={writeStoredLlmProfile}
            />
          )}

          <ModeSwitchDialog currentMode={getActiveApiMode()} />
        </div>
      </div>
    </TooltipProvider>
  )
}

export { TopBar }
