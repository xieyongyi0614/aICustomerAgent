import { MockChatStreamTransport } from "@/mocks/mock-chat-stream"

import { readStoredApiMode, resolveApiMode } from "./api-mode"
import { FetchChatStreamTransport } from "./chat-stream"
import type { ChatStreamTransport } from "./transport"

function createChatTransport(): ChatStreamTransport {
  const mode = resolveApiMode(import.meta.env.VITE_API_MODE, readStoredApiMode())
  return mode === "mock"
    ? new MockChatStreamTransport()
    : new FetchChatStreamTransport()
}

export const chatTransport: ChatStreamTransport = createChatTransport()
