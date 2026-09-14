import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { NEUTRAL_BADGE_CLASS, enumBadgeClass } from "@/lib/enum-colors"
import { cn } from "@/lib/utils"
import {
  useWorldPlan,
  useWorldSimTick,
  useWorldSimulation,
  useWorldSituations,
} from "@/hooks/use-world-sim"
import type { WorldSimPlanBlock, WorldSimSituation } from "@/api/world-sim"

const BLOCK_STATUS_TONE: Record<string, string> = {
  planned: "bg-slate-400/15 text-slate-300 border-slate-400/40",
  active: "bg-emerald-500/15 text-emerald-300 border-emerald-500/40",
  completed: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  skipped: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  superseded: "bg-neutral-500/15 text-neutral-300 border-neutral-500/40",
}

function padMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`
}

function KeyValueRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="shrink-0 font-mono text-[10px] uppercase text-fg-tertiary">{label}</span>
      <span className="text-right text-xs">{children}</span>
    </div>
  )
}

function BlockTimeline({ blocks }: { blocks: WorldSimPlanBlock[] }) {
  const ordered = [...blocks].sort((a, b) => a.seq - b.seq)
  return (
    <div data-testid="world-sim-timeline" className="flex flex-col gap-1.5">
      {ordered.map((block) => (
        <div
          key={block.seq}
          data-testid={`world-sim-block-${block.seq}`}
          className="flex items-center gap-2 rounded-md border border-border p-2"
        >
          <span className="w-[86px] shrink-0 font-mono text-[10px] tabular-nums text-fg-tertiary">
            {padMinutes(block.start_minutes)}-{padMinutes(block.end_minutes)}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs">{block.activity}</span>
          <span className="shrink-0 font-mono text-[10px] text-fg-tertiary">
            {block.location_id}
          </span>
          <Badge
            variant="outline"
            data-testid={`world-sim-block-status-${block.seq}`}
            className={cn(
              "shrink-0 font-mono",
              BLOCK_STATUS_TONE[block.status] ?? NEUTRAL_BADGE_CLASS,
            )}
          >
            {block.status}
          </Badge>
        </div>
      ))}
    </div>
  )
}

function SituationCard({ situation }: { situation: WorldSimSituation }) {
  const quote =
    typeof situation.evidence?.quote === "string" ? (situation.evidence.quote as string) : null
  return (
    <li
      data-testid={`world-sim-situation-${situation.dimension}`}
      className="rounded-md border border-border p-2.5"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs">{situation.dimension}</span>
        <div className="flex items-center gap-1">
          <Badge variant="outline" className={NEUTRAL_BADGE_CLASS}>
            {situation.intensity}/5
          </Badge>
          <Badge
            variant="outline"
            className={enumBadgeClass("status", situation.status)}
          >
            {situation.status}
          </Badge>
        </div>
      </div>
      <p className="mt-1.5 break-words text-xs leading-relaxed">{situation.summary}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[10px] text-fg-tertiary">
        <span>{situation.source}</span>
        {situation.valid_until ? <span>有效至 {situation.valid_until}</span> : null}
      </div>
      {quote ? (
        <p className="mt-1.5 border-l-2 border-border pl-2 font-mono text-[10px] italic text-muted-foreground">
          {quote}
        </p>
      ) : null}
    </li>
  )
}

function WorldSimPanelInner({ userId }: { userId: string }) {
  const simulation = useWorldSimulation(userId)
  const plan = useWorldPlan(userId)
  const situations = useWorldSituations(userId)
  const tick = useWorldSimTick(userId)

  const enabled = simulation.data?.enabled ?? false
  const debugTickOn = simulation.data?.flags?.v23_debug_tick_enabled ?? false

  if (simulation.isPending) {
    return (
      <div
        data-testid="world-sim-skeleton"
        className="h-32 animate-pulse rounded-md border border-border bg-muted/40"
      />
    )
  }

  if (simulation.isError || simulation.data === undefined) {
    return (
      <div
        data-testid="world-sim-error"
        className="flex flex-col items-start gap-2 rounded-md border border-status-error/50 p-3"
      >
        <p className="text-xs text-status-error">世界模拟数据加载失败</p>
        <p className="font-mono text-[10px] text-fg-tertiary">{String(simulation.error)}</p>
        <Button size="sm" variant="outline" onClick={() => simulation.refetch()}>
          重试
        </Button>
      </div>
    )
  }

  if (!enabled) {
    return (
      <p data-testid="world-sim-disabled" className="font-mono text-xs text-fg-tertiary">
        世界模拟未启用（v23_world_simulation_enabled=false）
      </p>
    )
  }

  const timeCtx = simulation.data.timeContext
  const brief = simulation.data.brief

  return (
    <div data-testid="world-sim-panel" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10px] text-fg-tertiary">user: {userId}</span>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 px-2 font-mono text-[10px]"
            data-testid="world-sim-refresh"
            onClick={() => {
              void simulation.refetch()
              void plan.refetch()
              void situations.refetch()
            }}
          >
            刷新
          </Button>
          {debugTickOn ? (
            <Button
              size="sm"
              variant="outline"
              className="h-6 px-2 font-mono text-[10px]"
              data-testid="world-sim-tick"
              disabled={tick.isPending}
              onClick={() => tick.mutate()}
            >
              {tick.isPending ? "推进中…" : "手动 tick"}
            </Button>
          ) : null}
        </div>
      </div>

      {/* ① 时间与天气 + WorldBrief 全文 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="font-mono text-xs">时间与简报</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <KeyValueRow label="now">
            <span className="font-mono">
              {timeCtx && typeof timeCtx.now === "string" ? timeCtx.now : "—"}
            </span>
          </KeyValueRow>
          <KeyValueRow label="part">
            <span className="font-mono">
              {timeCtx && typeof timeCtx.part_of_day === "string" ? timeCtx.part_of_day : "—"}
            </span>
          </KeyValueRow>
          <KeyValueRow label="mode">
            <span className="font-mono">
              {timeCtx && typeof timeCtx.time_mode === "string" ? timeCtx.time_mode : "—"}
            </span>
          </KeyValueRow>
          {brief?.text ? (
            <p
              data-testid="world-sim-brief"
              className="break-words rounded-md border border-border bg-muted/30 p-2 text-xs leading-relaxed"
            >
              {brief.text}
            </p>
          ) : (
            <p className="font-mono text-[10px] text-fg-tertiary">暂无世界简报</p>
          )}
        </CardContent>
      </Card>

      {/* ② 当日计划时间轴 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="font-mono text-xs">
            当日计划{plan.data?.date ? ` · ${plan.data.date}` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {plan.data === undefined || plan.data.blocks.length === 0 ? (
            <p data-testid="world-sim-plan-empty" className="font-mono text-xs text-fg-tertiary">
              当日暂无计划
            </p>
          ) : (
            <BlockTimeline blocks={plan.data.blocks} />
          )}
        </CardContent>
      </Card>

      {/* ③ 活跃处境 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="font-mono text-xs">活跃处境</CardTitle>
        </CardHeader>
        <CardContent>
          {situations.data === undefined || situations.data.situations.length === 0 ? (
            <p
              data-testid="world-sim-situations-empty"
              className="font-mono text-xs text-fg-tertiary"
            >
              暂无活跃处境
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {situations.data.situations.map((situation) => (
                <SituationCard
                  key={`${situation.dimension}-${situation.detected_at ?? ""}`}
                  situation={situation}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* ④ 近期模拟事件 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="font-mono text-xs">近期模拟事件</CardTitle>
        </CardHeader>
        <CardContent>
          {simulation.data.recentEvents.length === 0 ? (
            <p
              data-testid="world-sim-events-empty"
              className="font-mono text-xs text-fg-tertiary"
            >
              暂无模拟事件
            </p>
          ) : (
            <ul data-testid="world-sim-events" className="flex flex-col gap-1.5">
              {simulation.data.recentEvents.map((event) => (
                <li
                  key={event.id}
                  className="flex items-center gap-2 rounded-md border border-border p-2"
                >
                  <Badge variant="outline" className={NEUTRAL_BADGE_CLASS}>
                    {event.type}
                  </Badge>
                  <span className="min-w-0 flex-1 truncate text-xs">{event.title}</span>
                  <span className="shrink-0 font-mono text-[10px] text-fg-tertiary">
                    {event.importance}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* ⑤ tick 结果（有则展示） */}
      {tick.data?.result ? (
        <Card data-testid="world-sim-tick-result">
          <CardHeader className="pb-1">
            <CardTitle className="font-mono text-xs">上次 tick 结果</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1">
            <KeyValueRow label="advanced">
              <span className="font-mono tabular-nums">
                {String(tick.data.result.advanced_minutes ?? "—")} min
              </span>
            </KeyValueRow>
            <KeyValueRow label="markers">
              <span className="font-mono">
                {Array.isArray(tick.data.result.markers)
                  ? (tick.data.result.markers as string[]).join(", ") || "—"
                  : "—"}
              </span>
            </KeyValueRow>
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function WorldSimPanel({ userId }: { userId?: string }) {
  const resolved = userId ?? "default-user"
  return <WorldSimPanelInner key={resolved} userId={resolved} />
}

export { WorldSimPanel }
