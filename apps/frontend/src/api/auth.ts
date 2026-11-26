import { requestJson } from "@/api/http"

export interface MeDto {
  user_id: string
  device_id: string
  expires_at: string
}

export async function fetchMe(): Promise<MeDto> {
  return requestJson<MeDto>("/api/v1/auth/me")
}
