import { useEffect } from "react"

import { useChatStore } from "@/stores/chat-store"
import { resolveInitialSessionId } from "@/lib/session-id-storage"

export function useSessionIdHydration(): void {
  useEffect(() => {
    void resolveInitialSessionId().then((id) => {
      useChatStore.getState().setSessionId(id)
    })
  }, [])
}
