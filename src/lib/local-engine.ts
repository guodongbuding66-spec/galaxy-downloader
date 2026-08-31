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
export type LocalEngineCollectionMode = 'single' | 'all' | 'selected'

export interface LocalDesktopVideoSelection {
  quality?: string | null
  label?: string | null
  height?: number | null
}

export interface LocalDesktopJobOptions {
  sourceUrl: string
  videoQuality?: string
  audioQuality?: string
  includeAudio?: boolean
  includeSubtitle?: boolean
  subtitleLanguage?: string | null
  includeCover?: boolean
  browser?: LocalEngineBrowser
  collectionMode?: LocalEngineCollectionMode
  selectedItems?: number[]
  /** @deprecated Use collectionMode. Kept for older call sites/releases. */
  playlist?: boolean
}

// Primary route goes through the Galaxy website so users whose network cannot
// directly reach GitHub can still download the official release package.
export const LOCAL_ENGINE_RELEASE_URL = '/api/local-engine/download'

// Keep the original GitHub Latest Release as a visible backup mirror.
export const LOCAL_ENGINE_GITHUB_URL = 'https://github.com/guodongbuding66-spec/galaxy-downloader/releases/latest/download/GalaxyLocalEngine-Windows.zip'

const COMMON_VIDEO_HEIGHTS = new Set([144, 240, 360, 480, 540, 720, 1080, 1440, 2160, 4320])

function validHeight(value: number): boolean {
  return Number.isFinite(value) && value >= 100 && value <= 10000
}

export function resolveLocalDesktopVideoQuality(
  selection?: LocalDesktopVideoSelection | null,
): string {
  if (!selection) return 'best'

  if (typeof selection.height === 'number' && validHeight(selection.height)) {
    return String(Math.round(selection.height))
  }

  const quality = selection.quality?.trim() || ''
  if (!quality || quality.toLowerCase() === 'best') return 'best'

  const labelMatch = selection.label?.match(/(?:^|\D)(\d{3,4})\s*p(?:\D|$)/i)
  if (labelMatch) return labelMatch[1]

  const explicitQuality = quality.match(/^(\d{3,4})p$/i)
  if (explicitQuality) return explicitQuality[1]

  const numericQuality = quality.match(/^\d{3,4}$/)
  if (numericQuality && COMMON_VIDEO_HEIGHTS.has(Number(quality))) {
    return quality
  }

  // Parser format IDs such as YouTube 137 are not resolutions. When the
  // parser does not expose a height/label, let yt-dlp choose the best stream
  // rather than accidentally treating a format ID as a pixel height.
  return 'best'
}

function normalizeSelectedItems(items?: number[]): number[] {
  if (!items?.length) return []
  const normalized: number[] = []
  for (const raw of items) {
    const value = Math.trunc(Number(raw))
    if (!Number.isFinite(value) || value <= 0 || normalized.includes(value)) continue
    normalized.push(value)
    if (normalized.length >= 500) break
  }
  return normalized
}

export function resolveLocalEngineCollectionMode(
  options: Pick<LocalDesktopJobOptions, 'collectionMode' | 'playlist' | 'selectedItems'>,
): LocalEngineCollectionMode {
  const selectedItems = normalizeSelectedItems(options.selectedItems)
  if (options.collectionMode === 'selected') {
    return selectedItems.length ? 'selected' : 'single'
  }
  if (options.collectionMode === 'all' || options.collectionMode === 'single') {
    return options.collectionMode
  }
  return options.playlist ? 'all' : 'single'
}

export function buildLocalDesktopEngineUri(options: LocalDesktopJobOptions): string {
  const params = new URLSearchParams()
  const selectedItems = normalizeSelectedItems(options.selectedItems)
  const collectionMode = resolveLocalEngineCollectionMode({
    collectionMode: options.collectionMode,
    playlist: options.playlist,
    selectedItems,
  })

  params.set('url', options.sourceUrl)
  params.set('video', options.videoQuality || 'best')
  params.set('audio', options.audioQuality || 'best')
  params.set('include_audio', options.includeAudio === false ? '0' : '1')
  params.set('subtitle', options.includeSubtitle ? '1' : '0')
  if (options.subtitleLanguage) params.set('subtitle_lang', options.subtitleLanguage)
  params.set('cover', options.includeCover ? '1' : '0')
  params.set('browser', options.browser || 'none')
  params.set('collection', collectionMode)
  if (collectionMode === 'selected') params.set('items', selectedItems.join(','))
  // Preserve the legacy field so a protocol URL is still understandable by
  // pre-0.5 engines, while new engines use the explicit collection policy.
  params.set('playlist', collectionMode === 'all' ? '1' : '0')
  return `galaxy-downloader://download?${params.toString()}`
}

export function launchLocalDesktopEngine(options: LocalDesktopJobOptions): void {
  if (typeof window === 'undefined') return
  window.location.href = buildLocalDesktopEngineUri(options)
}
