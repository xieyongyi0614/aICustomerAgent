import { useMemo, useState, type ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { copyText } from "@/lib/copy-text"
import { cn } from "@/lib/utils"
import { countJsonNodes, stringifyForCopy } from "./json-utils"

interface JsonViewerProps {
  data: unknown
  defaultExpandDepth?: number
  maxAutoNodes?: number
}

type BulkMode = "all" | "none" | null

function valueClass(value: unknown): string {
  if (value === null) return "text-fg-tertiary italic"
  switch (typeof value) {
    case "string":
      return "text-emerald-300"
    case "number":
      return "text-sky-300"
    case "boolean":
      return "text-violet-300"
    default:
      return "text-muted-foreground"
  }
}

function formatScalar(value: unknown): ReactNode {
  if (typeof value === "string") {
    return <span className={cn(valueClass(value))}>"{value}"</span>
  }
  return <span className={cn(valueClass(value))}>{String(value)}</span>
}

function previewText(value: object): string {
  if (Array.isArray(value)) return `Array(${value.length})`
  const keys = Object.keys(value)
  const head = keys.slice(0, 3).join(", ")
  return `{ ${head}${keys.length > 3 ? ", …" : ""} }`.replace("{  }", "{}")
}

function JsonViewer({
  data,
  defaultExpandDepth = 2,
  maxAutoNodes = 2000,
}: JsonViewerProps) {
  const nodeCount = useMemo(() => countJsonNodes(data), [data])
  const oversized = nodeCount > maxAutoNodes
  const baseDepth = oversized ? Math.min(defaultExpandDepth, 1) : defaultExpandDepth

  const [manual, setManual] = useState<Map<string, boolean>>(() => new Map())
  const [bulk, setBulk] = useState<BulkMode>(null)

  function computeOpen(path: string, depth: number): boolean {
    const manualValue = manual.get(path)
    if (manualValue !== undefined) return manualValue
    if (bulk === "all") return true
    if (bulk === "none") return false
    return depth < baseDepth
  }

  function toggle(path: string, currentOpen: boolean) {
    setManual((prev) => {
      const next = new Map(prev)
      next.set(path, !currentOpen)
      return next
    })
  }

  function renderNode(
    path: string,
    name: string | null,
    value: unknown,
    depth: number,
  ): ReactNode {
    const isBranch = value !== null && typeof value === "object"

    if (!isBranch) {
      return (
        <div className="flex items-baseline gap-2 font-mono text-xs leading-6">
          {name !== null ? <span className="text-muted-foreground">{name}:</span> : null}
          {formatScalar(value)}
        </div>
      )
    }

    const open = computeOpen(path, depth)

    function branchHeader(): ReactNode {
      return (
        <>
          <button
            type="button"
            data-testid={`json-toggle-${path}`}
            className="group inline-flex items-center gap-1 text-left hover:text-foreground"
            onClick={() => toggle(path, open)}
          >
            <span className="inline-block w-3 text-fg-tertiary">{open ? "▾" : "▸"}</span>
            {name !== null ? (
              <span className="text-muted-foreground">{name}:</span>
            ) : null}
            {!open ? (
              <span className="text-muted-foreground group-hover:text-foreground">
                {previewText(value as object)}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            data-testid={`json-copy-${path}`}
            className="ml-2 rounded px-1 text-[10px] text-fg-tertiary hover:text-foreground"
            onClick={() => copyText(stringifyForCopy(value))}
          >
            copy
          </button>
        </>
      )
    }

    let children: ReactNode = null
    if (open) {
      const entries: Array<[string, unknown]> = Array.isArray(value)
        ? (value as unknown[]).map((item, index) => [String(index), item])
        : Object.entries(value as Record<string, unknown>)
      children =
        entries.length === 0 ? (
          <div className="pl-5 font-mono text-xs leading-6 text-fg-tertiary">
            {Array.isArray(value) ? "[]" : "{}"}
          </div>
        ) : (
          <div className="border-l border-border/60 pl-4">
            {entries.map(([key, child]) =>
              renderNode(`${path}.${key}`, key, child, depth + 1),
            )}
          </div>
        )
    }

    return (
      <div className="font-mono text-xs leading-6">
        {branchHeader()}
        {children}
      </div>
    )
  }

  return (
    <div className="relative" data-testid="json-viewer">
      <div className="absolute right-0 -top-1 z-10 flex gap-1">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 font-mono text-[10px]"
          data-testid="json-expand-all"
          onClick={() => {
            setBulk("all")
            setManual(new Map())
          }}
        >
          expand all
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 font-mono text-[10px]"
          data-testid="json-collapse-all"
          onClick={() => {
            setBulk("none")
            setManual(new Map())
          }}
        >
          collapse all
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 font-mono text-[10px]"
          data-testid="json-copy-all"
          onClick={() => copyText(stringifyForCopy(data))}
        >
          copy
        </Button>
      </div>

      {oversized ? (
        <p
          data-testid="json-oversized-note"
          className="mb-2 font-mono text-[10px] text-status-warn"
        >
          对象过大（{nodeCount} 节点），已默认折叠展示
        </p>
      ) : null}

      {renderNode("$", null, data, 0)}
    </div>
  )
}

export { JsonViewer }
export type { JsonViewerProps }
