import { useQuery } from "@tanstack/react-query"

import { fetchLlmProfiles } from "@/api/llm"
import { qk } from "@/api/query-keys"
import { resolveActiveLlmProfileId } from "@/lib/llm-profile-storage"
import type { LlmProfilesDto } from "@/types/backend/llm"

export function useLlmProfiles() {
  const query = useQuery<LlmProfilesDto>({
    queryKey: qk.llmProfiles,
    queryFn: fetchLlmProfiles,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const profiles = query.data?.profiles ?? []

  return {
    profiles,
    activeProfileId: resolveActiveLlmProfileId(profiles),
    isLoading: query.isLoading,
  }
}