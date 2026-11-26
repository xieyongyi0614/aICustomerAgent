import { authHeaders } from "@/api/auth-token"

export class ApiError extends Error {
  readonly status?: number
  readonly code?: string

  constructor(message: string, options?: { status?: number; code?: string }) {
    super(message)
    this.name = 'ApiError'
    this.status = options?.status
    this.code = options?.code
  }
}

export function resolveApiBase(): string {
  const base = import.meta.env.VITE_API_BASE_URL
  if (typeof base !== 'string' || base.length === 0) return ''
  return base.replace(/\/+$/, '')
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null) return null
  return value as Record<string, unknown>
}

export async function toApiErrorFromResponse(response: Response): Promise<ApiError> {
  let message = `request failed with status ${response.status}`
  let code: string | undefined
  try {
    const data = asRecord(await response.json())
    if (data !== null) {
      if (typeof data.detail === 'string') message = data.detail
      const errorBody = asRecord(data.error)
      if (errorBody !== null && typeof errorBody.message === 'string') {
        message = errorBody.message
      }
      if (errorBody !== null && errorBody.code !== undefined) {
        code = String(errorBody.code)
      }
    }
  } catch {
    message = `request failed with status ${response.status}`
  }
  return new ApiError(message, { status: response.status, code })
}

export async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  for (const [key, value] of Object.entries(authHeaders())) {
    if (!headers.has(key)) headers.set(key, value)
  }
  const response = await fetch(`${resolveApiBase()}${path}`, { ...init, headers })
  if (!response.ok) {
    throw await toApiErrorFromResponse(response)
  }
  return (await response.json()) as T
}
