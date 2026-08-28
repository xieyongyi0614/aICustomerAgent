import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { NEUTRAL_BADGE_CLASS, enumBadgeClass } from "@/lib/enum-colors"
import { useChatStore } from "@/stores/chat-store"
import type { SceneIntentResult, SceneState } from "@/types/domain/chat-meta"

interface KeyValueRowProps {
  label: string
  children: React.ReactNode
}

function KeyValueRow({ label, children }: KeyValueRowProps) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 font-mono text-[10px] uppercase text-fg-tertiary">
        {label}
      </span>
      <span className="text-right text-xs">{children}</span>
    </div>
  )
}

function SceneIntentCard({ sceneIntent }: { sceneIntent: SceneIntentResult }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between font-mono text-xs">
          <span>Scene Intent</span>
          <Badge variant="outline" className={NEUTRAL_BADGE_CLASS}>
            {sceneIntent.intent}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <KeyValueRow label="confidence">
          <span className="font-mono tabular-nums">
            {sceneIntent.confidence.toFixed(2)}
          </span>
        </KeyValueRow>
        {sceneIntent.reason.length > 0 ? (
          <p className="break-words text-xs leading-relaxed text-muted-foreground">
            {sceneIntent.reason}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function SceneStateCard({ sceneState }: { sceneState: SceneState }) {
  const pending = sceneState.pendingAction
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="font-mono text-xs">Scene State</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <KeyValueRow label="location">
          <span className="font-mono">{sceneState.location ?? "—"}</span>
        </KeyValueRow>
        <KeyValueRow label="activity">
          <span className="font-mono">{sceneState.currentActivity ?? "—"}</span>
        </KeyValueRow>
        <KeyValueRow label="action">
          <span className="font-mono">{sceneState.currentAction ?? "—"}</span>
        </KeyValueRow>
        <KeyValueRow label="mood">
          <span className="font-mono">{sceneState.sceneMood ?? "—"}</span>
        </KeyValueRow>
        <KeyValueRow label="pending">
          {pending === null ? (
            <span className="font-mono text-fg-tertiary">无</span>
          ) : (
            <span className="flex items-center gap-2">
              <span className="font-mono">{pending.action}</span>
              <Badge
                variant="outline"
                className={enumBadgeClass("status", pending.status)}
              >
                {pending.status}
              </Badge>
            </span>
          )}
        </KeyValueRow>
      </CardContent>
    </Card>
  )
}

function ScenePanel() {
  const turnMeta = useChatStore((s) => s.turnMeta)

  if (turnMeta === null) {
    return (
      <p className="font-mono text-xs text-fg-tertiary">
        发送第一条消息后，这里将实时展示场景状态。
      </p>
    )
  }

  return (
    <div data-testid="scene-panel" className="flex flex-col gap-3">
      {turnMeta.sceneIntent ? (
        <SceneIntentCard sceneIntent={turnMeta.sceneIntent} />
      ) : null}
      {turnMeta.sceneState ? (
        <SceneStateCard sceneState={turnMeta.sceneState} />
      ) : (
        <p className="font-mono text-xs text-fg-tertiary">
          本轮未下发场景状态（旧契约或降级路径）
        </p>
      )}
    </div>
  )
}

export { ScenePanel }