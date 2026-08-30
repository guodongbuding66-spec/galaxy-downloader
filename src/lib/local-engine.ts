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

export type LocalEngineBrowser = 'none' | 'edge' | 'chrome' | 'firefox'

export interface LocalDesktopJobOptions {
  sourceUrl: string
  videoQuality?: string
  audioQuality?: string
  includeAudio?: boolean
  includeSubtitle?: boolean
  subtitleLanguage?: string | null
  includeCover?: boolean
  browser?: LocalEngineBrowser
  playlist?: boolean
}

export const LOCAL_ENGINE_RELEASE_URL = 'https://github.com/guodongbuding66-spec/galaxy-downloader/releases/latest/download/GalaxyLocalEngine-Windows.zip'

export function buildLocalDesktopEngineUri(options: LocalDesktopJobOptions): string {
  const params = new URLSearchParams()
  params.set('url', options.sourceUrl)
  params.set('video', options.videoQuality || 'best')
  params.set('audio', options.audioQuality || 'best')
  params.set('include_audio', options.includeAudio === false ? '0' : '1')
  params.set('subtitle', options.includeSubtitle ? '1' : '0')
  if (options.subtitleLanguage) params.set('subtitle_lang', options.subtitleLanguage)
  params.set('cover', options.includeCover ? '1' : '0')
  params.set('browser', options.browser || 'none')
  params.set('playlist', options.playlist ? '1' : '0')
  return `galaxy-downloader://download?${params.toString()}`
}

export function launchLocalDesktopEngine(options: LocalDesktopJobOptions): void {
  if (typeof window === 'undefined') return
  window.location.href = buildLocalDesktopEngineUri(options)
}
