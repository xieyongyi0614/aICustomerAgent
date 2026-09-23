import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  useLedgerBudgets,
  useLedgerEntries,
  useLedgerSummary,
  useReverseEntry,
} from "./hooks"

function EmptyState({ text }: { text: string }) {
  return (
    <div data-testid="ledger-empty" className="p-6 text-center text-sm text-fg-tertiary">
      {text}
    </div>
  )
}

function LoadingState() {
  return (
    <div data-testid="ledger-loading" className="space-y-2 p-4">
      <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
      <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
      <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
    </div>
  )
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div data-testid="ledger-error" className="space-y-2 p-6 text-center">
      <p className="text-sm text-status-warn">加载失败</p>
      <Button size="sm" variant="outline" onClick={onRetry}>
        重试
      </Button>
    </div>
  )
}

export function LedgerView() {
  const [period, setPeriod] = useState("month")
  const [direction, setDirection] = useState<string | undefined>(undefined)
  const [offset, setOffset] = useState(0)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const [reason, setReason] = useState("")
  const summary = useLedgerSummary(period)
  const entries = useLedgerEntries({ limit: 10, offset, direction })
  const budgets = useLedgerBudgets()
  const reverse = useReverseEntry()

  if (summary.isLoading) return <LoadingState />
  if (summary.isError) return <ErrorState onRetry={() => void summary.refetch()} />

  const data = summary.data
  const entryList = entries.data
  const budgetList = budgets.data ?? []

  return (
    <div data-testid="ledger-view" className="flex h-full flex-col gap-3 overflow-y-auto p-3">
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs text-fg-tertiary">账本</span>
        {["month", "week"].map((item) => (
          <Button
            key={item}
            size="xs"
            variant={period === item ? "default" : "ghost"}
            data-testid={`ledger-period-${item}`}
            onClick={() => {
              setPeriod(item)
              setOffset(0)
            }}
          >
            {item === "month" ? "本月" : "本周"}
          </Button>
        ))}
      </div>

      {data && data.entry_count === 0 ? (
        <EmptyState text="本期还没有账目" />
      ) : (
        data && (
          <Card size="sm">
            <CardHeader>
              <CardTitle className="text-sm">本期合计</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-3 gap-2 font-mono text-sm">
              <div>
                <div className="text-fg-tertiary">支出</div>
                <div data-testid="ledger-expense-text">{data.expense_text}</div>
              </div>
              <div>
                <div className="text-fg-tertiary">收入</div>
                <div data-testid="ledger-income-text">{data.income_text}</div>
              </div>
              <div>
                <div className="text-fg-tertiary">净额</div>
                <div data-testid="ledger-net-text">{data.net_text}</div>
              </div>
              <div className="col-span-3 text-xs text-fg-tertiary">
                条目 {data.entry_count} · 冲正 {data.reversal_count}
              </div>
            </CardContent>
          </Card>
        )
      )}

      {data && data.by_category.length > 0 && (
        <Card size="sm">
          <CardHeader>
            <CardTitle className="text-sm">类目分布</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.by_category.slice(0, 5).map((item, index) => {
              const share =
                data.expense_minor > 0
                  ? Math.min(100, Math.round((Math.abs(item.net_minor) / data.expense_minor) * 100))
                  : 0
              return (
                <div key={`${item.category_id ?? "unclassified"}-${index}`}>
                  <div className="flex justify-between text-xs">
                    <span>{item.category_id ?? "未归类"}</span>
                    <span className="font-mono">{share}%</span>
                  </div>
                  <div className="h-1.5 rounded bg-muted">
                    <div
                      data-testid="ledger-category-bar"
                      className="h-1.5 rounded bg-primary"
                      style={{ width: `${share}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </CardContent>
        </Card>
      )}

      <Card size="sm">
        <CardHeader>
          <CardTitle className="text-sm">条目</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="flex gap-2">
            <Button size="xs" variant={direction === undefined ? "default" : "ghost"} onClick={() => setDirection(undefined)}>
              全部
            </Button>
            <Button size="xs" variant={direction === "expense" ? "default" : "ghost"} onClick={() => setDirection("expense")}>
              支出
            </Button>
            <Button size="xs" variant={direction === "income" ? "default" : "ghost"} onClick={() => setDirection("income")}>
              收入
            </Button>
          </div>
          {entries.isLoading && <LoadingState />}
          {entries.isError && <ErrorState onRetry={() => void entries.refetch()} />}
          {entryList && entryList.items.length === 0 && <EmptyState text="没有条目" />}
          {entryList?.items.map((item) => (
            <div
              key={item.id}
              data-testid="ledger-entry-row"
              className="flex items-center justify-between border-b border-border py-1 text-sm"
            >
              <div>
                <div className="font-mono" data-testid="ledger-entry-amount-text">
                  {item.amount_text}
                </div>
                <div className="text-xs text-fg-tertiary">
                  {item.direction} · {item.source}
                </div>
              </div>
              <Button
                size="xs"
                variant="ghost"
                data-testid="ledger-reverse-button"
                onClick={() => {
                  setConfirmId(item.id)
                  setReason("")
                }}
              >
                撤销
              </Button>
            </div>
          ))}
          {entryList && (
            <div className="flex items-center justify-between pt-2 text-xs">
              <span data-testid="ledger-total">共 {entryList.total}</span>
              <div className="flex gap-2">
                <Button size="xs" variant="outline" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))}>
                  上一页
                </Button>
                <Button size="xs" variant="outline" onClick={() => setOffset(offset + 10)}>
                  下一页
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card size="sm">
        <CardHeader>
          <CardTitle className="text-sm">预算</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {budgets.isLoading && <LoadingState />}
          {budgets.isError && <ErrorState onRetry={() => void budgets.refetch()} />}
          {budgets.isSuccess && budgetList.length === 0 && <EmptyState text="未设置预算" />}
          {budgetList.map((item) => (
            <div key={item.goal_id} data-testid="ledger-budget-row" className="text-sm">
              <div className="flex justify-between">
                <span>{item.scope === "total" ? "总额" : item.category_id}</span>
                <span className="font-mono">
                  {item.consumed_text} / {item.limit_text}
                </span>
              </div>
              <div className="h-1.5 rounded bg-muted">
                <div
                  data-testid="ledger-budget-bar"
                  className="h-1.5 rounded bg-primary"
                  style={{
                    width: `${Math.min(100, Math.round((item.consumed_minor / Math.max(item.limit_minor, 1)) * 100))}%`,
                  }}
                />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {confirmId && (
        <div
          data-testid="ledger-reverse-confirm"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        >
          <div className="w-80 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
            <p className="mb-2 text-sm">确认撤销这笔账？将生成冲正记录。</p>
            <input
              data-testid="ledger-reverse-reason"
              className="mb-2 w-full rounded border border-border bg-background px-2 py-1 text-sm"
              placeholder="原因（必填）"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmId(null)}>
                取消
              </Button>
              <Button
                size="sm"
                data-testid="ledger-reverse-submit"
                disabled={!reason.trim()}
                onClick={() => {
                  reverse.mutate(
                    { entryId: confirmId, reason: reason.trim() },
                    { onSuccess: () => setConfirmId(null) },
                  )
                }}
              >
                确认撤销
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
