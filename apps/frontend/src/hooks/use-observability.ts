import { useQuery } from "@tanstack/react-query"

import { ApiError } from "@/api/http"
import { qk } from "@/api/query-keys"
import {
  fetchMemories,
  fetchState,
  fetchTurnTrace,
} from "@/api/rest"
import type { TurnTrace } from "@/types/domain/observability"

export const TRACE_POLL_INTERVAL_MS = 800
export const TRACE_POLL_MAX_FETCHES = 6

const STATE_STALE_MS = 5_000
const MEMORIES_STALE_MS = 10_000

export function useCharacterState(userId = "default-user") {
  return useQuery({
    queryKey: qk.state(userId),
    queryFn: () => fetchState(userId),
    staleTime: STATE_STALE_MS,
  })
}

export function useMemories(userId = "default-user") {
  return useQuery({
    queryKey: qk.memories(userId),
    queryFn: () => fetchMemories(userId),
    staleTime: MEMORIES_STALE_MS,
  })
}

export class PendingTraceSignal extends Error {
  readonly pendingData: TurnTrace

  constructor(data: TurnTrace) {
    super("trace pending")
    this.name = "PendingTraceSignal"
    this.pendingData = data
  }
}

export function isTraceNotFound(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    typeof error.status === "number" &&
    error.status === 404
  )
}

function isPendingSignal(error: unknown): error is PendingTraceSignal {
  return error instanceof PendingTraceSignal
}

interface TurnTraceOptions {
  pollIntervalMs?: number
}

export function useTurnTrace(turnId: string | null, options?: TurnTraceOptions) {
  const pollIntervalMs = options?.pollIntervalMs ?? TRACE_POLL_INTERVAL_MS
  return useQuery<TurnTrace, Error>({
    queryKey: qk.turnTrace(turnId ?? "__none__"),
    queryFn: async () => {
      const data = await fetchTurnTrace(turnId as string)
      if (data.status === "pending") {
        throw new PendingTraceSignal(data)
      }
      return data
    },
    enabled: turnId !== null,
    retry: (failureCount, error) =>
      isPendingSignal(error) && failureCount < TRACE_POLL_MAX_FETCHES - 1,
    retryDelay: pollIntervalMs,
    staleTime: 30_000,
  })
}
