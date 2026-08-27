import { requestJson } from "@/api/http"
import type { LlmProfilesDto } from "@/types/backend/llm"

export async function fetchLlmProfiles(): Promise<LlmProfilesDto> {
  return requestJson<LlmProfilesDto>("/api/v1/llm/profiles")
}
