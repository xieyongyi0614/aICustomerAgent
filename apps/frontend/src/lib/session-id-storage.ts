import { load } from "@fingerprintjs/fingerprintjs"

const STORAGE_KEY = "asuna-debug.sessionId"
const FALLBACK_PREFIX = "fallback-session-"

function readStorage(): string | null {
  try {
    if (typeof localStorage === "undefined") return null
    const value = localStorage.getItem(STORAGE_KEY)
    return typeof value === "string" && value.length > 0 ? value : null
  } catch {
    return null
  }
}

function writeStorage(value: string): void {
  try {
    if (typeof localStorage === "undefined") return
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    return
  }
}

export function readStoredSessionId(): string | null {
  return readStorage()
}

export function writeStoredSessionId(sessionId: string): void {
  if (sessionId.trim().length === 0) return
  writeStorage(sessionId.trim())
}

export function clearStoredSessionId(): void {
  try {
    if (typeof localStorage === "undefined") return
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    return
  }
}

function fallbackSessionId(): string {
  return `${FALLBACK_PREFIX}${Math.random().toString(36).slice(2, 10)}`
}

async function computeDeviceFingerprint(): Promise<string> {
  try {
    const agent = await load()
    const { visitorId } = await agent.get()
    if (visitorId.length > 0) return visitorId
  } catch {
    return fallbackSessionId()
  }
  return fallbackSessionId()
}

export async function resolveInitialSessionId(): Promise<string> {
  const stored = readStorage()
  if (stored !== null) return stored
  const fingerprint = await computeDeviceFingerprint()
  writeStorage(fingerprint)
  return fingerprint
}
