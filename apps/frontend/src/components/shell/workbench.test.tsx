// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { Workbench } from "./workbench"

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  cleanup()
})

describe("Workbench layout", () => {
  it("renders topbar slot, chat pane and inline debug pane by default", () => {
    render(<Workbench />, { wrapper: makeWrapper() })
    expect(screen.getByTestId("topbar-slot")).toBeTruthy()
    expect(screen.getByTestId("chat-pane")).toBeTruthy()
    expect(screen.getByTestId("debug-pane-inline")).toBeTruthy()
    expect(screen.getByTestId("debug-collapse")).toBeTruthy()
    expect(screen.getByTestId("mobile-banner")).toBeTruthy()
    expect(screen.getByTestId("debug-drawer-trigger")).toBeTruthy()
  })

  it("exposes five tabs and switches into the live state panel", async () => {
    const user = userEvent.setup()
    render(<Workbench />, { wrapper: makeWrapper() })
    for (const label of ["Overview", "State", "Memory", "Trace", "Raw"]) {
      expect(screen.getByRole("tab", { name: label })).toBeTruthy()
    }
    await user.click(screen.getByRole("tab", { name: "State" }))
    expect(screen.getByRole("tab", { name: "State" }).getAttribute("aria-selected")).toBe(
      "true",
    )
  })

  it("collapses the debug pane and persists the preference", async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Workbench />, { wrapper: makeWrapper() })
    await user.click(screen.getByTestId("debug-collapse"))
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()
    expect(screen.getByTestId("debug-restore")).toBeTruthy()
    expect(window.localStorage.getItem("asuna-debug.debugPaneCollapsed")).toBe("true")

    unmount()
    render(<Workbench />, { wrapper: makeWrapper() })
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()
    expect(screen.getByTestId("debug-restore")).toBeTruthy()
  })

  it("restores the inline pane from collapsed state", async () => {
    window.localStorage.setItem("asuna-debug.debugPaneCollapsed", "true")
    const user = userEvent.setup()
    render(<Workbench />, { wrapper: makeWrapper() })
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()
    await user.click(screen.getByTestId("debug-restore"))
    expect(screen.getByTestId("debug-pane-inline")).toBeTruthy()
    expect(window.localStorage.getItem("asuna-debug.debugPaneCollapsed")).toBe("false")
  })
})
