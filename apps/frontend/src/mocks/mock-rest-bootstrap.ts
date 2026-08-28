import type { setupWorker } from "msw/browser"

type MockServiceWorker = Awaited<ReturnType<typeof setupWorker>>

let started = false
let worker: MockServiceWorker | null = null

export async function ensureMockRest(): Promise<void> {
  if (started) return
  started = true
  if (typeof window === "undefined") return
  const { setupWorker } = await import("msw/browser")
  const { restHandlers } = await import("@/mocks/msw-handlers")
  worker = setupWorker(...restHandlers)
  await worker.start({ onUnhandledRequest: "bypass", quiet: true })
}

export async function disableMockRest(): Promise<void> {
  if (worker !== null) {
    worker.stop()
    worker = null
    started = false
    return
  }
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return
  const registrations = await navigator.serviceWorker.getRegistrations()
  await Promise.all(registrations.map((registration) => registration.unregister()))
}
