from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


bridge = ROOT / "src" / "lib" / "local-engine-bridge.ts"
replace_once(
    bridge,
    '''const MIN_RESUME_BRIDGE_PROTOCOL = 5
const MAX_VISIBLE_QUEUED_JOBS = 25
const MAX_VISIBLE_RESUME_JOBS = 25
const MAX_QUEUE_TEXT_LENGTH = 120
''',
    '''const MIN_RESUME_BRIDGE_PROTOCOL = 5
const LOCAL_ENGINE_BATCH_REQUEST_TIMEOUT_MS = 15_000
const MAX_VISIBLE_QUEUED_JOBS = 25
const MAX_VISIBLE_RESUME_JOBS = 25
const MAX_VISIBLE_BATCH_ISSUES = 2_000
const MAX_VISIBLE_BATCH_OUTCOMES = 500
const MAX_QUEUE_TEXT_LENGTH = 120
const MAX_BATCH_TEXT_LENGTH = 240
''',
)
replace_once(
    bridge,
    '''  canPause: boolean
  resumeJobs: LocalEngineResumeJob[]
}
''',
    '''  canPause: boolean
  resumeJobs: LocalEngineResumeJob[]
  batchDownloadReady: boolean
}
''',
)
replace_once(
    bridge,
    '''export interface LocalEngineBridgeJob {
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
''',
    '''export interface LocalEngineBridgeJob {
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
''',
)
replace_once(
    bridge,
    '''  | 'RESUME_CONTROL_UNAVAILABLE'
  | 'CONTROL_REJECTED'
''',
    '''  | 'RESUME_CONTROL_UNAVAILABLE'
  | 'BATCH_CONTROL_UNAVAILABLE'
  | 'CONTROL_REJECTED'
''',
)
replace_once(
    bridge,
    '''type SubmissionMessageCode = 'QUEUE_FULL' | 'ENGINE_BUSY' | 'ENGINE_SHUTTING_DOWN' | 'ENGINE_HANDOFF_TIMEOUT' | 'NO_PAUSABLE_JOB' | 'RESUME_JOB_NOT_FOUND' | 'RESUME_JOB_ACTIVE' | 'RESUME_CONTROL_UNAVAILABLE'
''',
    '''type SubmissionMessageCode = 'QUEUE_FULL' | 'ENGINE_BUSY' | 'ENGINE_SHUTTING_DOWN' | 'ENGINE_HANDOFF_TIMEOUT' | 'NO_PAUSABLE_JOB' | 'RESUME_JOB_NOT_FOUND' | 'RESUME_JOB_ACTIVE' | 'RESUME_CONTROL_UNAVAILABLE' | 'BATCH_CONTROL_UNAVAILABLE'
''',
)
replace_once(
    bridge,
    '''    RESUME_CONTROL_UNAVAILABLE: '当前本地引擎不支持暂停/恢复控制，请升级到支持该功能的版本。',
''',
    '''    RESUME_CONTROL_UNAVAILABLE: '当前本地引擎不支持暂停/恢复控制，请升级到支持该功能的版本。',
    BATCH_CONTROL_UNAVAILABLE: '当前本地引擎不支持批量下载，请升级 Galaxy Local Engine 后重试。',
''',
)
replace_once(
    bridge,
    '''    RESUME_CONTROL_UNAVAILABLE: 'This Local Engine does not support pause/resume controls. Please upgrade it.',
''',
    '''    RESUME_CONTROL_UNAVAILABLE: 'This Local Engine does not support pause/resume controls. Please upgrade it.',
    BATCH_CONTROL_UNAVAILABLE: 'This Local Engine does not support batch downloads. Please upgrade it.',
''',
)

status_block = '''export function getLastLocalEngineBridgeDiagnostic(): string | null {
  return lastBridgeDiagnostic
}

export async function getLocalEngineBridgeStatus(): Promise<LocalEngineBridgeStatus | null> {
'''
status_helpers = '''function compactBatchText(value: unknown): string {
  return String(value || '').replace(/\\s+/g, ' ').trim().slice(0, MAX_BATCH_TEXT_LENGTH)
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
'''
replace_once(bridge, status_block, status_helpers)

old_status_body = '''    const payload = await response.json() as Partial<LocalEngineBridgeStatus>
    if (!payload.ok || typeof payload.version !== 'string') {
      lastBridgeDiagnostic = 'Galaxy Local Engine 返回了无效状态，请重新启动本地引擎。'
      return null
    }
    if (!versionAtLeast(payload.version, LOCAL_ENGINE_REQUIRED_VERSION)) {
      lastBridgeDiagnostic = `Galaxy Local Engine 版本过低（当前 ${payload.version}，需要 ${LOCAL_ENGINE_REQUIRED_VERSION}+）。请下载最新版并重新运行 install.cmd。`
      return null
    }

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
      queueLength,
      queueCapacity,
      queuedJobs,
      activeJobId,
      canPause: Number(payload.bridgeProtocol || 1) >= MIN_RESUME_BRIDGE_PROTOCOL && Boolean(payload.canPause),
      resumeJobs,
    }
'''
new_status_body = '''    const payload = await response.json() as unknown
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
'''
replace_once(bridge, old_status_body, new_status_body)

replace_once(
    bridge,
    '''async function postBridgeAction(path: string, body?: unknown): Promise<Response> {
  return bridgeFetch(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }, 2500)
}
''',
    '''async function postBridgeAction(path: string, body?: unknown, timeoutMs = 2500): Promise<Response> {
  return bridgeFetch(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }, timeoutMs)
}
''',
)

submit_anchor = '''export async function submitLocalEngineBridgeJob(job: LocalEngineBridgeJob): Promise<string> {
'''
batch_submit = '''export async function submitLocalEngineBatchInput(
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
'''
replace_once(bridge, submit_anchor, batch_submit)

resume = ROOT / "local-engine" / "resume_bridge.py"
replace_once(
    resume,
    '                self._json(200, {"ok": True, "bridgeProtocol": RESUME_BRIDGE_PROTOCOL_VERSION, **payload})\n',
    '                self._json(200, {"ok": True, "bridgeProtocol": RESUME_BRIDGE_PROTOCOL_VERSION, **payload, "batchDownloadReady": callable(local_bridge._submit_batch_jobs)})\n',
)

http_test = ROOT / "scripts" / "test-local-bridge-submission.py"
replace_once(
    http_test,
    '''    def test_batch_controller_is_discovered_from_bound_owner(self):
        self.assertIsNotNone(self.bridge._submit_batch_jobs)
''',
    '''    def test_batch_controller_is_discovered_from_bound_owner(self):
        self.assertIsNotNone(self.bridge._submit_batch_jobs)

    def test_status_advertises_batch_capability_from_bound_owner(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/status", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["bridgeProtocol"], 5)
        self.assertTrue(payload["batchDownloadReady"])
''',
)

print("web batch bridge client integration applied")
