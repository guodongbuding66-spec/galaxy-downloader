import { LOCAL_ENGINE_REQUIRED_VERSION } from '@/lib/local-engine'

const LOCAL_ENGINE_BRIDGE_BASE_URLS = [
  'http://localhost:17836',
  'http://127.0.0.1:17836',
] as const

const REQUEST_TIMEOUT_MS = 1200

type LoopbackRequestInit = RequestInit & {
  targetAddressSpace?: 'loopback'
}

export interface LocalEngineVersionProbe {
  version: string
  compatible: boolean
}

function versionParts(value: string): number[] | null {
  const match = value.trim().match(/^(\d+)\.(\d+)\.(\d+)/)
  if (!match) return null
  return match.slice(1, 4).map(Number)
}

export function isLocalEngineVersionCompatible(
  version: string,
  minimum = LOCAL_ENGINE_REQUIRED_VERSION,
): boolean {
  const current = versionParts(version)
  const required = versionParts(minimum)
  if (!current || !required) return false
  for (let index = 0; index < 3; index += 1) {
    if (current[index]! > required[index]!) return true
    if (current[index]! < required[index]!) return false
  }
  return true
}

export async function probeLocalEngineVersion(): Promise<LocalEngineVersionProbe | null> {
  if (typeof window === 'undefined') return null

  for (const baseUrl of LOCAL_ENGINE_BRIDGE_BASE_URLS) {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    try {
      const init: LoopbackRequestInit = {
        cache: 'no-store',
        signal: controller.signal,
        targetAddressSpace: 'loopback',
      }
      const response = await fetch(`${baseUrl}/status`, init)
      if (!response.ok) continue
      const payload = await response.json() as { ok?: boolean; version?: unknown }
      if (!payload.ok || typeof payload.version !== 'string' || !payload.version.trim()) continue
      const version = payload.version.trim()
      return {
        version,
        compatible: isLocalEngineVersionCompatible(version),
      }
    } catch {
      // Try the alternate loopback hostname. This probe intentionally does not
      // classify network/Origin failures as an installed engine.
    } finally {
      window.clearTimeout(timeout)
    }
  }

  return null
}
