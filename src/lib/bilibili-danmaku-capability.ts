import {
  normalizeLocalEngineDanmakuFormats,
  type LocalEngineDanmakuFormat,
} from '@/lib/local-engine'

const LOOPBACK_STATUS_URLS = [
  'http://localhost:17836/status',
  'http://127.0.0.1:17836/status',
] as const
const CAPABILITY_TIMEOUT_MS = 1200

interface LoopbackRequestInit extends RequestInit {
  targetAddressSpace?: 'loopback'
}

export function normalizeBilibiliDanmakuFormatCapability(
  value: unknown,
): LocalEngineDanmakuFormat[] {
  if (!value || typeof value !== 'object') return ['xml']
  const payload = value as Record<string, unknown>
  if (payload.ok !== true || !Array.isArray(payload.bilibiliDanmakuFormats)) return ['xml']
  return normalizeLocalEngineDanmakuFormats(
    payload.bilibiliDanmakuFormats.map((item) => String(item || '')),
  )
}

export async function getBilibiliDanmakuFormatCapability(
  fetcher: typeof fetch = fetch,
): Promise<LocalEngineDanmakuFormat[]> {
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
      const payload = await response.json() as unknown
      return normalizeBilibiliDanmakuFormatCapability(payload)
    } catch {
      // A missing/older/offline Local Engine must never unlock formats it did
      // not explicitly advertise. Try the alternate loopback hostname first.
    } finally {
      clearTimeout(timeout)
    }
  }
  return ['xml']
}
