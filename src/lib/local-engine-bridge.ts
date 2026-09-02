import {
  LOCAL_ENGINE_REQUIRED_VERSION,
  type LocalEngineAdvancedOptions,
  type LocalEngineBrowser,
  type LocalEngineCollectionMode,
} from '@/lib/local-engine'
import type { UnifiedParseResult } from '@/lib/types'

const LOCAL_ENGINE_BRIDGE_BASE_URLS = [
  'http://localhost:17836',
  'http://127.0.0.1:17836',
] as const

export const LOCAL_ENGINE_BRIDGE_BASE_URL = LOCAL_ENGINE_BRIDGE_BASE_URLS[0]
const LOCAL_ENGINE_REQUEST_TIMEOUT_MS = 1800
const MIN_PARSE_BRIDGE_PROTOCOL = 4
const MIN_RESUME_BRIDGE_PROTOCOL = 5
const LOCAL_ENGINE_BATCH_REQUEST_TIMEOUT_MS = 15_000
const MAX_VISIBLE_QUEUED_JOBS = 25
const MAX_VISIBLE_RESUME_JOBS = 25
const MAX_VISIBLE_BATCH_ISSUES = 2_000
const MAX_VISIBLE_BATCH_OUTCOMES = 500
const MAX_QUEUE_TEXT_LENGTH = 120
const MAX_BATCH_TEXT_LENGTH = 240
const QUEUE_JOB_ID_PATTERN = /^[a-zA-Z0-9]{1,128}$/

export interface LocalEngineQueuedJob {
  id: string
  position: number
  label: string
  sourceHost: string
}

export type LocalEngineResumeMode = 'continue' | 'restart'
export type LocalEngineResumeState = 'paused' | 'interrupted'

export interface LocalEngineResumeJob {
  id: string
  state: LocalEngineResumeState
  createdAt: string
  updatedAt: string
  sourceHost: string
  label: string
  videoQuality: string
  progress: number
  downloaded: string
  resumeMode: LocalEngineResumeMode
}

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
  advancedMedia?: boolean
  aria2Ready?: boolean
  queueLength: number
  queueCapacity: number
  queuedJobs: LocalEngineQueuedJob[]
  activeJobId: string | null
  canPause: boolean
  resumeJobs: LocalEngineResumeJob[]
  batchDownloadReady: boolean
}

export interface LocalEngineBridgeJob extends Partial<LocalEngineAdvancedOptions> {
  sourceUrl: string
  displayTitle?: string
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
  /** @deprecated Use collectionMode. */
  playlist?: boolean
}

export type LocalEngineBatchFormat = 'auto' | 'txt' | 'csv'
export type LocalEngineBatchResolvedFormat = 'txt' | 'csv'
export type LocalEngineBatchOptions = Omit<LocalEngineBridgeJob, 'sourceUrl' | 'displayTitle'>

export interface LocalEngineBatchRequest {
  input: string
  format?: LocalEngineBatchFormat
  options?: LocalEngineBatchOptions
}

export interface LocalEngineBatchIssue {
  row: number
  code: string
  message: string
}

export interface LocalEngineBatchOutcome {
  row: number
  accepted: boolean
  status: number
  code: string
}

export interface LocalEngineBatchSubmissionResult {
  ok: boolean
  httpStatus: number
  code: string
  format: LocalEngineBatchResolvedFormat
  inputCount: number
  inputIssueCount: number
  attemptedCount: number
  acceptedCount: number
  rejectedCount: number
  startedCount: number
  queuedCount: number
  remainingCount: number
  stoppedCode: string | null
  issues: LocalEngineBatchIssue[]
  outcomes: LocalEngineBatchOutcome[]
}

export type LocalEngineSubmissionCode =
  | 'BAD_REQUEST'
  | 'QUEUE_FULL'
  | 'QUEUE_ITEM_CANCELLED'
  | 'QUEUE_ITEM_NOT_FOUND'
  | 'QUEUE_CONTROL_UNAVAILABLE'
  | 'ENGINE_BUSY'
  | 'ENGINE_SHUTTING_DOWN'
  | 'ENGINE_HANDOFF_TIMEOUT'
  | 'NO_PAUSABLE_JOB'
  | 'RESUME_JOB_NOT_FOUND'
  | 'RESUME_JOB_ACTIVE'
  | 'RESUME_CONTROL_UNAVAILABLE'
  | 'BATCH_CONTROL_UNAVAILABLE'
  | 'CONTROL_REJECTED'
  | 'CONTROL_FAILED'
  | 'INTERNAL_ERROR'
  | string

