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
export type LocalEngineSubtitleMode = 'manual' | 'auto' | 'both'
export type SponsorBlockCategory =
  | 'sponsor'
  | 'selfpromo'
  | 'interaction'
  | 'intro'
  | 'outro'
  | 'preview'
  | 'music_offtopic'
  | 'filler'

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
  skipPreviouslyDownloaded?: boolean
  browser?: LocalEngineBrowser
  collectionMode?: LocalEngineCollectionMode
  selectedItems?: number[]
  segmentStart?: string | null
  segmentEnd?: string | null
  splitChapters?: boolean
  subtitleMode?: LocalEngineSubtitleMode
  subtitleLanguages?: string[]
  audioLanguages?: string[]
  sponsorBlockCategories?: SponsorBlockCategory[]
  useAria2c?: boolean
  /** @deprecated Use collectionMode. Kept for older call sites/releases. */
  playlist?: boolean
}

// Keep one source of truth for the website/bridge/image-engine requirement and
// for the exact GitHub release tag the website serves. This prevents a newer
// website build from silently downloading an older `releases/latest` package.
export const LOCAL_ENGINE_REQUIRED_VERSION = '0.15.0'
export const LOCAL_ENGINE_RELEASE_TAG = `local-engine-v${LOCAL_ENGINE_REQUIRED_VERSION}`

// Primary route goes through the Galaxy website so users whose network cannot
// directly reach GitHub can still download the exact release required by this
// website build.
export const LOCAL_ENGINE_RELEASE_URL =
  `/api/local-engine/download?version=${LOCAL_ENGINE_REQUIRED_VERSION}`

// Keep GitHub as a visible backup mirror, but pin it to the same exact tag.
export const LOCAL_ENGINE_GITHUB_URL =
  `https://github.com/guodongbuding66-spec/galaxy-downloader/releases/download/${LOCAL_ENGINE_RELEASE_TAG}/GalaxyLocalEngine-Windows.zip`

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

function normalizeList(values?: string[]): string[] {
  if (!values?.length) return []
  const normalized: string[] = []
  for (const raw of values) {
    const value = String(raw || '').trim()
    if (!value || normalized.includes(value)) continue
    normalized.push(value)
    if (normalized.length >= 12) break
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
  params.set('archive', options.skipPreviouslyDownloaded ? '1' : '0')
  params.set('browser', options.browser || 'none')
  params.set('collection', collectionMode)
  if (collectionMode === 'selected') params.set('items', selectedItems.join(','))

  if (options.segmentStart) params.set('section_start', options.segmentStart)
  if (options.segmentEnd) params.set('section_end', options.segmentEnd)
  params.set('split_chapters', options.splitChapters ? '1' : '0')
  params.set('subtitle_mode', options.subtitleMode || 'both')
  const subtitleLanguages = normalizeList(options.subtitleLanguages)
  if (subtitleLanguages.length) params.set('subtitle_langs', subtitleLanguages.join(','))
  const audioLanguages = normalizeList(options.audioLanguages)
  if (audioLanguages.length) params.set('audio_langs', audioLanguages.join(','))
  if (options.sponsorBlockCategories?.length) {
    params.set('sponsorblock', options.sponsorBlockCategories.join(','))
  }
  params.set('aria2', options.useAria2c ? '1' : '0')

  // Preserve the legacy field so a protocol URL is still understandable by
  // pre-0.5 engines, while new engines use the explicit collection policy.
  params.set('playlist', collectionMode === 'all' ? '1' : '0')
  return `galaxy-downloader://download?${params.toString()}`
}

export function launchLocalDesktopEngine(options: LocalDesktopJobOptions): void {
  if (typeof window === 'undefined') return
  window.location.href = buildLocalDesktopEngineUri(options)
}
