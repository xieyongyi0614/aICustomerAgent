import { createChatStore } from "./chat-store-factory"
import { chatTransport } from "@/api"

export const useChatStore = createChatStore(chatTransport)
