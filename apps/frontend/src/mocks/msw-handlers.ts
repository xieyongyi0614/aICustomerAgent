import { delay, http, HttpResponse } from "msw"

import {
  EMPTY_USER,
  LLM_PROFILES_FIXTURE,
  makeTraceFixture,
  messagesFixture,
  NEAR_UPGRADE_USER,
  RICH_USER,
} from "./fixtures"

function persona(requestUrl: URL) {
  const userId = requestUrl.searchParams.get("user_id") ?? "default-user"
  if (userId === "rich-user") return RICH_USER
  if (userId === "near-upgrade-user") return NEAR_UPGRADE_USER
  return EMPTY_USER
}

async function withOptionalDelay(requestUrl: URL): Promise<void> {
  const delayMs = Number(requestUrl.searchParams.get("__delay") ?? 0)
  if (delayMs > 0) await delay(delayMs)
}

function scenario(requestUrl: URL, name: string): boolean {
  return requestUrl.searchParams.get("__scenario") === name
}

export const restHandlers = [
  http.get("*/api/v1/state", async ({ request }) => {
    const url = new URL(request.url)
    if (scenario(url, "error500")) {
      return HttpResponse.json({ detail: "state boom" }, { status: 500 })
    }
    await withOptionalDelay(url)
    return HttpResponse.json(persona(url).state)
  }),

  http.get("*/api/v1/memories", async ({ request }) => {
    const url = new URL(request.url)
    if (scenario(url, "error500")) {
      return HttpResponse.json({ detail: "memories boom" }, { status: 500 })
    }
    await withOptionalDelay(url)
    return HttpResponse.json(persona(url).memories)
  }),

  http.get("*/api/v1/conversations/:conversationId/messages", ({ params }) => {
    const { conversationId } = params as { conversationId: string }
    const body = messagesFixture(conversationId)
    if (body === null) {
      return HttpResponse.json({ detail: "会话不存在" }, { status: 404 })
    }
    return HttpResponse.json(body)
  }),

  http.get("*/api/v1/debug/turns/:turnId/trace", ({ params }) => {
    const { turnId } = params as { turnId: string }
    if (turnId === "no-such-turn") {
      return HttpResponse.json({ detail: "turn trace 不存在或已被清理" }, { status: 404 })
    }
    if (turnId === "__pending__" || turnId === "__timeout__") {
      return HttpResponse.json(makeTraceFixture("pending"))
    }
    return HttpResponse.json(makeTraceFixture("complete"))
  }),

  http.get("*/api/v1/llm/profiles", () => HttpResponse.json(LLM_PROFILES_FIXTURE)),
]
