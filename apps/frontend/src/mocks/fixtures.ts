export function hoursAgoIso(hours: number): string {
  return new Date(Date.now() - hours * 3600 * 1000).toISOString()
}

export const EMPTY_USER = {
  state: {
    character_state: {
      mood: "calm",
      energy: 0.9,
      current_topic: "",
      inner_state: "平静，期待和用户聊天",
      updated_at: null as string | null,
    },
    relationship_state: {
      intimacy: 0.3,
      trust: 0.35,
      familiarity: 0.3,
      stage: "friend",
      updated_at: null as string | null,
    },
    emotion_history: [] as Array<{
      user_emotion: string
      event: string
      behavior: string
      mood_before: string
      mood_after: string
      energy_after: number
      stage_after: string
      created_at: string
    }>,
  },
  memories: {
    user_id: "empty-user",
    memories: [] as Array<{
      id: string
      user_id: string
      memory: string
      memory_type: string
      importance: number
      created_at: string
      updated_at: string
    }>,
  },
}

export const RICH_USER = {
  state: {
    character_state: {
      mood: "worried",
      energy: 0.42,
      current_topic: "用户的 Debug Console 项目",
      inner_state: "担心用户连续熬夜赶工",
      updated_at: hoursAgoIso(2),
    },
    relationship_state: {
      intimacy: 0.56,
      trust: 0.58,
      familiarity: 0.51,
      stage: "close_friend",
      updated_at: hoursAgoIso(2),
    },
    emotion_history: [
      {
        user_emotion: "sad",
        event: "setback",
        behavior: "comfort",
        mood_before: "calm",
        mood_after: "worried",
        energy_after: 0.42,
        stage_after: "close_friend",
        created_at: hoursAgoIso(5),
      },
      {
        user_emotion: "excited",
        event: "achievement",
        behavior: "celebrate",
        mood_before: "worried",
        mood_after: "happy",
        energy_after: 0.55,
        stage_after: "close_friend",
        created_at: hoursAgoIso(20),
      },
    ],
  },
  memories: {
    user_id: "rich-user",
    memories: [
      {
        id: "m-1",
        user_id: "rich-user",
        memory: "用户正在开发 AI Character Agent 项目",
        memory_type: "goal",
        importance: 0.9,
        created_at: "2026-08-20T10:00:00",
        updated_at: "2026-08-20T10:00:00",
      },
      {
        id: "m-2",
        user_id: "rich-user",
        memory: "用户喜欢日本料理，尤其是寿司",
        memory_type: "preference",
        importance: 0.7,
        created_at: "2026-08-18T12:00:00",
        updated_at: "2026-08-18T12:00:00",
        confidence: 0.95,
        source: "user_stated",
        status: "active",
      },
      {
        id: "m-3",
        user_id: "rich-user",
        memory: "用户喜欢速食便当",
        memory_type: "preference",
        importance: 0.6,
        created_at: "2026-08-10T09:00:00",
        updated_at: "2026-08-18T12:00:00",
        confidence: 0.85,
        source: "user_stated",
        status: "superseded",
        superseded_by: "m-2",
      },
    ],
  },
}

export const NEAR_UPGRADE_USER = {
  state: {
    character_state: {
      mood: "excited",
      energy: 0.68,
      current_topic: "用户的上线冲刺",
      inner_state: "期待用户的好消息",
      updated_at: null as string | null,
    },
    relationship_state: {
      intimacy: 0.53,
      trust: 0.54,
      familiarity: 0.5,
      stage: "friend",
      updated_at: null as string | null,
    },
    emotion_history: [
      {
        user_emotion: "excited",
        event: "achievement",
        behavior: "celebrate",
        mood_before: "calm",
        mood_after: "excited",
        energy_after: 0.68,
        stage_after: "friend",
        created_at: "2026-08-26T08:00:00",
      },
    ],
  },
  memories: {
    user_id: "near-upgrade-user",
    memories: [
      {
        id: "n-1",
        user_id: "near-upgrade-user",
        memory: "用户正在冲刺项目上线",
        memory_type: "goal",
        importance: 0.62,
        created_at: "2026-08-26T07:00:00",
        updated_at: "2026-08-26T07:00:00",
      },
    ],
  },
}

export function makeTraceFixture(status: "pending" | "complete") {
  return {
    turn_id: "t-rich-1",
    status,
    role_mode:
      status === "complete"
        ? { mode: "immersive", intent: "emotional", confidence: 0.88, reason: "情绪倾诉" }
        : null,
    analysis:
      status === "complete"
        ? {
            user_emotion: { emotion: "sad", event: "setback" },
            behavior: { behavior: "comfort", reason: "先接住情绪" },
          }
        : null,
    total_ms: status === "complete" ? 5806.4 : 0,
    steps:
      status === "complete"
        ? [
            { name: "role_router", status: "ok", durationMs: 120.1, firstTokenMs: null, error: null },
            { name: "turn_analyzer", status: "degraded", durationMs: 280.0, firstTokenMs: null, error: null },
            { name: "memory_retrieval", status: "ok", durationMs: 35.0, firstTokenMs: null, error: null },
            { name: "context_builder", status: "ok", durationMs: 8.2, firstTokenMs: null, error: null },
            { name: "prompt_builder", status: "ok", durationMs: 10.0, firstTokenMs: null, error: null },
            { name: "llm", status: "ok", durationMs: 4820.0, firstTokenMs: 380.0, error: null },
            { name: "state_update", status: "ok", durationMs: 300.0, firstTokenMs: null, error: null },
            { name: "memory_extractor", status: "ok", durationMs: 300.1, firstTokenMs: null, error: null },
          ]
        : [],
  }
}

export function messagesFixture(conversationId: string) {
  if (conversationId === "ghost-session") return null
  return {
    conversation_id: conversationId,
    messages: [
      { id: 11, role: "human" as const, content: "第一句", created_at: "2026-08-26T09:00:00" },
      { id: 12, role: "ai" as const, content: "第一答", created_at: "2026-08-26T09:00:05" },
      { id: 13, role: "human" as const, content: "第二句", created_at: "2026-08-26T09:01:00" },
    ],
  }
}

export const LLM_PROFILES_FIXTURE = {
  default: "minimax-m3",
  profiles: [
    { id: "longcat", label: "LongCat (mock)", model: "LongCat-2.0", default: false },
    {
      id: "minimax-m3",
      label: "MiniMax M3 (mock)",
      model: "MiniMaxAI/MiniMax-M3",
      default: true,
    },
  ],
}
