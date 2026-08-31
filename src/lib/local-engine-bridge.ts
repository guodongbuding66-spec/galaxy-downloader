import type { LocalEngineBrowser } from '@/lib/local-engine'

export const LOCAL_ENGINE_BRIDGE_BASE_URL = 'http://127.0.0.1:17836'
const LOCAL_ENGINE_REQUEST_TIMEOUT_MS = 1400
const MIN_LOCAL_ENGINE_VERSION = '0.4.3'

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
  playlist?: boolean
}

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

async function bridgeFetch(
  path: string,
  init?: RequestInit,
  timeoutMs = LOCAL_ENGINE_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(`${LOCAL_ENGINE_BRIDGE_BASE_URL}${path}`, {
      cache: 'no-store',
      ...init,
      signal: controller.signal,
    })
  } finally {
    window.clearTimeout(timeoutId)
  }
}

export async function getLocalEngineBridgeStatus(): Promise<LocalEngineBridgeStatus | null> {
  try {
    const response = await bridgeFetch('/status')
    if (!response.ok) return null
    const payload = await response.json() as Partial<LocalEngineBridgeStatus>
    if (!payload.ok || typeof payload.version !== 'string') return null

    // Older bridge versions may still answer localhost, but are intentionally
    // treated as incompatible when the current website depends on newer runtime
    // behavior (for example reliable yt-dlp progress reporting in v0.4.3).
    if (!versionAtLeast(payload.version, MIN_LOCAL_ENGINE_VERSION)) return null

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
  } catch {
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
    throw new Error(`Galaxy Local Engine ${MIN_LOCAL_ENGINE_VERSION}+ is required`)
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
