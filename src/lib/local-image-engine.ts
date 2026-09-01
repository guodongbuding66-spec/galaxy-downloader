const IMAGE_ENGINE_BASE_URLS = [
  'http://localhost:17837',
  'http://127.0.0.1:17837',
] as const

const MIN_IMAGE_ENGINE_VERSION = '0.7.0'
const REQUEST_TIMEOUT_MS = 1600

type LoopbackRequestInit = RequestInit & {
  targetAddressSpace?: 'loopback'
}

export interface LocalImageDownloadJob {
  images: string[]
  title: string
  sourceUrl?: string | null
  package?: boolean
  description?: string | null
  markdownContent?: string | null
  author?: string | null
  publishedAt?: string | null
}

export interface LocalImageEngineSubmission {
  available: boolean
  accepted: boolean
  busy: boolean
  message?: string
}

let preferredBaseUrl: string | null = null

function versionParts(value: string): number[] | null {
  const match = value.trim().match(/^(\d+)\.(\d+)\.(\d+)/)
  if (!match) return null
  return match.slice(1, 4).map(Number)
}

function versionAtLeast(value: string, minimum: string): boolean {
  const current = versionParts(value)
  const required = versionParts(minimum)
  if (!current || !required) return false
  for (let index = 0; index < 3; index += 1) {
    if (current[index]! > required[index]!) return true
    if (current[index]! < required[index]!) return false
  }
  return true
}

function candidateBaseUrls(): string[] {
  const values = preferredBaseUrl
    ? [preferredBaseUrl, ...IMAGE_ENGINE_BASE_URLS]
    : [...IMAGE_ENGINE_BASE_URLS]
  return [...new Set(values)]
}

async function loopbackFetch(path: string, init?: RequestInit): Promise<Response | null> {
  for (const baseUrl of candidateBaseUrls()) {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
    try {
      const requestInit: LoopbackRequestInit = {
        cache: 'no-store',
        ...init,
        signal: controller.signal,
        targetAddressSpace: 'loopback',
      }
      const response = await fetch(`${baseUrl}${path}`, requestInit)
      preferredBaseUrl = baseUrl
      return response
    } catch {
      // Try the other loopback hostname. Chrome/Edge local-network policy can
      // behave differently for localhost and 127.0.0.1.
    } finally {
      window.clearTimeout(timeout)
    }
  }
  return null
}

export async function getLocalImageEngineVersion(): Promise<string | null> {
  if (typeof window === 'undefined') return null
  const response = await loopbackFetch('/status')
  if (!response?.ok) return null
  try {
    const payload = await response.json() as { ok?: boolean; version?: string; imageDownloads?: boolean }
    if (!payload.ok || !payload.imageDownloads || typeof payload.version !== 'string') return null
    return versionAtLeast(payload.version, MIN_IMAGE_ENGINE_VERSION) ? payload.version : null
  } catch {
    return null
  }
}

export async function submitLocalImageDownload(
  job: LocalImageDownloadJob,
): Promise<LocalImageEngineSubmission> {
  if (typeof window === 'undefined') {
    return { available: false, accepted: false, busy: false }
  }
  const version = await getLocalImageEngineVersion()
  if (!version) {
    return { available: false, accepted: false, busy: false }
  }
  const response = await loopbackFetch('/download-images', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(job),
  })
  if (!response) {
    return { available: false, accepted: false, busy: false }
  }
  let message = ''
  try {
    const payload = await response.json() as { accepted?: boolean; message?: string }
    message = String(payload.message || '')
    if (response.ok && payload.accepted) {
      return { available: true, accepted: true, busy: false, message }
    }
  } catch {
    // Keep the status-based fallback below.
  }
  return {
    available: true,
    accepted: false,
    busy: response.status === 409,
    message: message || `Local image engine returned HTTP ${response.status}`,
  }
}
