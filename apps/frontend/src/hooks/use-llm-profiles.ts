import { useQuery } from "@tanstack/react-query"
import { useState } from "react"

import { fetchLlmProfiles } from "@/api/llm"
import { qk } from "@/api/query-keys"
import { writeStoredLlmProfile, resolveActiveLlmProfileId } from "@/lib/llm-profile-storage"
import type { LlmProfilesDto } from "@/types/backend/llm"

export function useLlmProfiles() {
  const query = useQuery<LlmProfilesDto>({
    queryKey: qk.llmProfiles,
    queryFn: fetchLlmProfiles,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const [override, setOverride] = useState<string | null | undefined>(undefined)

  const profiles = query.data?.profiles ?? []
  const activeProfileId =
    override !== undefined ? override : resolveActiveLlmProfileId(profiles)

  function selectProfile(profileId: string): void {
    writeStoredLlmProfile(profileId)
    setOverride(profileId)
  }

  return {
    profiles,
    activeProfileId,
    selectProfile,
    isLoading: query.isLoading,
  }
}