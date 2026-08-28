import type {
  ActionStatusValue,
  BehaviorValue,
  EmotionValue,
  ModeValue,
  StageValue,
} from "@/types/domain/enums"

export type EnumKind =
  | 'mode'
  | 'emotion'
  | 'behavior'
  | 'stage'
  | 'status'

export const NEUTRAL_BADGE_CLASS = 'bg-neutral-500/15 text-neutral-300 border-neutral-500/40'
export const DEGRADED_BADGE_CLASS = 'bg-amber-500/15 text-amber-300 border-amber-500/50'

const MODE_BADGES: Record<ModeValue, string> = {
  professional: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
  default: 'bg-slate-400/15 text-slate-300 border-slate-400/40',
  immersive: 'bg-violet-500/15 text-violet-300 border-violet-500/40',
}

const EMOTION_BADGES: Record<EmotionValue, string> = {
  happy: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/40',
  calm: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  sad: 'bg-blue-500/15 text-blue-300 border-blue-500/40',
  anxious: 'bg-orange-500/15 text-orange-300 border-orange-500/40',
  angry: 'bg-red-500/15 text-red-300 border-red-500/40',
  tired: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/40',
  excited: 'bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40',
  neutral: NEUTRAL_BADGE_CLASS,
}

const BEHAVIOR_BADGES: Record<BehaviorValue, string> = {
  normal_reply: NEUTRAL_BADGE_CLASS,
  comfort: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  encourage: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  celebrate: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  show_concern: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
  recall_memory: 'bg-violet-500/15 text-violet-300 border-violet-500/40',
  ask_followup: 'bg-teal-500/15 text-teal-300 border-teal-500/40',
}

const STAGE_BADGES: Record<StageValue, string> = {
  stranger: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/40',
  friend: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
  close_friend: 'bg-violet-500/15 text-violet-300 border-violet-500/40',
  partner: 'bg-pink-500/15 text-pink-300 border-pink-500/40',
}

const ACTION_STATUS_BADGES: Record<ActionStatusValue, string> = {
  pending: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  completed: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  cancelled: 'bg-zinc-500/15 text-zinc-300 border-zinc-500/40',
  superseded: 'bg-slate-500/15 text-slate-300 border-slate-500/40',
}

const BADGE_TABLES: Record<EnumKind, Record<string, string>> = {
  mode: MODE_BADGES,
  emotion: EMOTION_BADGES,
  behavior: BEHAVIOR_BADGES,
  stage: STAGE_BADGES,
  status: ACTION_STATUS_BADGES,
}

export const MODE_VALUES = Object.keys(MODE_BADGES) as ModeValue[]
export const EMOTION_VALUES = Object.keys(EMOTION_BADGES) as EmotionValue[]
export const BEHAVIOR_VALUES = Object.keys(BEHAVIOR_BADGES) as BehaviorValue[]
export const STAGE_VALUES = Object.keys(STAGE_BADGES) as StageValue[]

export function enumBadgeClass(kind: EnumKind, value: string): string {
  return BADGE_TABLES[kind][value] ?? NEUTRAL_BADGE_CLASS
}
