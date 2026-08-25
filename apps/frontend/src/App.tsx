import { TokenDemoPage } from "@/features/token-demo/token-demo-page"
import { Workbench } from "@/components/shell/workbench"

const showTokenDemo = import.meta.env.DEV && window.location.hash === "#demo"

function App() {
  return showTokenDemo ? <TokenDemoPage /> : <Workbench />
}

export default App
