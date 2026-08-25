export function formatRelativeTime(timestampMs: number, nowMs: number = Date.now()): string {
  const diffSeconds = Math.floor((nowMs - timestampMs) / 1000)
  if (diffSeconds < 60) return "刚刚"
  const diffMinutes = Math.floor(diffSeconds / 60)
  if (diffMinutes < 60) return `${diffMinutes} 分钟前`
  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours} 小时前`
  const date = new Date(timestampMs)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${date.getMonth() + 1}-${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function formatDurationMs(durationMs: number): string {
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`
  return `${(durationMs / 1000).toFixed(1)}s`
}
