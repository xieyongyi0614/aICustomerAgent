export function countJsonNodes(value: unknown): number {
  if (value === null || typeof value !== "object") return 1
  if (Array.isArray(value)) {
    let total = 1
    for (const item of value) total += countJsonNodes(item)
    return total
  }
  let total = 1
  for (const key of Object.keys(value as Record<string, unknown>)) {
    total += countJsonNodes((value as Record<string, unknown>)[key])
  }
  return total
}

export function collectJsonPaths(
  value: unknown,
  prefix = "$",
  out: string[] = [],
): string[] {
  out.push(prefix)
  if (value === null || typeof value !== "object") return out
  if (Array.isArray(value)) {
    value.forEach((item, index) => collectJsonPaths(item, `${prefix}[${index}]`, out))
    return out
  }
  for (const key of Object.keys(value as Record<string, unknown>)) {
    collectJsonPaths((value as Record<string, unknown>)[key], `${prefix}.${key}`, out)
  }
  return out
}

export function stringifyForCopy(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? String(value)
  } catch {
    return "[unserializable]"
  }
}
