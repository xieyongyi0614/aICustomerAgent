import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { MeterBar } from "@/components/ui/meter-bar"
import {
  DEGRADED_BADGE_CLASS,
  NEUTRAL_BADGE_CLASS,
  enumBadgeClass,
} from "@/lib/enum-colors"
import {
  DEGRADED_CONFIDENCE_THRESHOLD,
  isDefaultAnalysisCombo,
} from "@/lib/degradation"
import { useChatStore } from "@/stores/chat-store"
import type { RoleMode, TurnAnalysis } from "@/types/domain/chat-meta"

function KeyValueRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 font-mono text-[10px] uppercase text-fg-tertiary">{label}</span>
      <span className="text-right text-xs">{children}</span>
    </div>
  )
}

function RoleModeCard({ roleMode }: { roleMode: RoleMode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between font-mono text-xs">
          <span>Role Mode</span>
          <Badge variant="outline" className={enumBadgeClass("mode", roleMode.mode)}>
            {roleMode.mode}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <KeyValueRow label="intent">
          <Badge variant="outline" className={NEUTRAL_BADGE_CLASS}>
            {roleMode.intent}
          </Badge>
        </KeyValueRow>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase text-fg-tertiary">confidence</span>
            <span className="font-mono text-xs tabular-nums">
              {roleMode.confidence.toFixed(2)}
            </span>
          </div>
          <MeterBar
            value={roleMode.confidence}
            ticks={[DEGRADED_CONFIDENCE_THRESHOLD]}
            toneClassName={
              roleMode.confidence < DEGRADED_CONFIDENCE_THRESHOLD
                ? "bg-status-warn"
                : "bg-status-ok"
            }
          />
        </div>
        {roleMode.reason.length > 0 ? (
          <p className="break-words text-xs leading-relaxed text-muted-foreground">
            {roleMode.reason}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function TurnAnalysisCard({
  analysis,
  showWeakHint,
}: {
  analysis: TurnAnalysis
  showWeakHint: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between font-mono text-xs">
          <span>Turn Analysis</span>
          {showWeakHint ? (
            <Badge variant="outline" className={NEUTRAL_BADGE_CLASS}>
              默认分析
            </Badge>
          ) : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <KeyValueRow label="emotion">
          <Badge variant="outline" className={enumBadgeClass("emotion", analysis.userEmotion.emotion)}>
            {analysis.userEmotion.emotion}
          </Badge>
        </KeyValueRow>
        <KeyValueRow label="event">
          <span className="font-mono">{analysis.userEmotion.event}</span>
        </KeyValueRow>
        <KeyValueRow label="behavior">
          <Badge variant="outline" className={enumBadgeClass("behavior", analysis.behavior.behavior)}>
            {analysis.behavior.behavior}
          </Badge>
        </KeyValueRow>
        {analysis.behavior.reason.length > 0 ? (
          <p className="break-words text-xs leading-relaxed text-muted-foreground">
            {analysis.behavior.reason}
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function OverviewPanel() {
  const turnMeta = useChatStore((s) => s.turnMeta)
  const hasMessages = useChatStore((s) => s.messages.length > 0)
  const hasCompletedTurn = useChatStore((s) =>
    s.messages.some((m) => m.role === "ai" && m.status !== "pending" && m.status !== "streaming"),
  )

  if (turnMeta === null) {
    if (!hasMessages) {
      return (
        <p className="font-mono text-xs text-fg-tertiary">
          发送第一条消息后，这里将实时展示路由与分析结果。
        </p>
      )
    }
    if (hasCompletedTurn) {
      return (
        <div data-testid="meta-missing" className="rounded-md border border-status-warn/50 p-3">
          <p className="text-xs text-status-warn">本轮元数据缺失（旧契约或未下发）</p>
          <p className="mt-1 font-mono text-[10px] text-fg-tertiary">
            Overview 将在 Phase 2 经 REST 回填
          </p>
        </div>
      )
    }
    return <p className="font-mono text-xs text-fg-tertiary">等待首个 token…</p>
  }

  const degraded = turnMeta.roleMode.confidence < DEGRADED_CONFIDENCE_THRESHOLD

  return (
    <div data-testid="overview-panel" className="flex flex-col gap-3">
      {degraded ? (
        <div
          data-testid="degraded-alert"
          className="flex items-center gap-2 rounded-md border border-status-warn/60 bg-status-warn/10 p-2.5"
        >
          <Badge variant="outline" className={DEGRADED_BADGE_CLASS}>
            可能已降级
          </Badge>
          <span className="font-mono text-[10px] text-fg-tertiary">
            confidence &lt; {DEGRADED_CONFIDENCE_THRESHOLD}
          </span>
        </div>
      ) : null}

      <RoleModeCard roleMode={turnMeta.roleMode} />
      <TurnAnalysisCard
        analysis={turnMeta.analysis}
        showWeakHint={isDefaultAnalysisCombo(turnMeta.analysis)}
      />

      <p className="font-mono text-[10px] text-fg-tertiary">
        [state-summary] Phase 2 经 REST 回填
      </p>
    </div>
  )
}

export { OverviewPanel }
