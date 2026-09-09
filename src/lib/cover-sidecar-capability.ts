const LOOPBACK_STATUS_URLS = [
  'http://localhost:17836/status',
  'http://127.0.0.1:17836/status',
] as const
const CAPABILITY_TIMEOUT_MS = 1200

interface LoopbackRequestInit extends RequestInit {
  targetAddressSpace?: 'loopback'
}

export function normalizeCoverSidecarCapability(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const payload = value as Record<string, unknown>
  return payload.ok === true && payload.coverSidecar === true
}

export async function getCoverSidecarCapability(
  fetcher: typeof fetch = fetch,
): Promise<boolean> {
  for (const url of LOOPBACK_STATUS_URLS) {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), CAPABILITY_TIMEOUT_MS)
    try {
      const init: LoopbackRequestInit = {
        cache: 'no-store',
        signal: controller.signal,
        targetAddressSpace: 'loopback',
      }
      const response = await fetcher(url, init)
      if (!response.ok) continue
      return normalizeCoverSidecarCapability(await response.json() as unknown)
    } catch {
      // Missing, older and offline engines fail closed. Try the alternate
      // loopback hostname before deciding that cover sidecars are unavailable.
    } finally {
      clearTimeout(timeout)
    }
  }
  return false
}
