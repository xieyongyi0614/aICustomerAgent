import type {
  ActionStatusValue,
  BehaviorValue,
  EmotionValue,
  EventValue,
  IntentValue,
  ModeValue,
  SceneIntentValue,
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

export interface SceneIntentResult {
  intent: SceneIntentValue
  confidence: number
  reason: string
}

export interface PendingAction {
  action: string
  status: ActionStatusValue
  createdAtTurn: number
}

export interface SceneState {
  sessionId: string
  turnId: number
  location: string | null
  currentActivity: string | null
  currentAction: string | null
  pendingAction: PendingAction | null
  sceneMood: string | null
}
