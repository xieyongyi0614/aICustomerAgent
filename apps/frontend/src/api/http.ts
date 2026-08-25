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