export class LocalEngineBridgeSubmissionError extends Error {
  readonly code: LocalEngineSubmissionCode
  readonly status: number

  constructor(message: string, code: LocalEngineSubmissionCode, status: number) {
    super(message)
    this.name = 'LocalEngineBridgeSubmissionError'
    this.code = code
    this.status = status
  }
}

type SubmissionMessageCode = 'QUEUE_FULL' | 'ENGINE_BUSY' | 'ENGINE_SHUTTING_DOWN' | 'ENGINE_HANDOFF_TIMEOUT' | 'NO_PAUSABLE_JOB' | 'RESUME_JOB_NOT_FOUND' | 'RESUME_JOB_ACTIVE' | 'RESUME_CONTROL_UNAVAILABLE' | 'BATCH_CONTROL_UNAVAILABLE'
type SubmissionMessages = Partial<Record<SubmissionMessageCode, string>>

const SUBMISSION_MESSAGES: Record<string, SubmissionMessages> = {
  zh: {
    QUEUE_FULL: '本地下载队列已满，请等待前面的任务完成后再试。',
    ENGINE_BUSY: '本地引擎正在处理另一个任务，请稍后重试或升级到支持下载队列的版本。',
    ENGINE_SHUTTING_DOWN: 'Galaxy Local Engine 正在退出，请重新启动本地引擎后再提交任务。',
    ENGINE_HANDOFF_TIMEOUT: '本地引擎桌面窗口响应超时，请确认程序没有卡住，然后重试。',
    NO_PAUSABLE_JOB: '当前没有可以暂停的下载任务。',
    RESUME_JOB_NOT_FOUND: '这个可恢复任务已不存在，状态可能已被清理或在其他窗口中处理。',
    RESUME_JOB_ACTIVE: '该任务正在运行，不能在运行期间放弃恢复状态。',
    RESUME_CONTROL_UNAVAILABLE: '当前本地引擎不支持暂停/恢复控制，请升级到支持该功能的版本。',
    BATCH_CONTROL_UNAVAILABLE: '当前本地引擎不支持批量下载，请升级 Galaxy Local Engine 后重试。',
  },
  'zh-tw': {
    QUEUE_FULL: '本機下載佇列已滿，請等待前面的工作完成後再試。',
    ENGINE_BUSY: '本機引擎正在處理另一個工作，請稍後重試或升級至支援下載佇列的版本。',
    ENGINE_SHUTTING_DOWN: 'Galaxy Local Engine 正在結束，請重新啟動本機引擎後再提交工作。',
    ENGINE_HANDOFF_TIMEOUT: '本機引擎桌面視窗回應逾時，請確認程式沒有卡住後重試。',
  },
  ja: {
    QUEUE_FULL: 'ローカルのダウンロード待ちが上限です。前の処理が完了してから再試行してください。',
    ENGINE_BUSY: 'ローカルエンジンは別の処理を実行中です。後で再試行するか、キュー対応版へ更新してください。',
    ENGINE_SHUTTING_DOWN: 'Galaxy Local Engine は終了中です。再起動してからもう一度送信してください。',
    ENGINE_HANDOFF_TIMEOUT: 'ローカルエンジンの画面応答がタイムアウトしました。アプリが停止していないか確認して再試行してください。',
  },
  es: {
    QUEUE_FULL: 'La cola de descargas local está llena. Espera a que termine una tarea e inténtalo de nuevo.',
    ENGINE_BUSY: 'El motor local está procesando otra tarea. Inténtalo más tarde o actualiza a una versión con cola.',
    ENGINE_SHUTTING_DOWN: 'Galaxy Local Engine se está cerrando. Reinícialo antes de enviar otra tarea.',
    ENGINE_HANDOFF_TIMEOUT: 'La ventana del motor local no respondió a tiempo. Comprueba que la aplicación no esté bloqueada y vuelve a intentarlo.',
  },
  ru: {
    QUEUE_FULL: 'Локальная очередь загрузок заполнена. Дождитесь завершения одной из задач и повторите попытку.',
    ENGINE_BUSY: 'Локальный движок занят другой задачей. Повторите позже или обновите версию с поддержкой очереди.',
    ENGINE_SHUTTING_DOWN: 'Galaxy Local Engine завершает работу. Перезапустите его и отправьте задачу снова.',
    ENGINE_HANDOFF_TIMEOUT: 'Окно локального движка не ответило вовремя. Проверьте, что приложение не зависло, и повторите попытку.',
  },
  en: {
    QUEUE_FULL: 'The local download queue is full. Wait for a queued job to finish and try again.',
    ENGINE_BUSY: 'The local engine is processing another job. Retry later or upgrade to a queue-capable version.',
    ENGINE_SHUTTING_DOWN: 'Galaxy Local Engine is shutting down. Restart it before submitting another job.',
    ENGINE_HANDOFF_TIMEOUT: 'The Local Engine desktop window did not respond in time. Check that the app is responsive and retry.',
    NO_PAUSABLE_JOB: 'There is no active download that can be paused.',
    RESUME_JOB_NOT_FOUND: 'This recoverable download no longer exists.',
    RESUME_JOB_ACTIVE: 'The active download cannot discard its recovery state while it is running.',
    RESUME_CONTROL_UNAVAILABLE: 'This Local Engine does not support pause/resume controls. Please upgrade it.',
    BATCH_CONTROL_UNAVAILABLE: 'This Local Engine does not support batch downloads. Please upgrade it.',
  },
}

