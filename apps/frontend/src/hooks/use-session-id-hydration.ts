import { useEffect } from "react"

import { useChatStore } from "@/stores/chat-store"
import { resolveInitialSessionId } from "@/lib/session-id-storage"

export function useSessionIdHydration(): void {
  useEffect(() => {
    void resolveInitialSessionId().then((id) => {
      const store = useChatStore.getState()
      store.setSessionId(id)
      void store.loadMessages(id)
    })
  }, [])
}
