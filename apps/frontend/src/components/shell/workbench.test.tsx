// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it } from "vitest"

import { Workbench } from "./workbench"

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  cleanup()
})

describe("Workbench layout", () => {
  it("renders topbar slot, chat pane and inline debug pane by default", () => {
    render(<Workbench />)
    expect(screen.getByTestId("topbar-slot")).toBeTruthy()
    expect(screen.getByTestId("chat-pane")).toBeTruthy()
    expect(screen.getByTestId("debug-pane-inline")).toBeTruthy()
    expect(screen.getByTestId("debug-collapse")).toBeTruthy()
    expect(screen.getByTestId("mobile-banner")).toBeTruthy()
    expect(screen.getByTestId("debug-drawer-trigger")).toBeTruthy()
  })

  it("exposes five placeholder tabs with phase-2 copy", async () => {
    const user = userEvent.setup()
    render(<Workbench />)
    for (const label of ["Overview", "State", "Memory", "Trace", "Raw"]) {
      expect(screen.getByRole("tab", { name: label })).toBeTruthy()
    }
    await user.click(screen.getByRole("tab", { name: "State" }))
    expect(screen.getByText(/\[State\] Phase 2 提供/)).toBeTruthy()
  })

  it("collapses the debug pane and persists the preference", async () => {
    const user = userEvent.setup()
    const { unmount } = render(<Workbench />)
    await user.click(screen.getByTestId("debug-collapse"))
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()
    expect(screen.getByTestId("debug-restore")).toBeTruthy()
    expect(window.localStorage.getItem("asuna-debug.debugPaneCollapsed")).toBe("true")

    unmount()
    render(<Workbench />)
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()
    expect(screen.getByTestId("debug-restore")).toBeTruthy()
  })

  it("restores the inline pane from collapsed state", async () => {
    window.localStorage.setItem("asuna-debug.debugPaneCollapsed", "true")
    const user = userEvent.setup()
    render(<Workbench />)
    expect(screen.queryByTestId("debug-pane-inline")).toBeNull()
    await user.click(screen.getByTestId("debug-restore"))
    expect(screen.getByTestId("debug-pane-inline")).toBeTruthy()
    expect(window.localStorage.getItem("asuna-debug.debugPaneCollapsed")).toBe("false")
  })
})
