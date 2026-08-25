import type {
  BehaviorValue,
  EmotionValue,
  EventValue,
  IntentValue,
  ModeValue,
} from './enums'

export interface RoleMode {
  mode: ModeValue
  intent: IntentValue
  confidence: number
  reason: string
}

export interface UserEmotion {
  emotion: EmotionValue
  event: EventValue
}

export interface BehaviorDecision {
  behavior: BehaviorValue
  reason: string
}

export interface TurnAnalysis {
  userEmotion: UserEmotion
  behavior: BehaviorDecision
}
