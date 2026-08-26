let started = false

export async function ensureMockRest(): Promise<void> {
  if (started) return
  started = true
  if (typeof window === "undefined") return
  const { setupWorker } = await import("msw/browser")
  const { restHandlers } = await import("@/mocks/msw-handlers")
  await setupWorker(...restHandlers).start({ onUnhandledRequest: "bypass", quiet: true })
}
