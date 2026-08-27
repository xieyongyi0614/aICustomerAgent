import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState, type ReactNode } from "react"

import { ensureMockRest, disableMockRest } from "@/mocks/mock-rest-bootstrap"
import { getActiveApiMode } from "@/api/api-mode"

function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
      },
    },
  })
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(createQueryClient)

  if (getActiveApiMode() === "mock") {
    void ensureMockRest()
  } else {
    void disableMockRest()
  }

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}