export function localizeLocalEngineSubmissionMessage(
  code: LocalEngineSubmissionCode,
  fallback: string,
  language?: string,
): string {
  const rawLanguage = (language || (typeof document === 'undefined' ? 'en' : document.documentElement.lang) || 'en').toLowerCase()
  const locale = rawLanguage.startsWith('zh-tw') || rawLanguage.startsWith('zh-hant')
    ? 'zh-tw'
    : rawLanguage.startsWith('zh')
      ? 'zh'
      : rawLanguage.startsWith('ja')
        ? 'ja'
        : rawLanguage.startsWith('es')
          ? 'es'
          : rawLanguage.startsWith('ru')
            ? 'ru'
            : 'en'
  const messages = SUBMISSION_MESSAGES[locale] || SUBMISSION_MESSAGES.en
  if (code in messages) return messages[code as keyof SubmissionMessages]
  return fallback
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

function compactQueueText(value: unknown): string {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, MAX_QUEUE_TEXT_LENGTH)
}

export function normalizeLocalEngineQueuedJobs(value: unknown): LocalEngineQueuedJob[] {
  if (!Array.isArray(value)) return []
  const normalized: LocalEngineQueuedJob[] = []
  const seen = new Set<string>()

  for (const raw of value.slice(0, MAX_VISIBLE_QUEUED_JOBS)) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const id = String(item.id || '').trim()
    if (!QUEUE_JOB_ID_PATTERN.test(id) || seen.has(id)) continue
    const position = Math.floor(Number(item.position || 0))
    if (!Number.isFinite(position) || position <= 0) continue
    const label = compactQueueText(item.label)
    const sourceHost = compactQueueText(item.sourceHost)
    if (!label && !sourceHost) continue
    seen.add(id)
    normalized.push({
      id,
      position,
      label: label || sourceHost,
      sourceHost,
    })
  }

  return normalized.sort((left, right) => left.position - right.position)
}

