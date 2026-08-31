import type { LocalEngineBrowser, LocalEngineCollectionMode } from '@/lib/local-engine'
import type { UnifiedParseResult } from '@/lib/types'

const LOCAL_ENGINE_BRIDGE_BASE_URLS = [
  'http://localhost:17836',
  'http://127.0.0.1:17836',
] as const

export const LOCAL_ENGINE_BRIDGE_BASE_URL = LOCAL_ENGINE_BRIDGE_BASE_URLS[0]
const LOCAL_ENGINE_REQUEST_TIMEOUT_MS = 1800
const MIN_LOCAL_ENGINE_VERSION = '0.5.0'
const MIN_PARSE_BRIDGE_PROTOCOL = 4

export interface LocalEngineBridgeStatus {
  ok: boolean
  bridgeProtocol: number
  version: string
  state: string
  status: string
  detail: string
  busy: boolean
  progress: number
  speed: string
  eta: string
  downloaded: string
  ffmpegReady: boolean
  ytDlpReady: boolean
}

export interface LocalEngineBridgeJob {
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
  /** @deprecated Use collectionMode. */
  playlist?: boolean
}

type LoopbackRequestInit = RequestInit & {
  targetAddressSpace?: 'loopback'
}

let preferredBridgeBaseUrl: string | null = null
let lastBridgeDiagnostic: string | null = null

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
    if (current[index] > required[index]) return true
    if (current[index] < required[index]) return false
  }
  return true
}

function detectBrowserForCookies(): LocalEngineBrowser {
  if (typeof navigator === 'undefined') return 'none'
  const userAgent = navigator.userAgent.toLowerCase()
  if (userAgent.includes('edg/')) return 'edge'
  if (userAgent.includes('firefox/')) return 'firefox'
  if (userAgent.includes('chrome/') || userAgent.includes('crios/')) return 'chrome'
  return 'none'
}

function parseBrowserCandidates(): LocalEngineBrowser[] {
  const current = detectBrowserForCookies()
  const candidates: LocalEngineBrowser[] = [current, 'edge', 'chrome', 'firefox']
  return [...new Set(candidates)].filter((value) => value !== 'none') as LocalEngineBrowser[]
}

function errorText(error: unknown): string {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return '连接本地引擎超时。请确认 Galaxy Local Engine 正在运行。'
  }
  if (error instanceof Error && error.message.trim()) return error.message
  return '浏览器无法连接本地引擎。'
}

function localNetworkHelp(detail?: string): string {
  const suffix = detail?.trim() ? `（${detail.trim()}）` : ''
  return `无法访问 Galaxy Local Engine${suffix}。请确认本地引擎正在运行，并在浏览器的网站权限中允许“本地网络访问/Local network access”，然后重新点击解析。`
}

function candidateBaseUrls(): string[] {
  const candidates = preferredBridgeBaseUrl
    ? [preferredBridgeBaseUrl, ...LOCAL_ENGINE_BRIDGE_BASE_URLS]
    : [...LOCAL_ENGINE_BRIDGE_BASE_URLS]
  return [...new Set(candidates)]
}

async function bridgeFetch(
  path: string,
  init?: RequestInit,
  timeoutMs = LOCAL_ENGINE_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  let lastError: unknown = null

  for (const baseUrl of candidateBaseUrls()) {
    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
    try {
      const requestInit: LoopbackRequestInit = {
        cache: 'no-store',
        ...init,
        signal: controller.signal,
        targetAddressSpace: 'loopback',
      }
      const response = await fetch(`${baseUrl}${path}`, requestInit)
      preferredBridgeBaseUrl = baseUrl
      return response
    } catch (error) {
      lastError = error
    } finally {
      window.clearTimeout(timeoutId)
    }
  }

  throw lastError instanceof Error ? lastError : new Error('Local engine bridge is unreachable')
}

export function getLastLocalEngineBridgeDiagnostic(): string | null {
  return lastBridgeDiagnostic
}

export async function getLocalEngineBridgeStatus(): Promise<LocalEngineBridgeStatus | null> {
  try {
    const response = await bridgeFetch('/status')
    if (!response.ok) {
      lastBridgeDiagnostic = response.status === 403
        ? 'Galaxy Local Engine 拒绝了当前网站来源。请升级本地引擎或重新运行 install.cmd。'
        : localNetworkHelp(`HTTP ${response.status}`)
      return null
    }
    const payload = await response.json() as Partial<LocalEngineBridgeStatus>
    if (!payload.ok || typeof payload.version !== 'string') {
      lastBridgeDiagnostic = 'Galaxy Local Engine 返回了无效状态，请重新启动本地引擎。'
      return null
    }
    if (!versionAtLeast(payload.version, MIN_LOCAL_ENGINE_VERSION)) {
      lastBridgeDiagnostic = `Galaxy Local Engine 版本过低（当前 ${payload.version}，需要 ${MIN_LOCAL_ENGINE_VERSION}+）。请下载最新版并重新运行 install.cmd。`
      return null
    }

    lastBridgeDiagnostic = null
    return {
      ok: true,
      bridgeProtocol: Number(payload.bridgeProtocol || 1),
      version: payload.version,
      state: String(payload.state || 'ready'),
      status: String(payload.status || 'Ready'),
      detail: String(payload.detail || ''),
      busy: Boolean(payload.busy),
      progress: Math.max(0, Math.min(100, Number(payload.progress || 0))),
      speed: String(payload.speed || '—'),
      eta: String(payload.eta || '—'),
      downloaded: String(payload.downloaded || '—'),
      ffmpegReady: Boolean(payload.ffmpegReady),
      ytDlpReady: Boolean(payload.ytDlpReady),
    }
  } catch (error) {
    lastBridgeDiagnostic = localNetworkHelp(errorText(error))
    return null
  }
}

