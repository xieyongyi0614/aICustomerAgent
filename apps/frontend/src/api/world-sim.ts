import { requestJson } from "@/api/http"

export interface WorldBriefParts {
  text: string
  time_line: string | null
  place_line: string | null
  situations_line: string | null
  events_line: string | null
}

export interface WorldSimPlanBlock {
  seq: number
  part_of_day: string
  start_minutes: number
  end_minutes: number
  activity: string
  location_id: string
  variability_source: string | null
  status: string
  note: string | null
}

export interface WorldSimSituation {
  dimension: string
  summary: string
  intensity: number
  status: string
  source: string
  detected_at: string | null
  valid_until: string | null
  evidence: Record<string, unknown>
}

export interface WorldSimEvent {
  id: string
  type: string
  title: string
  importance: string
  status: string
  idempotency_key: string | null
  created_at: string | null
}

export interface WorldSimulationView {
  enabled: boolean
  timeContext: Record<string, unknown> | null
  brief: { text: string; parts: WorldBriefParts | null } | null
  currentBlock: WorldSimPlanBlock | null
  activeSituations: WorldSimSituation[]
  recentEvents: WorldSimEvent[]
  flags: Record<string, boolean>
}

export interface WorldPlanView {
  enabled: boolean
  date: string | null
  blocks: WorldSimPlanBlock[]
}

export interface WorldSituationsView {
  enabled: boolean
  situations: WorldSimSituation[]
}

export interface WorldSimTickView {
  enabled: boolean
  result: Record<string, unknown> | null
}

interface WorldSimulationDto {
  enabled: boolean
  time_context: Record<string, unknown> | null
  brief: { text: string; parts: WorldBriefParts | null } | null
  current_block: WorldSimPlanBlock | null
  active_situations: WorldSimSituation[]
  recent_events: WorldSimEvent[]
  flags: Record<string, boolean>
}

interface WorldPlanDto {
  enabled: boolean
  date: string | null
  blocks: WorldSimPlanBlock[]
}

interface WorldSituationsDto {
  enabled: boolean
  situations: WorldSimSituation[]
}

interface WorldSimTickDto {
  enabled: boolean
  result: Record<string, unknown> | null
}

export async function getWorldSimulation(userId: string): Promise<WorldSimulationView> {
  const dto = await requestJson<WorldSimulationDto>(
    `/api/v1/debug/world/simulation?user_id=${encodeURIComponent(userId)}`,
  )
  return {
    enabled: dto.enabled,
    timeContext: dto.time_context ?? null,
    brief: dto.brief ?? null,
    currentBlock: dto.current_block ?? null,
    activeSituations: dto.active_situations ?? [],
    recentEvents: dto.recent_events ?? [],
    flags: dto.flags ?? {},
  }
}

export async function getWorldPlan(userId: string, date?: string): Promise<WorldPlanView> {
  const params = new URLSearchParams({ user_id: userId })
  if (date) params.set("date", date)
  const dto = await requestJson<WorldPlanDto>(
    `/api/v1/debug/world/plan?${params.toString()}`,
  )
  return { enabled: dto.enabled, date: dto.date ?? null, blocks: dto.blocks ?? [] }
}

export async function getWorldSituations(
  userId: string,
  includeExpired = false,
): Promise<WorldSituationsView> {
  const params = new URLSearchParams({
    user_id: userId,
    include_expired: String(includeExpired),
  })
  const dto = await requestJson<WorldSituationsDto>(
    `/api/v1/debug/world/situations?${params.toString()}`,
  )
  return { enabled: dto.enabled, situations: dto.situations ?? [] }
}

export async function postWorldSimTick(userId: string): Promise<WorldSimTickView> {
  const dto = await requestJson<WorldSimTickDto>(
    "/api/v1/debug/world/simulation/tick",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    },
  )
  return { enabled: dto.enabled, result: dto.result ?? null }
}
