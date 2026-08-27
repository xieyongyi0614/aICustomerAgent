const STORAGE_KEY = "asuna-debug.llmProfile"

export function readStoredLlmProfile(): string | null {
  try {
    if (typeof localStorage === "undefined") return null
    const value = localStorage.getItem(STORAGE_KEY)
    return typeof value === "string" && value.length > 0 ? value : null
  } catch {
    return null
  }
}

export function writeStoredLlmProfile(profileId: string): void {
  try {
    if (typeof localStorage === "undefined") return
    localStorage.setItem(STORAGE_KEY, profileId)
  } catch {
    return
  }
}

export function clearStoredLlmProfile(): void {
  try {
    if (typeof localStorage === "undefined") return
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    return
  }
}

interface LlmProfileCandidate {
  id: string
  default: boolean
}

export function resolveActiveLlmProfileId(
  candidates: LlmProfileCandidate[],
): string | null {
  const stored = readStoredLlmProfile()
  const fallback = candidates.find((candidate) => candidate.default)?.id ?? null
  if (stored === null) return fallback
  if (candidates.length > 0 && !candidates.some((candidate) => candidate.id === stored)) {
    clearStoredLlmProfile()
    return fallback
  }
  return stored
}