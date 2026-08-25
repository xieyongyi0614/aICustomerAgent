export type ApiMode = 'real' | 'mock'

export const API_MODE_STORAGE_KEY = 'asuna-debug.apiMode'

export function resolveApiMode(envValue: unknown, storedValue: unknown): ApiMode {
  if (storedValue === 'mock' || storedValue === 'real') return storedValue
  if (envValue === 'mock' || envValue === 'real') return envValue
  return 'real'
}

export function readStoredApiMode(): ApiMode | null {
  try {
    if (typeof localStorage === "undefined") return null
    const value = localStorage.getItem(API_MODE_STORAGE_KEY)
    return value === "mock" || value === "real" ? value : null
  } catch {
    return null
  }
}

export function writeStoredApiMode(mode: ApiMode): void {
  try {
    if (typeof localStorage === "undefined") return
    localStorage.setItem(API_MODE_STORAGE_KEY, mode)
  } catch {
    return
  }
}

export function getActiveApiMode(): ApiMode {
  return resolveApiMode(import.meta.env.VITE_API_MODE, readStoredApiMode())
}

