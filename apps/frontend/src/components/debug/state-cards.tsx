import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { MeterBar } from "@/components/ui/meter-bar"
import { JsonViewer } from "@/features/json-viewer/json-viewer"
import { STAGE_TICKS } from "@/lib/stage-thresholds"
import { enumBadgeClass } from "@/lib/enum-colors"
import { formatRelativeTime } from "@/lib/format"
import type { RelationshipView } from "@/types/domain/observability"

const IDLE_RECOVERY_HOURS = 12

function isStale(updatedAt: string | null): boolean {
  if (updatedAt === null) return false
  const ts = new Date(updatedAt).getTime()
  if (Number.isNaN(ts)) return false
  return Date.now() - ts > IDLE_RECOVERY_HOURS * 3600 * 1000
}

function RawJsonDialog({ label, data }: { label: string; data: unknown }) {
  return (
    <Dialog>
      <DialogTrigger
        render={<Button variant="ghost" size="sm" className="h-6 px-2 font-mono text-[10px]" />}
      >
        {label}
      </DialogTrigger>
      <DialogContent className="max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm">原始 JSON</DialogTitle>
        </DialogHeader>
        <JsonViewer data={data} />
      </DialogContent>
    </Dialog>
  )
}

function CharacterStateCard({
  character,
}: {
  character: {
    mood: string
    energy: number
    currentTopic: string
    innerState: string
    updatedAt: string | null
  }
}) {
  return (
    <Card data-testid="character-state-card">
      <CardHeader className="flex-row items-center justify-between pb-2">
        <CardTitle className="font-mono text-xs">Character State</CardTitle>
        <RawJsonDialog label="json" data={character} />
      </CardHeader>
      <CardContent className="flex flex-col gap-2.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase text-fg-tertiary">mood</span>
          <Badge variant="outline" className={enumBadgeClass("emotion", character.mood)}>
            {character.mood}
          </Badge>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase text-fg-tertiary">energy</span>
            <span className="font-mono tabular-nums">{character.energy.toFixed(2)}</span>
          </div>
          <MeterBar value={character.energy} toneClassName="bg-status-ok" />
        </div>
        <p>
          <span className="font-mono text-[10px] uppercase text-fg-tertiary">topic: </span>
          {character.currentTopic.length > 0 ? character.currentTopic : "—"}
        </p>
        <p className="leading-relaxed">{character.innerState}</p>
      </CardContent>
    </Card>
  )
}

function RelationshipCard({ relationship }: { relationship: RelationshipView }) {
  const dims = [
    { key: "intimacy", label: "亲密", value: relationship.intimacy, tone: "bg-rose-400" },
    { key: "trust", label: "信任", value: relationship.trust, tone: "bg-sky-400" },
    {
      key: "familiarity",
      label: "熟悉",
      value: relationship.familiarity,
      tone: "bg-emerald-400",
    },
  ] as const

  return (
    <Card data-testid="relationship-card">
      <CardHeader className="flex-row items-center justify-between pb-2">
        <CardTitle className="font-mono text-xs">Relationship</CardTitle>
        <div className="flex items-center gap-1">
          <Badge variant="outline" className={enumBadgeClass("stage", relationship.stage)}>
            {relationship.stage}
          </Badge>
          <RawJsonDialog label="json" data={relationship} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-xs">
        {dims.map((dim) => (
          <div key={dim.key}>
            <div className="mb-1 flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase text-fg-tertiary">
                {dim.label}
              </span>
              <span className="font-mono tabular-nums">{dim.value.toFixed(2)}</span>
            </div>
            <MeterBar value={dim.value} ticks={STAGE_TICKS} toneClassName={dim.tone} />
          </div>
        ))}
        {isStale(relationship.updatedAt) ? (
          <p className="font-mono text-[10px] text-status-warn" title={relationship.updatedAt ?? ""}>
            状态已超过闲置恢复窗口（{IDLE_RECOVERY_HOURS}h）
          </p>
        ) : null}
      </CardContent>
    </Card>
  )
}

function EmotionHistoryStrip({
  entries,
}: {
  entries: Array<{
    emotion: string
    event: string
    createdAt: string
  }>
}) {
  if (entries.length === 0) {
    return (
      <p data-testid="emotion-history-empty" className="font-mono text-xs text-fg-tertiary">
        暂无情绪历史
      </p>
    )
  }
  return (
    <div data-testid="emotion-history-strip" className="flex flex-wrap items-center gap-1.5">
      {entries.map((entry, index) => (
        <span
          key={`${entry.createdAt}-${index}`}
          className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5"
          title={`${entry.event} · ${formatRelativeTime(new Date(entry.createdAt).getTime())}`}
        >
          <Badge variant="outline" className={enumBadgeClass("emotion", entry.emotion)}>
            {entry.emotion}
          </Badge>
          <span className="font-mono text-[10px] text-fg-tertiary">{entry.event}</span>
        </span>
      ))}
    </div>
  )
}

export { CharacterStateCard, EmotionHistoryStrip, RelationshipCard }
