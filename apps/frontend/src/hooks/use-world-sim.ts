import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { qk } from "@/api/query-keys"
import {
  getWorldPlan,
  getWorldSimulation,
  getWorldSituations,
  postWorldSimTick,
} from "@/api/world-sim"

const WORLD_SIM_STALE_MS = 5_000

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

export function useWorldSimulation(userId: string, enabled = true) {
  return useQuery({
    queryKey: qk.worldSimulation(userId),
    queryFn: () => getWorldSimulation(userId),
    staleTime: WORLD_SIM_STALE_MS,
    enabled,
  })
}

export function useWorldPlan(userId: string, date: string = todayIso(), enabled = true) {
  return useQuery({
    queryKey: qk.worldPlan(userId, date),
    queryFn: () => getWorldPlan(userId, date),
    staleTime: WORLD_SIM_STALE_MS,
    enabled,
  })
}

export function useWorldSituations(userId: string, includeExpired = false, enabled = true) {
  return useQuery({
    queryKey: qk.worldSituations(userId, includeExpired),
    queryFn: () => getWorldSituations(userId, includeExpired),
    staleTime: WORLD_SIM_STALE_MS,
    enabled,
  })
}

export function useWorldSimTick(userId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => postWorldSimTick(userId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: qk.worldSimulation(userId) })
      void queryClient.invalidateQueries({ queryKey: qk.worldPlan(userId, todayIso()) })
      void queryClient.invalidateQueries({ queryKey: qk.worldSituations(userId, false) })
    },
  })
}