export function normalizeLocalEngineResumeJobs(value: unknown): LocalEngineResumeJob[] {
  if (!Array.isArray(value)) return []
  const normalized: LocalEngineResumeJob[] = []
  const seen = new Set<string>()

  for (const raw of value.slice(0, MAX_VISIBLE_RESUME_JOBS)) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const id = String(item.id || '').trim()
    if (!QUEUE_JOB_ID_PATTERN.test(id) || seen.has(id)) continue
    const state = String(item.state || '').toLowerCase()
    if (state !== 'paused' && state !== 'interrupted') continue
    const sourceHost = compactQueueText(item.sourceHost)
    const label = compactQueueText(item.label)
    if (!sourceHost && !label) continue
    const rawProgress = Number(item.progress || 0)
    const progress = Number.isFinite(rawProgress) ? Math.max(0, Math.min(100, rawProgress)) : 0
    const rawResumeMode = String(item.resumeMode || '').toLowerCase()
    const resumeMode: LocalEngineResumeMode = rawResumeMode === 'continue' ? 'continue' : 'restart'
    seen.add(id)
    normalized.push({
      id,
      state,
      createdAt: compactQueueText(item.createdAt),
      updatedAt: compactQueueText(item.updatedAt),
      sourceHost,
      label: label || sourceHost,
      videoQuality: compactQueueText(item.videoQuality) || 'best',
      progress,
      downloaded: compactQueueText(item.downloaded) || '—',
      resumeMode,
    })
  }

  return normalized
}


function compactBatchText(value: unknown): string {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, MAX_BATCH_TEXT_LENGTH)
}

function batchCount(value: unknown, maximum: number): number | null {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return null
  const rounded = Math.floor(numeric)
  if (rounded < 0 || rounded > maximum) return null
  return rounded
}

export function normalizeLocalEngineBatchSubmissionResult(
  value: unknown,
  httpStatus: number,
): LocalEngineBatchSubmissionResult | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Record<string, unknown>
  if (typeof payload.ok !== 'boolean') return null
  const code = compactBatchText(payload.code)
  const format = String(payload.format || '').toLowerCase()
  if (!code || (format !== 'txt' && format !== 'csv')) return null
  if (!Number.isInteger(httpStatus) || httpStatus < 100 || httpStatus > 599) return null

  const inputCount = batchCount(payload.inputCount, MAX_VISIBLE_BATCH_OUTCOMES)
  const inputIssueCount = batchCount(payload.inputIssueCount, MAX_VISIBLE_BATCH_ISSUES)
  const attemptedCount = batchCount(payload.attemptedCount, MAX_VISIBLE_BATCH_OUTCOMES)
  const acceptedCount = batchCount(payload.acceptedCount, MAX_VISIBLE_BATCH_OUTCOMES)
  const rejectedCount = batchCount(payload.rejectedCount, MAX_VISIBLE_BATCH_OUTCOMES)
  const startedCount = batchCount(payload.startedCount, MAX_VISIBLE_BATCH_OUTCOMES)
  const queuedCount = batchCount(payload.queuedCount, MAX_VISIBLE_BATCH_OUTCOMES)
  const remainingCount = batchCount(payload.remainingCount, MAX_VISIBLE_BATCH_OUTCOMES)
  if ([inputCount, inputIssueCount, attemptedCount, acceptedCount, rejectedCount, startedCount, queuedCount, remainingCount].some((item) => item === null)) {
    return null
  }

  const issues: LocalEngineBatchIssue[] = []
  if (!Array.isArray(payload.issues)) return null
  for (const raw of payload.issues.slice(0, MAX_VISIBLE_BATCH_ISSUES)) {
    if (!raw || typeof raw !== 'object') return null
    const issue = raw as Record<string, unknown>
    const row = batchCount(issue.row, MAX_VISIBLE_BATCH_ISSUES + 1)
    const issueCode = compactBatchText(issue.code)
    const message = compactBatchText(issue.message)
    if (row === null || !issueCode || !message) return null
    issues.push({ row, code: issueCode, message })
  }

  const outcomes: LocalEngineBatchOutcome[] = []
  if (!Array.isArray(payload.outcomes)) return null
  for (const raw of payload.outcomes.slice(0, MAX_VISIBLE_BATCH_OUTCOMES)) {
    if (!raw || typeof raw !== 'object') return null
    const outcome = raw as Record<string, unknown>
    const row = batchCount(outcome.row, MAX_VISIBLE_BATCH_ISSUES + 1)
    const status = batchCount(outcome.status, 599)
    const outcomeCode = compactBatchText(outcome.code)
    if (row === null || row <= 0 || status === null || status < 100 || !outcomeCode || typeof outcome.accepted !== 'boolean') return null
    outcomes.push({ row, accepted: outcome.accepted, status, code: outcomeCode })
  }

  const typedInputCount = inputCount as number
  const typedInputIssueCount = inputIssueCount as number
  const typedAttemptedCount = attemptedCount as number
  const typedAcceptedCount = acceptedCount as number
  const typedRejectedCount = rejectedCount as number
  const typedStartedCount = startedCount as number
  const typedQueuedCount = queuedCount as number
  const typedRemainingCount = remainingCount as number
  if (
    typedInputIssueCount !== issues.length
    || typedAttemptedCount !== outcomes.length
    || typedAcceptedCount !== outcomes.filter((item) => item.accepted).length
    || typedRejectedCount !== outcomes.filter((item) => !item.accepted).length
    || typedAcceptedCount + typedRejectedCount !== typedAttemptedCount
    || typedAttemptedCount + typedRemainingCount !== typedInputCount
    || typedStartedCount + typedQueuedCount > typedAcceptedCount
  ) return null

  const stoppedText = compactBatchText(payload.stoppedCode)
  return {
    ok: payload.ok,
    httpStatus,
    code,
    format: format as LocalEngineBatchResolvedFormat,
    inputCount: typedInputCount,
    inputIssueCount: typedInputIssueCount,
    attemptedCount: typedAttemptedCount,
    acceptedCount: typedAcceptedCount,
    rejectedCount: typedRejectedCount,
    startedCount: typedStartedCount,
    queuedCount: typedQueuedCount,
    remainingCount: typedRemainingCount,
    stoppedCode: stoppedText || null,
    issues,
    outcomes,
  }
}

