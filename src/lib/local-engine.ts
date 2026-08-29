export const GALAXY_LOCAL_ENGINE_PROTOCOL_VERSION = 1 as const

export type GalaxyLocalEngineMethod =
  | 'engine.status'
  | 'engine.cookies'
  | 'media.parse'
  | 'media.download'
  | 'media.cancel'

export interface LocalProcessingCapabilities {
  webAssembly: boolean
  sharedArrayBuffer: boolean
  crossOriginIsolated: boolean
  multiThreadFFmpeg: boolean
  opfs: boolean
  serviceWorker: boolean
  wakeLock: boolean
}

export interface GalaxyCompanionCapabilities {
  protocolVersion: number
  engineVersion: string
  pyodide: boolean
  ytDlp: boolean
  ffmpegWasm: boolean
  cookies: boolean
  crossOriginFetch: boolean
}

export interface GalaxyCompanionStatus {
  available: boolean
  capabilities: GalaxyCompanionCapabilities | null
  reason?: string
}

interface BrowserFeatureRuntime {
  WebAssembly?: unknown
  SharedArrayBuffer?: unknown
  crossOriginIsolated?: boolean
  navigator?: {
    storage?: {
      getDirectory?: unknown
    }
    serviceWorker?: unknown
    wakeLock?: unknown
  }
}

interface CompanionEnvelope {
  source: 'galaxy-companion'
  protocolVersion: number
  requestId: string
  type: 'response' | 'event'
  ok?: boolean
  result?: unknown
  error?: string
}

function browserRuntime(): BrowserFeatureRuntime {
  if (typeof window === 'undefined') return {}
  return window as unknown as BrowserFeatureRuntime
}

export function detectLocalProcessingCapabilities(
  runtime: BrowserFeatureRuntime = browserRuntime(),
): LocalProcessingCapabilities {
  const navigatorLike = runtime.navigator
  const webAssembly = typeof runtime.WebAssembly !== 'undefined'
  const sharedArrayBuffer = typeof runtime.SharedArrayBuffer !== 'undefined'
  const isolated = runtime.crossOriginIsolated === true

  return {
    webAssembly,
    sharedArrayBuffer,
    crossOriginIsolated: isolated,
    multiThreadFFmpeg: webAssembly && sharedArrayBuffer && isolated,
    opfs: typeof navigatorLike?.storage?.getDirectory === 'function',
    serviceWorker: typeof navigatorLike?.serviceWorker !== 'undefined',
    wakeLock: typeof navigatorLike?.wakeLock !== 'undefined',
  }
}

export function isGalaxyCompanionEnvelope(value: unknown): value is CompanionEnvelope {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const candidate = value as Partial<CompanionEnvelope>
  return candidate.source === 'galaxy-companion'
    && typeof candidate.protocolVersion === 'number'
    && typeof candidate.requestId === 'string'
    && (candidate.type === 'response' || candidate.type === 'event')
}

function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `galaxy-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export async function requestGalaxyCompanion<T = unknown>(
  method: GalaxyLocalEngineMethod,
  params: Record<string, unknown> = {},
  timeoutMs = 1_500,
): Promise<T> {
  if (typeof window === 'undefined') {
    throw new Error('Galaxy Companion is only available in a browser')
  }

  const requestId = createRequestId()

  return new Promise<T>((resolve, reject) => {
    let settled = false

    const cleanup = () => {
      window.removeEventListener('message', handleMessage)
      window.clearTimeout(timeoutId)
    }

    const settle = (operation: () => void) => {
      if (settled) return
      settled = true
      cleanup()
      operation()
    }

    const handleMessage = (event: MessageEvent) => {
      if (event.source !== window || !isGalaxyCompanionEnvelope(event.data)) return
      if (event.data.requestId !== requestId || event.data.type !== 'response') return

      if (event.data.protocolVersion !== GALAXY_LOCAL_ENGINE_PROTOCOL_VERSION) {
        settle(() => reject(new Error('Galaxy Companion protocol version mismatch')))
        return
      }

      if (event.data.ok === false) {
        settle(() => reject(new Error(event.data.error || 'Galaxy Companion request failed')))
        return
      }

      settle(() => resolve(event.data.result as T))
    }

    const timeoutId = window.setTimeout(() => {
      settle(() => reject(new Error('Galaxy Companion did not respond')))
    }, timeoutMs)

    window.addEventListener('message', handleMessage)
    window.postMessage({
      source: 'galaxy-web',
      protocolVersion: GALAXY_LOCAL_ENGINE_PROTOCOL_VERSION,
      requestId,
      type: 'request',
      method,
      params,
    }, window.location.origin)
  })
}

export async function probeGalaxyCompanion(timeoutMs = 800): Promise<GalaxyCompanionStatus> {
  try {
    const capabilities = await requestGalaxyCompanion<GalaxyCompanionCapabilities>(
      'engine.status',
      {},
      timeoutMs,
    )

    if (!capabilities || capabilities.protocolVersion !== GALAXY_LOCAL_ENGINE_PROTOCOL_VERSION) {
      return {
        available: false,
        capabilities: null,
        reason: 'protocol-mismatch',
      }
    }

    return {
      available: true,
      capabilities,
    }
  } catch (error) {
    return {
      available: false,
      capabilities: null,
      reason: error instanceof Error ? error.message : String(error),
    }
  }
}
