import { useCallback, useEffect, useRef, useState } from "react"

const NEAR_BOTTOM_THRESHOLD_PX = 40

interface UseAutoScrollOptions {
  contentKey: unknown
  enabled: boolean
}

interface UseAutoScrollReturn {
  containerRef: React.RefObject<HTMLDivElement | null>
  isFollowing: boolean
  handleScroll: () => void
  scrollToBottom: () => void
  resetFollow: () => void
}

export function useAutoScroll({
  contentKey,
  enabled,
}: UseAutoScrollOptions): UseAutoScrollReturn {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [isFollowing, setIsFollowing] = useState(true)

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    setIsFollowing(true)
  }, [])

  const handleScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight
    setIsFollowing(distance < NEAR_BOTTOM_THRESHOLD_PX)
  }, [])

  const resetFollow = useCallback(() => {
    setIsFollowing(true)
  }, [])

  useEffect(() => {
    if (!enabled || !isFollowing) return
    scrollToBottom()
  }, [contentKey, enabled, isFollowing, scrollToBottom])

  return { containerRef, isFollowing, handleScroll, scrollToBottom, resetFollow }
}