export function normalizeLocalEngineBridgeStatusPayload(value: unknown): LocalEngineBridgeStatus | null {
  if (!value || typeof value !== 'object') return null
  const payload = value as Partial<LocalEngineBridgeStatus>
  if (!payload.ok || typeof payload.version !== 'string') return null

  const bridgeProtocol = Math.max(1, Math.floor(Number(payload.bridgeProtocol || 1)))
  const queueCapacity = Math.max(0, Math.floor(Number(payload.queueCapacity || 0)))
  const queuedJobs = normalizeLocalEngineQueuedJobs(payload.queuedJobs)
  const reportedQueueLength = Math.max(0, Math.floor(Number(payload.queueLength || 0)))
  const queueLength = Math.max(
    queuedJobs.length,
    Math.min(queueCapacity || Number.MAX_SAFE_INTEGER, reportedQueueLength),
  )
  const resumeJobs = normalizeLocalEngineResumeJobs(payload.resumeJobs)
  const rawActiveJobId = String(payload.activeJobId || '').trim()
  const activeJobId = QUEUE_JOB_ID_PATTERN.test(rawActiveJobId) ? rawActiveJobId : null

  return {
    ok: true,
    bridgeProtocol,
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
    advancedMedia: Boolean(payload.advancedMedia),
    aria2Ready: Boolean(payload.aria2Ready),
    queueLength,
    queueCapacity,
    queuedJobs,
    activeJobId,
    canPause: bridgeProtocol >= MIN_RESUME_BRIDGE_PROTOCOL && Boolean(payload.canPause),
    resumeJobs,
    batchDownloadReady: bridgeProtocol >= MIN_RESUME_BRIDGE_PROTOCOL && Boolean(payload.batchDownloadReady),
  }
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
    const payload = await response.json() as unknown
    const normalized = normalizeLocalEngineBridgeStatusPayload(payload)
    if (!normalized) {
      lastBridgeDiagnostic = 'Galaxy Local Engine 返回了无效状态，请重新启动本地引擎。'
      return null
    }
    if (!versionAtLeast(normalized.version, LOCAL_ENGINE_REQUIRED_VERSION)) {
      lastBridgeDiagnostic = `Galaxy Local Engine 版本过低（当前 ${normalized.version}，需要 ${LOCAL_ENGINE_REQUIRED_VERSION}+）。请下载最新版并重新运行 install.cmd。`
      return null
    }

    lastBridgeDiagnostic = null
    return normalized
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
      if (code === 'AUTH_REQUIRED') continue

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

async function postBridgeAction(path: string, body?: unknown, timeoutMs = 2500): Promise<Response> {
  return bridgeFetch(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }, timeoutMs)
}

