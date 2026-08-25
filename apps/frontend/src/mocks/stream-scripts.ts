import type { RoleMode, TurnAnalysis } from "@/types/domain/chat-meta"

export interface StreamScript {
  id: string
  keywords: readonly string[]
  roleMode: RoleMode
  analysis: TurnAnalysis
  lines: readonly string[]
  includeTurnMeta: boolean
  failure?: {
    afterLines: number
    message: string
    code?: string
  }
}

const DAILY_ROLE_MODE: RoleMode = {
  mode: "default",
  intent: "casual",
  confidence: 0.82,
  reason: "日常闲聊，默认语气即可",
}

const IMMERSIVE_COMFORT_ANALYSIS: TurnAnalysis = {
  userEmotion: { emotion: "sad", event: "setback" },
  behavior: { behavior: "comfort", reason: "用户情绪低落，先接住情绪" },
}

const COMFORT_ROLE_MODE: RoleMode = {
  mode: "immersive",
  intent: "emotional",
  confidence: 0.88,
  reason: "情绪倾诉，进入沉浸陪伴",
}

const CELEBRATE_ANALYSIS: TurnAnalysis = {
  userEmotion: { emotion: "excited", event: "achievement" },
  behavior: { behavior: "celebrate", reason: "用户达成成就，值得庆祝" },
}

const FALLBACK_ANALYSIS: TurnAnalysis = {
  userEmotion: { emotion: "neutral", event: "daily" },
  behavior: { behavior: "normal_reply", reason: "" },
}

const DEGRADED_ROLE_MODE: RoleMode = {
  mode: "default",
  intent: "casual",
  confidence: 0.2,
  reason: "",
}

export const STREAM_SCRIPTS: readonly StreamScript[] = [
  {
    id: "comfort",
    keywords: ["压力", "难过", "累", "烦", "加班"],
    roleMode: COMFORT_ROLE_MODE,
    analysis: IMMERSIVE_COMFORT_ANALYSIS,
    lines: [
      "辛苦了。",
      "连续赶工的话，谁都会撑不住的。",
      "先别想代码了，去喝口热水，深呼吸一下。",
      "等你缓过来，我们再一起看问题在哪，好吗？",
    ],
    includeTurnMeta: true,
  },
  {
    id: "celebrate",
    keywords: ["上线", "成功", "庆祝", "通过", "搞定"],
    roleMode: COMFORT_ROLE_MODE,
    analysis: CELEBRATE_ANALYSIS,
    lines: [
      "真的吗？！那也太棒了吧！",
      "就说你肯定没问题的！",
      "今晚必须庆祝一下，这可是大事！",
    ],
    includeTurnMeta: true,
  },
  {
    id: "legacy",
    keywords: ["旧契约"],
    roleMode: DEGRADED_ROLE_MODE,
    analysis: FALLBACK_ANALYSIS,
    lines: ["这是旧契约兼容流的回答。"],
    includeTurnMeta: false,
  },
  {
    id: "error",
    keywords: ["触发错误", "报错看看"],
    roleMode: DAILY_ROLE_MODE,
    analysis: FALLBACK_ANALYSIS,
    lines: ["前半段正常输出，", "然后流会中断……"],
    includeTurnMeta: true,
    failure: {
      afterLines: 2,
      message: "LLM 调用失败",
      code: "mock_upstream_error",
    },
  },
  {
    id: "daily",
    keywords: ["你好", "在吗", "今天", "天气"],
    roleMode: DAILY_ROLE_MODE,
    analysis: FALLBACK_ANALYSIS,
    lines: [
      "嗯，我在呢。",
      "今天过得怎么样？有什么想聊的吗？",
    ],
    includeTurnMeta: true,
  },
]

export function matchStreamScript(userContent: string): StreamScript {
  const normalized = userContent.trim()
  for (const script of STREAM_SCRIPTS) {
    if (script.keywords.some((keyword) => normalized.includes(keyword))) {
      return script
    }
  }
  return STREAM_SCRIPTS[STREAM_SCRIPTS.length - 1]
}
