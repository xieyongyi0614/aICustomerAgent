export interface LlmProfileDto {
  id: string
  label: string
  model: string
  default: boolean
}

export interface LlmProfilesDto {
  default: string
  profiles: LlmProfileDto[]
}