async function parseStructuredActionResponse(
  response: Response,
  fallbackMessage: string,
  fallbackCode: LocalEngineSubmissionCode,
): Promise<{ message: string; code: LocalEngineSubmissionCode }> {
  let message = fallbackMessage
  let code = fallbackCode
  try {
    const payload = await response.json() as { message?: string; error?: string; code?: string }
    message = payload.message || payload.error || message
    code = payload.code || code
  } catch {
    // Preserve status-based fallback values for older or malformed engines.
  }
  return { message, code }
}

export async function submitLocalEngineBatchInput(
  request: LocalEngineBatchRequest,
): Promise<LocalEngineBatchSubmissionResult> {
  if (!request || typeof request.input !== 'string') {
    throw new LocalEngineBridgeSubmissionError('Batch input must be a string', 'BAD_REQUEST', 400)
  }
  const format = request.format || 'auto'
  if (!['auto', 'txt', 'csv'].includes(format)) {
    throw new LocalEngineBridgeSubmissionError('Batch format must be auto, txt or csv', 'BAD_REQUEST', 400)
  }

  const status = await getLocalEngineBridgeStatus()
  if (!status) {
    throw new Error(lastBridgeDiagnostic || `Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ is required`)
  }
  if (!status.batchDownloadReady) {
    const code: LocalEngineSubmissionCode = 'BATCH_CONTROL_UNAVAILABLE'
    throw new LocalEngineBridgeSubmissionError(
      localizeLocalEngineSubmissionMessage(code, 'This Local Engine does not support batch downloads'),
      code,
      501,
    )
  }

  const response = await postBridgeAction(
    '/batch/download',
    {
      input: request.input,
      format,
      options: request.options || {},
    },
    LOCAL_ENGINE_BATCH_REQUEST_TIMEOUT_MS,
  )

  let rawPayload: unknown = null
  try {
    rawPayload = await response.json()
  } catch {
    // Malformed bridge response is handled below as a typed internal error.
  }
  const normalized = normalizeLocalEngineBatchSubmissionResult(rawPayload, response.status)
  if (normalized) return normalized

  let code: LocalEngineSubmissionCode = response.status === 404
    ? 'BATCH_CONTROL_UNAVAILABLE'
    : 'INTERNAL_ERROR'
  let message = response.ok
    ? 'Local Engine returned an invalid batch response'
    : `Local Engine rejected the batch (${response.status})`
  if (rawPayload && typeof rawPayload === 'object') {
    const payload = rawPayload as Record<string, unknown>
    const rawCode = compactBatchText(payload.code)
    const rawMessage = compactBatchText(payload.message || payload.error)
    if (rawCode) code = rawCode
    if (rawMessage) message = rawMessage
  }
  throw new LocalEngineBridgeSubmissionError(
    localizeLocalEngineSubmissionMessage(code, message),
    code,
    response.ok ? 502 : response.status,
  )
}

export async function submitLocalEngineBridgeJob(job: LocalEngineBridgeJob): Promise<string> {
  const status = await getLocalEngineBridgeStatus()
  if (!status) {
    throw new Error(lastBridgeDiagnostic || `Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ is required`)
  }
  if (status.bridgeProtocol < MIN_PARSE_BRIDGE_PROTOCOL) {
    throw new Error(`Galaxy Local Engine bridge protocol ${MIN_PARSE_BRIDGE_PROTOCOL}+ is required`)
  }

  const response = await postBridgeAction('/download', job)
  const fallbackMessage = response.ok ? 'Download job accepted' : `Local engine rejected the job (${response.status})`
  const fallbackCode: LocalEngineSubmissionCode = response.ok ? 'ACCEPTED' : 'ENGINE_BUSY'
  const { message, code } = await parseStructuredActionResponse(response, fallbackMessage, fallbackCode)
  if (response.ok) return message
  throw new LocalEngineBridgeSubmissionError(
    localizeLocalEngineSubmissionMessage(code, message),
    code,
    response.status,
  )
}

