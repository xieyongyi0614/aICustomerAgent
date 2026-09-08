import { Component, type ErrorInfo, type ReactNode } from "react"

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Unhandled render error", error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.error !== null) {
      return (
        <div
          role="alert"
          className="flex h-screen flex-col items-center justify-center gap-3 bg-background p-8 text-center text-foreground"
        >
          <p className="font-mono text-sm text-status-error">
            页面渲染出错：{this.state.error.message}
          </p>
          <button
            type="button"
            className="rounded border border-border px-3 py-1.5 font-mono text-xs hover:bg-muted"
            onClick={() => {
              this.setState({ error: null })
              window.location.reload()
            }}
          >
            重新加载
          </button>
        </div>
      )
    }
    return this.props.children
  }
}