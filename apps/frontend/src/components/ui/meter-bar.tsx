import { cn } from "@/lib/utils"

interface MeterBarProps {
  value: number
  max?: number
  ticks?: readonly number[]
  toneClassName?: string
  className?: string
}

function toRatio(value: number, max: number) {
  if (max <= 0) return 0
  return Math.min(Math.max(value / max, 0), 1)
}

function MeterBar({ value, max = 1, ticks, toneClassName, className }: MeterBarProps) {
  const ratio = toRatio(value, max)
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      data-slot="meter-bar"
      className={cn("relative h-1.5 w-full rounded-full bg-muted", className)}
    >
      <div
        data-slot="meter-bar-indicator"
        className={cn("absolute inset-y-0 left-0 rounded-full bg-primary", toneClassName)}
        style={{ width: `${ratio * 100}%` }}
      />
      {(ticks ?? []).map((tick) => (
        <span
          key={tick}
          data-slot="meter-bar-tick"
          className="absolute -top-1 -bottom-1 w-px bg-neutral-500"
          style={{ left: `${toRatio(tick, max) * 100}%` }}
        />
      ))}
    </div>
  )
}

export { MeterBar }
export type { MeterBarProps }
