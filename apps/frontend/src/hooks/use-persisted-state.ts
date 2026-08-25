import { useCallback, useState } from "react"

type PersistableValue = string | number | boolean

export function usePersistedState<T extends PersistableValue>(
  key: string,
  initial: T,
): [T, (next: T) => void] {
  const [value, setValue] = useState<T>(() => (readStorage(key) as T | null) ?? initial)
  const set = useCallback(
    (next: T) => {
      setValue(next)
      writeStorage(key, next)
    },
    [key],
  )
  return [value, set]
}

function readStorage(key: string): PersistableValue | null {
  try {
    if (typeof localStorage === "undefined") return null
    const raw = localStorage.getItem(key)
    if (raw === null) return null
    const parsed: unknown = JSON.parse(raw)
    return typeof parsed === "boolean" || typeof parsed === "number" || typeof parsed === "string"
      ? parsed
      : null
  } catch {
    return null
  }
}

function writeStorage(key: string, value: PersistableValue): void {
  try {
    if (typeof localStorage === "undefined") return
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    return
  }
}
