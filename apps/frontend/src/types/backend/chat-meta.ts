import type {
  BehaviorValue,
  EmotionValue,
  EventValue,
  IntentValue,
  ModeValue,
} from '../domain/enums'

export interface RoleModeDto {
  mode: ModeValue
  intent: IntentValue
  confidence: number
  reason: string
}

export interface UserEmotionDto {
  emotion: EmotionValue
  event: EventValue
}

export interface BehaviorDecisionDto {
  behavior: BehaviorValue
  reason: string
}

export interface TurnAnalysisDto {
  user_emotion: UserEmotionDto
  behavior: BehaviorDecisionDto
}
