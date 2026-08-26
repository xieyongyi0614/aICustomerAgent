import { AppProviders } from "@/app/providers"
import { TokenDemoPage } from "@/features/token-demo/token-demo-page"
import { Workbench } from "@/components/shell/workbench"

const showTokenDemo = import.meta.env.DEV && window.location.hash === "#demo"

function App() {
  return (
    <AppProviders>{showTokenDemo ? <TokenDemoPage /> : <Workbench />}</AppProviders>
  )
}

export default App