async function parseWithBrowser(sourceUrl: string, browser: LocalEngineBrowser): Promise<{
  payload: UnifiedParseResult | null
  response: Response
}> {
  const response = await bridgeFetch('/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: sourceUrl, browser }),
  }, 48_000)

  let payload: UnifiedParseResult | null = null
  try {
    payload = await response.json() as UnifiedParseResult
  } catch {
    // Preserve null; caller will report the HTTP failure.
  }
  return { payload, response }
}

function parseFailureDetail(payload: UnifiedParseResult | null, response: Response): string {
  return payload?.error || payload?.message || `HTTP ${response.status}`
}

function browserCookieDatabaseFailure(detail: string): boolean {
  const normalized = detail.toLowerCase()
  const patterns = [
    'browser_cookie_unavailable',
    'could not copy chrome cookie database',
    'could not copy edge cookie database',
    'could not copy firefox cookie database',
    'cookie database is locked',
    'database is locked',
    'failed to decrypt with dpapi',
    'failed to decrypt cookie',
    'no such table: meta',
    'no such table: cookies',
    'sqlite3.operationalerror',
  ]
  return patterns.some((pattern) => normalized.includes(pattern))
}

export async function parseWithLocalEngine(sourceUrl: string): Promise<UnifiedParseResult | null> {
  try {
    const status = await getLocalEngineBridgeStatus()
    if (!status) return null
    if (status.bridgeProtocol < MIN_PARSE_BRIDGE_PROTOCOL) {
      lastBridgeDiagnostic = `本地引擎解析协议过低（当前 ${status.bridgeProtocol}，需要 ${MIN_PARSE_BRIDGE_PROTOCOL}+）。请升级 Galaxy Local Engine。`
      return null
    }
    if (!status.ytDlpReady) {
      lastBridgeDiagnostic = '本地引擎中的 yt-dlp 尚未就绪，请重新启动 Galaxy Local Engine。'
      return null
    }

    // Always make one explicit public/no-cookie request first. Browser login
    // state is a fallback, never the default parsing path.
    const publicAttempt = await parseWithBrowser(sourceUrl, 'none')
    if (publicAttempt.response.ok && publicAttempt.payload?.success && publicAttempt.payload.data) {
      lastBridgeDiagnostic = null
      return publicAttempt.payload
    }

    const publicCode = String(publicAttempt.payload?.code || '')
    const publicDetail = parseFailureDetail(publicAttempt.payload, publicAttempt.response)
    if (publicCode !== 'AUTH_REQUIRED') {
      lastBridgeDiagnostic = publicDetail
      return null
    }

    const browsers = parseBrowserCandidates()
    let lastAuthDetail = publicDetail
    let cookieFailureSeen = false

    // Only an explicit AUTH_REQUIRED response is allowed to enter the browser
    // cookie path. Broken/locked SQLite cookie databases are skipped quietly so
    // one bad browser profile cannot replace the real media-parser result.
    for (const browser of browsers) {
      const { payload, response } = await parseWithBrowser(sourceUrl, browser)
      if (response.ok && payload?.success && payload.data) {
        lastBridgeDiagnostic = null
        return payload
      }

      const code = String(payload?.code || '')
      const detail = parseFailureDetail(payload, response)
      lastAuthDetail = detail

      if (code === 'BROWSER_COOKIE_UNAVAILABLE' || browserCookieDatabaseFailure(`${code} ${detail}`)) {
        cookieFailureSeen = true
        continue
      }

      if (code === 'AUTH_REQUIRED') {
        continue
      }

      // Once authentication was explicitly requested, a non-auth parser error
      // from one browser is meaningful and should not be hidden by another
      // unrelated browser profile.
      lastBridgeDiagnostic = detail
      return null
    }

    lastBridgeDiagnostic = cookieFailureSeen
      ? '该内容需要登录状态，但当前可用浏览器的登录 Cookie 无法安全读取。请在一个浏览器中登录目标平台；如该浏览器正在占用 Cookie 数据库，可完全退出后重试。'
      : lastAuthDetail
    return null
  } catch (error) {
    lastBridgeDiagnostic = localNetworkHelp(errorText(error))
    return null
  }
}

async function postBridgeAction(path: string, body?: unknown): Promise<Response> {
  return bridgeFetch(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }, 2500)
}

export async function submitLocalEngineBridgeJob(job: LocalEngineBridgeJob): Promise<void> {
  const status = await getLocalEngineBridgeStatus()
  if (!status) {
    throw new Error(lastBridgeDiagnostic || `Galaxy Local Engine ${MIN_LOCAL_ENGINE_VERSION}+ is required`)
  }
  if (status.bridgeProtocol < MIN_PARSE_BRIDGE_PROTOCOL) {
    throw new Error(`Galaxy Local Engine bridge protocol ${MIN_PARSE_BRIDGE_PROTOCOL}+ is required`)
  }

  const response = await postBridgeAction('/download', job)
  if (response.ok) return
  let message = `Local engine rejected the job (${response.status})`
  try {
    const payload = await response.json() as { message?: string; error?: string }
    message = payload.message || payload.error || message
  } catch {
    // Keep the status-based message.
  }
  throw new Error(message)
}

export async function cancelLocalEngineBridgeJob(): Promise<void> {
  const response = await postBridgeAction('/cancel')
  if (!response.ok) throw new Error(`Local engine cancel failed (${response.status})`)
}

export async function openLocalEngineDownloadFolder(): Promise<void> {
  const response = await postBridgeAction('/open-folder')
  if (!response.ok) throw new Error(`Could not open local download folder (${response.status})`)
}
