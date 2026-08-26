import { http, HttpResponse } from "msw"

import { EMPTY_USER, makeTraceFixture, messagesFixture, RICH_USER } from "./fixtures"

function persona(requestUrl: URL) {
  const userId = requestUrl.searchParams.get("user_id") ?? "default-user"
  if (userId === "rich-user") return RICH_USER
  return EMPTY_USER
}

export const restHandlers = [
  http.get("*/api/v1/state", ({ request }) => {
    const body = persona(new URL(request.url)).state
    return HttpResponse.json(body)
  }),

  http.get("*/api/v1/memories", ({ request }) => {
    const body = persona(new URL(request.url)).memories
    return HttpResponse.json(body)
  }),

  http.get("*/api/v1/conversations/:conversationId/messages", ({ params }) => {
    const { conversationId } = params as { conversationId: string }
    const body = messagesFixture(conversationId)
    if (body === null) {
      return HttpResponse.json({ detail: "会话不存在" }, { status: 404 })
    }
    return HttpResponse.json(body)
  }),

  http.get("*/api/v1/debug/turns/:turnId/trace", ({ params, request }) => {
    const { turnId } = params as { turnId: string }
    if (turnId === "no-such-turn") {
      return HttpResponse.json({ detail: "turn trace 不存在或已被清理" }, { status: 404 })
    }
    const scenario = new URL(request.url).searchParams.get("scenario")
    if (scenario === "pending-forever" || turnId === "__pending__") {
      return HttpResponse.json(makeTraceFixture("pending"))
    }
    return HttpResponse.json(makeTraceFixture("complete"))
  }),
]
