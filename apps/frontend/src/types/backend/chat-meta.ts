import type {
  ActionStatusValue,
  BehaviorValue,
  EmotionValue,
  EventValue,
  IntentValue,
  ModeValue,
  SceneIntentValue,
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

export interface SceneIntentResultDto {
  intent: SceneIntentValue
  confidence: number
  reason: string
}

export interface PendingActionDto {
  action: string
  status: ActionStatusValue
  created_at_turn: number
}

export interface SceneStateDto {
  session_id: string
  turn_id: number
  location: string | null
  current_activity: string | null
  current_action: string | null
  pending_action: PendingActionDto | null
  scene_mood: string | null
}
