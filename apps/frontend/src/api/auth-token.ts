const STORAGE_KEY = "asuna-debug.authToken"

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function setStoredToken(token: string): void {
  window.localStorage.setItem(STORAGE_KEY, token.trim())
}

export function clearStoredToken(): void {
  window.localStorage.removeItem(STORAGE_KEY)
}

export function authHeaders(): Record<string, string> {
  const token = getStoredToken()
  if (!token) return {}
  return { Authorization: `Bearer ${token}` }
}
