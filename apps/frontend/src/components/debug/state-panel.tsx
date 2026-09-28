import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  CharacterStateCard,
  EmotionHistoryStrip,
  RelationshipCard,
} from "@/components/debug/state-cards"
import { useCharacterState } from "@/hooks/use-observability"
import { nextStageProgress } from "@/lib/stage-thresholds"

interface StatePanelProps {
  userId?: string
}

function StatePanelInner({ userId }: { userId: string }) {
  const query = useCharacterState(userId)

  if (query.isPending) {
    return (
      <div data-testid="state-skeleton" className="flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-28 animate-pulse rounded-md border border-border bg-muted/40" />
        ))}
      </div>
    )
  }

  if (query.isError || query.data === undefined) {
    return (
      <div
        data-testid="state-error"
        className="flex flex-col items-start gap-2 rounded-md border border-status-error/50 p-3"
      >
        <p className="text-xs text-status-error">状态快照加载失败</p>
        <p className="font-mono text-[10px] text-fg-tertiary">{String(query.error)}</p>
        <Button size="sm" variant="outline" onClick={() => query.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  const snapshot = query.data
  const progress = nextStageProgress(snapshot.relationship)

  return (
    <div data-testid="state-panel" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-fg-tertiary">user: {userId}</span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 font-mono text-[10px]"
          data-testid="state-refresh"
          onClick={() => query.refetch()}
        >
          刷新
        </Button>
      </div>

      <CharacterStateCard character={snapshot.characterState} />
      <RelationshipCard relationship={snapshot.relationship} />

      {progress !== null ? (
        <p data-testid="stage-progress-hint" className="font-mono text-[10px] text-muted-foreground">
          距下一阶段「{progress.targetStage}」：
          {progress.gaps
            .map((g) => `${g.dim} 还差 ${g.missing.toFixed(2)}`)
            .join("，")}
        </p>
      ) : (
        <p className="font-mono text-[10px] text-fg-tertiary">已达到当前最高阶段</p>
      )}

      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="font-mono text-xs">Emotion History</CardTitle>
        </CardHeader>
        <CardContent>
          <EmotionHistoryStrip entries={snapshot.emotionHistory} />
        </CardContent>
      </Card>

      {snapshot.relationshipEvents.length > 0 ? (
        <Card data-testid="relationship-events-card">
          <CardHeader className="pb-1">
            <CardTitle className="font-mono text-xs">Relationship Events</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2 text-xs">
            {snapshot.relationshipEvents.map((event) => (
              <div
                key={`${event.type}-${event.createdAt}`}
                data-testid="relationship-event-item"
                className="flex items-center gap-2"
              >
                <Badge variant="outline" className="font-mono">
                  {event.type}
                </Badge>
                <span className="font-mono text-[10px] text-fg-tertiary">
                  {event.magnitude}
                </span>
                <span className="font-mono text-[10px] text-fg-tertiary">
                  {event.source}
                </span>
                <span className="ml-auto font-mono text-[10px] tabular-nums">
                  trust {event.impactTrust >= 0 ? "+" : ""}
                  {event.impactTrust.toFixed(2)}
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function StatePanel(props: StatePanelProps) {
  const userId = props.userId ?? ""
  return <StatePanelInner key={userId} userId={userId} />
}

export { StatePanel }
