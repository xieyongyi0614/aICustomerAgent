import { lazy, Suspense } from "react"

import { AppProviders } from "@/app/providers"
import { ErrorBoundary } from "@/components/error-boundary"
import { Workbench } from "@/components/shell/workbench"
import { useSessionIdHydration } from "@/hooks/use-session-id-hydration"

const TokenDemoPage = lazy(() =>
  import("@/features/token-demo/token-demo-page").then((m) => ({
    default: m.TokenDemoPage,
  })),
)

const showTokenDemo = import.meta.env.DEV && window.location.hash === "#demo"

function App() {
  useSessionIdHydration()

  return (
    <ErrorBoundary>
      <AppProviders>
        {showTokenDemo ? (
          <Suspense fallback={null}>
            <TokenDemoPage />
          </Suspense>
        ) : (
          <Workbench />
        )}
      </AppProviders>
    </ErrorBoundary>
  )
}

export default App
