// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { LedgerView } from "./LedgerView"
import * as api from "./api"

const summary = {
  period: { since: "2026-09-01", until: "2026-10-01", label: "month" },
  expense_minor: 2500,
  expense_text: "25.00",
  income_minor: 0,
  income_text: "0.00",
  net_minor: -2500,
  net_text: "-25.00",
  transfer_minor: 0,
  by_category: [{ category_id: null, net_minor: -2500, expense_minor: 2500, income_minor: 0 }],
  entry_count: 2,
  reversal_count: 0,
  compared_to_previous: null,
}

const entries = {
  items: [
    {
      id: "e1",
      account_id: "a1",
      category_id: null,
      amount_minor: 2500,
      amount_text: "25.00",
      currency: "CNY",
      direction: "expense",
      occurred_at: "2026-09-22T12:00:00",
      merchant: null,
      note: null,
      source: "manual",
      source_ref: null,
      idempotency_key: "k1",
      reversal_of: null,
    },
  ],
  total: 11,
  limit: 10,
  offset: 0,
}

const budgets = [
  {
    goal_id: "g1",
    scope: "total",
    category_id: null,
    period: "month",
    limit_minor: 150000,
    limit_text: "1500.00",
    currency: "CNY",
    consumed_minor: 2500,
    consumed_text: "25.00",
    remaining_minor: 147500,
    breached: false,
    reason: "ok",
  },
]

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  }
}

beforeEach(() => {
  vi.spyOn(api, "getLedgerSummary").mockResolvedValue(summary)
  vi.spyOn(api, "getLedgerEntries").mockResolvedValue(entries)
  vi.spyOn(api, "getLedgerBudgets").mockResolvedValue(budgets)
  vi.spyOn(api, "reverseLedgerEntry").mockResolvedValue({})
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe("LedgerView", () => {
  it("renders totals from text fields without local conversion", async () => {
    render(<LedgerView />, { wrapper: makeWrapper() })
    await waitFor(() => {
      expect(screen.getByTestId("ledger-expense-text").textContent).toBe("25.00")
    })
  })

  it("includes unclassified bucket", async () => {
    render(<LedgerView />, { wrapper: makeWrapper() })
    await waitFor(() => {
      expect(screen.getAllByText("未归类").length).toBeGreaterThan(0)
    })
  })

  it("shows pagination total", async () => {
    render(<LedgerView />, { wrapper: makeWrapper() })
    await waitFor(() => {
      expect(screen.getByTestId("ledger-total").textContent).toContain("11")
    })
  })

  it("blocks reverse without reason and shows confirmation", async () => {
    const user = userEvent.setup()
    render(<LedgerView />, { wrapper: makeWrapper() })
    await waitFor(() => screen.getByTestId("ledger-reverse-button"))
    await user.click(screen.getByTestId("ledger-reverse-button"))
    expect(screen.getByTestId("ledger-reverse-confirm")).toBeTruthy()
    expect((screen.getByTestId("ledger-reverse-submit") as HTMLButtonElement).disabled).toBe(true)
  })

  it("renders empty state", async () => {
    vi.spyOn(api, "getLedgerSummary").mockResolvedValue({
      ...summary,
      entry_count: 0,
      by_category: [],
    })
    render(<LedgerView />, { wrapper: makeWrapper() })
    await waitFor(() => {
      expect(screen.getByTestId("ledger-empty")).toBeTruthy()
    })
  })
})