export async function cancelLocalEngineQueuedJob(jobId: string): Promise<void> {
  const normalizedJobId = jobId.trim()
  if (!QUEUE_JOB_ID_PATTERN.test(normalizedJobId)) {
    throw new LocalEngineBridgeSubmissionError('Invalid queued job id', 'BAD_REQUEST', 400)
  }
  const response = await postBridgeAction('/queue/cancel', { jobId: normalizedJobId })
  const { message, code } = await parseStructuredActionResponse(
    response,
    response.ok ? 'Queued download cancelled' : `Could not cancel queued download (${response.status})`,
    response.ok ? 'QUEUE_ITEM_CANCELLED' : 'QUEUE_ITEM_NOT_FOUND',
  )
  if (response.ok) return
  throw new LocalEngineBridgeSubmissionError(
    localizeLocalEngineSubmissionMessage(code, message),
    code,
    response.status,
  )
}

async function requireResumeBridge(): Promise<LocalEngineBridgeStatus> {
  const status = await getLocalEngineBridgeStatus()
  if (!status) {
    throw new Error(lastBridgeDiagnostic || `Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ is required`)
  }
  if (status.bridgeProtocol < MIN_RESUME_BRIDGE_PROTOCOL) {
    throw new LocalEngineBridgeSubmissionError(
      'This Local Engine version does not support pause/resume controls',
      'RESUME_CONTROL_UNAVAILABLE',
      501,
    )
  }
  return status
}

async function runResumeControl(
  path: string,
  body: unknown | undefined,
  successFallback: string,
  successCode: LocalEngineSubmissionCode,
  failureFallback: string,
  failureCode: LocalEngineSubmissionCode,
): Promise<string> {
  const response = await postBridgeAction(path, body)
  const { message, code } = await parseStructuredActionResponse(
    response,
    response.ok ? successFallback : failureFallback,
    response.ok ? successCode : failureCode,
  )
  if (response.ok) return message
  throw new LocalEngineBridgeSubmissionError(
    localizeLocalEngineSubmissionMessage(code, message),
    code,
    response.status,
  )
}

export async function pauseLocalEngineBridgeJob(): Promise<string> {
  const status = await requireResumeBridge()
  if (!status.busy || !status.canPause) {
    throw new LocalEngineBridgeSubmissionError(
      localizeLocalEngineSubmissionMessage('NO_PAUSABLE_JOB', 'There is no active download that can be paused'),
      'NO_PAUSABLE_JOB',
      409,
    )
  }
  return runResumeControl(
    '/pause',
    undefined,
    'Active download is stopping at a resumable checkpoint',
    'PAUSE_REQUESTED',
    'Could not pause the active download',
    'NO_PAUSABLE_JOB',
  )
}

export async function resumeLocalEngineBridgeJob(jobId: string): Promise<string> {
  const normalizedJobId = jobId.trim()
  if (!QUEUE_JOB_ID_PATTERN.test(normalizedJobId)) {
    throw new LocalEngineBridgeSubmissionError('Invalid recoverable job id', 'BAD_REQUEST', 400)
  }
  const status = await requireResumeBridge()
  if (status.busy) {
    throw new LocalEngineBridgeSubmissionError(
      localizeLocalEngineSubmissionMessage('ENGINE_BUSY', 'Another download is already active'),
      'ENGINE_BUSY',
      409,
    )
  }
  return runResumeControl(
    '/resume',
    { jobId: normalizedJobId },
    'Recoverable download has been started',
    'RESUME_STARTED',
    'Could not resume the download',
    'RESUME_JOB_NOT_FOUND',
  )
}

export async function discardLocalEngineResumeJob(jobId: string): Promise<string> {
  const normalizedJobId = jobId.trim()
  if (!QUEUE_JOB_ID_PATTERN.test(normalizedJobId)) {
    throw new LocalEngineBridgeSubmissionError('Invalid recoverable job id', 'BAD_REQUEST', 400)
  }
  await requireResumeBridge()
  return runResumeControl(
    '/resume/discard',
    { jobId: normalizedJobId },
    'Recoverable download state was discarded',
    'RESUME_JOB_DISCARDED',
    'Could not discard the recoverable download',
    'RESUME_JOB_NOT_FOUND',
  )
}


export async function cancelLocalEngineBridgeJob(): Promise<void> {
  const response = await postBridgeAction('/cancel')
  if (!response.ok) throw new Error(`Local engine cancel failed (${response.status})`)
}

export async function openLocalEngineDownloadFolder(): Promise<void> {
  const response = await postBridgeAction('/open-folder')
  if (!response.ok) throw new Error(`Could not open local download folder (${response.status})`)
}