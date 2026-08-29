export type LocalEngineProfile = 'unsupported' | 'single-thread' | 'multi-thread'

export interface LocalProcessingCapabilities {
  webAssembly: boolean
  sharedArrayBuffer: boolean
  crossOriginIsolated: boolean
  multiThreadFFmpeg: boolean
  opfs: boolean
  serviceWorker: boolean
  wakeLock: boolean
  profile: LocalEngineProfile
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
  const multiThreadFFmpeg = webAssembly && sharedArrayBuffer && isolated
  const profile: LocalEngineProfile = !webAssembly
    ? 'unsupported'
    : multiThreadFFmpeg
      ? 'multi-thread'
      : 'single-thread'

  return {
    webAssembly,
    sharedArrayBuffer,
    crossOriginIsolated: isolated,
    multiThreadFFmpeg,
    opfs: typeof navigatorLike?.storage?.getDirectory === 'function',
    serviceWorker: typeof navigatorLike?.serviceWorker !== 'undefined',
    wakeLock: typeof navigatorLike?.wakeLock !== 'undefined',
    profile,
  }
}

export function canProcessMediaLocally(
  capabilities: LocalProcessingCapabilities = detectLocalProcessingCapabilities(),
): boolean {
  return capabilities.webAssembly
}

export function shouldUseFileBackedInputs(
  capabilities: LocalProcessingCapabilities = detectLocalProcessingCapabilities(),
): boolean {
  return capabilities.webAssembly && capabilities.opfs
}
