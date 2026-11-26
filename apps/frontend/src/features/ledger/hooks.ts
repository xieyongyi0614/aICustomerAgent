import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getLedgerBudgets,
  getLedgerEntries,
  getLedgerSummary,
  reverseLedgerEntry,
} from "./api"

export function useLedgerSummary(period = "month") {
  return useQuery({
    queryKey: ["ledger-summary", period],
    queryFn: () => getLedgerSummary(period),
  })
}

export function useLedgerEntries(params: { limit?: number; offset?: number; direction?: string }) {
  return useQuery({
    queryKey: ["ledger-entries", params],
    queryFn: () => getLedgerEntries(params),
  })
}

export function useLedgerBudgets() {
  return useQuery({
    queryKey: ["ledger-budgets"],
    queryFn: getLedgerBudgets,
  })
}

export function useReverseEntry() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, reason }: { entryId: string; reason: string }) =>
      reverseLedgerEntry(entryId, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ledger-summary"] })
      void queryClient.invalidateQueries({ queryKey: ["ledger-entries"] })
      void queryClient.invalidateQueries({ queryKey: ["ledger-budgets"] })
    },
  })
}
