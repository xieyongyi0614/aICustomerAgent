// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

const { copyText } = vi.hoisted(() => ({ copyText: vi.fn() }))

vi.mock("@/lib/copy-text", () => ({ copyText }))

const { JsonViewer } = await import("./json-viewer")

const SAMPLE = {
  mode: "immersive",
  confidence: 0.88,
  nested: { deep: { deeper: "value" }, list: [1, 2] },
  empty: {},
}

afterEach(() => {
  cleanup()
  copyText.mockClear()
})

function toggles() {
  return document.querySelectorAll("[data-testid^='json-toggle-']")
}

describe("JsonViewer", () => {
  it("expands to default depth and hides deeper levels until toggled", () => {
    render(<JsonViewer data={SAMPLE} />)
    expect(screen.getByText('"immersive"')).toBeTruthy()
    expect(screen.getByTestId("json-toggle-$.nested")).toBeTruthy()
    expect(screen.queryByText("deeper:")).toBeNull()

    fireEvent.click(screen.getByTestId("json-toggle-$.nested.deep"))
    expect(screen.getByText("deeper:")).toBeTruthy()
    expect(screen.getByTestId("json-copy-$.nested.deep")).toBeTruthy()
    expect(screen.getByText('"value"')).toBeTruthy()

    fireEvent.click(screen.getByTestId("json-toggle-$.nested"))
    expect(screen.queryByText("deeper:")).toBeNull()
  })

  it("copies a subtree with stable serialization", () => {
    render(<JsonViewer data={SAMPLE} />)
    fireEvent.click(screen.getByTestId("json-copy-$"))
    const arg = copyText.mock.calls[0][0] as string
    const parsed = JSON.parse(arg)
    expect(parsed.mode).toBe("immersive")
    expect(arg.includes("\n")).toBe(true)
  })

  it("expand all / collapse all control every branch", () => {
    render(<JsonViewer data={SAMPLE} />)
    fireEvent.click(screen.getByTestId("json-expand-all"))
    expect(screen.getByText('"value"')).toBeTruthy()
    expect(toggles().length).toBeGreaterThanOrEqual(4)

    fireEvent.click(screen.getByTestId("json-collapse-all"))
    expect(screen.queryByText("deeper:")).toBeNull()
    expect(screen.getByText("{ mode, confidence, nested, … }")).toBeTruthy()
  })

  it("auto-collapses oversized objects with a notice", () => {
    const huge: Record<string, number> = {}
    for (let i = 0; i < 900; i += 1) huge[`k${i}`] = i
    render(<JsonViewer data={{ huge }} maxAutoNodes={200} />)
    expect(screen.getByTestId("json-oversized-note").textContent).toContain("已默认折叠")
    expect(screen.queryByText("k5:")).toBeNull()

    fireEvent.click(screen.getByTestId("json-expand-all"))
    expect(screen.getByText("k5:")).toBeTruthy()
  })

  it("renders scalars at the root and empty branches", () => {
    render(<JsonViewer data={"plain string"} />)
    expect(screen.getByText('"plain string"')).toBeTruthy()

    cleanup()
    render(<JsonViewer data={{ empty: {} }} />)
    fireEvent.click(screen.getByTestId("json-toggle-$.empty"))
    expect(screen.getByText("{}")).toBeTruthy()
  })
})
