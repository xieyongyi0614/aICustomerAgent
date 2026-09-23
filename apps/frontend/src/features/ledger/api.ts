import { requestJson } from "@/api/http"

export interface LedgerSummary {
  period: { since: string; until: string; label: string }
  expense_minor: number
  expense_text: string
  income_minor: number
  income_text: string
  net_minor: number
  net_text: string
  transfer_minor: number
  by_category: Array<{
    category_id: string | null
    net_minor: number
    expense_minor: number
    income_minor: number
  }>
  entry_count: number
  reversal_count: number
  compared_to_previous: {
    expense_delta: number
    income_delta: number
    expense_ratio: number | null
  } | null
}

export interface LedgerEntry {
  id: string
  account_id: string
  category_id: string | null
  amount_minor: number
  amount_text: string
  currency: string
  direction: string
  occurred_at: string
  merchant: string | null
  note: string | null
  source: string
  source_ref: string | null
  idempotency_key: string
  reversal_of: string | null
}

export interface LedgerEntryList {
  items: LedgerEntry[]
  total: number
  limit: number
  offset: number
}

export interface BudgetItem {
  goal_id: string
  scope: string
  category_id: string | null
  period: string
  limit_minor: number
  limit_text: string
  currency: string
  consumed_minor: number
  consumed_text: string
  remaining_minor: number
  breached: boolean
  reason: string
}

export function getLedgerSummary(period = "month") {
  return requestJson<LedgerSummary>(`/api/v1/ledger/summary?period=${period}`)
}

export function getLedgerEntries(params: {
  limit?: number
  offset?: number
  direction?: string
} = {}) {
  const query = new URLSearchParams()
  query.set("limit", String(params.limit ?? 20))
  query.set("offset", String(params.offset ?? 0))
  if (params.direction) query.set("direction", params.direction)
  return requestJson<LedgerEntryList>(`/api/v1/ledger/entries?${query}`)
}

export function getLedgerBudgets() {
  return requestJson<BudgetItem[]>(`/api/v1/ledger/budgets`)
}

export function reverseLedgerEntry(entryId: string, reason: string) {
  return requestJson(`/api/v1/ledger/entries/${entryId}/reverse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  })
}
