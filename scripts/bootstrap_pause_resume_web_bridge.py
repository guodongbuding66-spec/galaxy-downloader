from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one {label} target, got {count}: {old[:140]!r}")
    return text.replace(old, new, 1)


def patch_python_bridge() -> None:
    path = Path("local-engine/resume_bridge.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import bridge as base_bridge\nfrom bridge_submission_policy import StructuredLocalBridge, normalize_submission_result\n",
        "import bridge as base_bridge\nfrom bridge_submission_policy import StructuredLocalBridge, normalize_submission_result\n\nRESUME_BRIDGE_PROTOCOL_VERSION = 5\n",
        "resume bridge protocol constant",
    )
    text = replace_once(
        text,
        'self._json(200, {"ok": True, "bridgeProtocol": base_bridge.BRIDGE_PROTOCOL_VERSION, **payload})',
        'self._json(200, {"ok": True, "bridgeProtocol": RESUME_BRIDGE_PROTOCOL_VERSION, **payload})',
        "resume bridge status protocol",
    )
    text = replace_once(
        text,
        "    owner = Owner()\n",
        "    assert RESUME_BRIDGE_PROTOCOL_VERSION > base_bridge.BRIDGE_PROTOCOL_VERSION\n    owner = Owner()\n",
        "resume bridge protocol self test",
    )
    path.write_text(text, encoding="utf-8")


def patch_typescript_bridge() -> None:
    path = Path("src/lib/local-engine-bridge.ts")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "const MIN_PARSE_BRIDGE_PROTOCOL = 4\nconst MAX_VISIBLE_QUEUED_JOBS = 25\n",
        "const MIN_PARSE_BRIDGE_PROTOCOL = 4\nconst MIN_RESUME_BRIDGE_PROTOCOL = 5\nconst MAX_VISIBLE_QUEUED_JOBS = 25\nconst MAX_VISIBLE_RESUME_JOBS = 25\n",
        "bridge protocol constants",
    )

    text = replace_once(
        text,
        '''export interface LocalEngineQueuedJob {
  id: string
  position: number
  label: string
  sourceHost: string
}

export interface LocalEngineBridgeStatus {
''',
        '''export interface LocalEngineQueuedJob {
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
''',
        "resume bridge types",
    )

    text = replace_once(
        text,
        '''  queueLength: number
  queueCapacity: number
  queuedJobs: LocalEngineQueuedJob[]
}
''',
        '''  queueLength: number
  queueCapacity: number
  queuedJobs: LocalEngineQueuedJob[]
  activeJobId: string | null
  canPause: boolean
  resumeJobs: LocalEngineResumeJob[]
}
''',
        "status resume fields",
    )

    text = replace_once(
        text,
        '''  | 'ENGINE_HANDOFF_TIMEOUT'
  | 'INTERNAL_ERROR'
''',
        '''  | 'ENGINE_HANDOFF_TIMEOUT'
  | 'NO_PAUSABLE_JOB'
  | 'RESUME_JOB_NOT_FOUND'
  | 'RESUME_JOB_ACTIVE'
  | 'RESUME_CONTROL_UNAVAILABLE'
  | 'CONTROL_REJECTED'
  | 'CONTROL_FAILED'
  | 'INTERNAL_ERROR'
''',
        "resume control codes",
    )

    text = replace_once(
        text,
        "type SubmissionMessages = Record<'QUEUE_FULL' | 'ENGINE_BUSY' | 'ENGINE_SHUTTING_DOWN' | 'ENGINE_HANDOFF_TIMEOUT', string>\n",
        "type SubmissionMessageCode = 'QUEUE_FULL' | 'ENGINE_BUSY' | 'ENGINE_SHUTTING_DOWN' | 'ENGINE_HANDOFF_TIMEOUT' | 'NO_PAUSABLE_JOB' | 'RESUME_JOB_NOT_FOUND' | 'RESUME_JOB_ACTIVE' | 'RESUME_CONTROL_UNAVAILABLE'\n"
        "type SubmissionMessages = Partial<Record<SubmissionMessageCode, string>>\n",
        "submission message type",
    )

    text = replace_once(
        text,
        '''    ENGINE_HANDOFF_TIMEOUT: '本地引擎桌面窗口响应超时，请确认程序没有卡住，然后重试。',
  },
''',
        '''    ENGINE_HANDOFF_TIMEOUT: '本地引擎桌面窗口响应超时，请确认程序没有卡住，然后重试。',
    NO_PAUSABLE_JOB: '当前没有可以暂停的下载任务。',
    RESUME_JOB_NOT_FOUND: '这个可恢复任务已不存在，状态可能已被清理或在其他窗口中处理。',
    RESUME_JOB_ACTIVE: '该任务正在运行，不能在运行期间放弃恢复状态。',
    RESUME_CONTROL_UNAVAILABLE: '当前本地引擎不支持暂停/恢复控制，请升级到支持该功能的版本。',
  },
''',
        "zh resume messages",
    )

    text = replace_once(
        text,
        '''    ENGINE_HANDOFF_TIMEOUT: 'The Local Engine desktop window did not respond in time. Check that the app is responsive and retry.',
  },
''',
        '''    ENGINE_HANDOFF_TIMEOUT: 'The Local Engine desktop window did not respond in time. Check that the app is responsive and retry.',
    NO_PAUSABLE_JOB: 'There is no active download that can be paused.',
    RESUME_JOB_NOT_FOUND: 'This recoverable download no longer exists.',
    RESUME_JOB_ACTIVE: 'The active download cannot discard its recovery state while it is running.',
    RESUME_CONTROL_UNAVAILABLE: 'This Local Engine does not support pause/resume controls. Please upgrade it.',
  },
''',
        "en resume messages",
    )

    normalization = '''

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
'''
    text = replace_once(
        text,
        "\n\nexport function getLastLocalEngineBridgeDiagnostic(): string | null {\n",
        normalization + "\n\nexport function getLastLocalEngineBridgeDiagnostic(): string | null {\n",
        "resume normalization",
    )

    text = replace_once(
        text,
        '''    const queueLength = Math.max(
      queuedJobs.length,
      Math.min(queueCapacity || Number.MAX_SAFE_INTEGER, reportedQueueLength),
    )

    lastBridgeDiagnostic = null
''',
        '''    const queueLength = Math.max(
      queuedJobs.length,
      Math.min(queueCapacity || Number.MAX_SAFE_INTEGER, reportedQueueLength),
    )
    const resumeJobs = normalizeLocalEngineResumeJobs(payload.resumeJobs)
    const rawActiveJobId = String(payload.activeJobId || '').trim()
    const activeJobId = QUEUE_JOB_ID_PATTERN.test(rawActiveJobId) ? rawActiveJobId : null

    lastBridgeDiagnostic = null
''',
        "status resume normalization",
    )

    text = replace_once(
        text,
        '''      queueLength,
      queueCapacity,
      queuedJobs,
    }
''',
        '''      queueLength,
      queueCapacity,
      queuedJobs,
      activeJobId,
      canPause: Number(payload.bridgeProtocol || 1) >= MIN_RESUME_BRIDGE_PROTOCOL && Boolean(payload.canPause),
      resumeJobs,
    }
''',
        "status resume return",
    )

    controls = '''

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
'''
    text = replace_once(
        text,
        "\n\nexport async function cancelLocalEngineBridgeJob(): Promise<void> {\n",
        controls + "\n\nexport async function cancelLocalEngineBridgeJob(): Promise<void> {\n",
        "resume action functions",
    )

    path.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    path = Path("tests/local-engine-bridge-error.test.ts")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''  localizeLocalEngineSubmissionMessage,
  normalizeLocalEngineQueuedJobs,
''',
        '''  localizeLocalEngineSubmissionMessage,
  normalizeLocalEngineQueuedJobs,
  normalizeLocalEngineResumeJobs,
''',
        "test import",
    )
    text = replace_once(
        text,
        '''    expect(localizeLocalEngineSubmissionMessage('QUEUE_FULL', 'fallback', 'ru-RU'))
      .toContain('очередь')
''',
        '''    expect(localizeLocalEngineSubmissionMessage('QUEUE_FULL', 'fallback', 'ru-RU'))
      .toContain('очередь')
    expect(localizeLocalEngineSubmissionMessage('RESUME_JOB_NOT_FOUND', 'fallback', 'zh-CN'))
      .toContain('可恢复任务')
    expect(localizeLocalEngineSubmissionMessage('NO_PAUSABLE_JOB', 'fallback', 'en-US'))
      .toContain('can be paused')
''',
        "resume localization tests",
    )

    resume_tests = '''

describe('Local Engine recoverable job normalization', () => {
  it('keeps only privacy-safe resumable summaries and fails unknown modes closed to restart', () => {
    const jobs = normalizeLocalEngineResumeJobs([
      {
        id: 'a'.repeat(32),
        state: 'paused',
        sourceHost: 'media.example.com',
        label: '  Demo   download ',
        videoQuality: '1080p',
        progress: 42.75,
        downloaded: '512 MiB',
        resumeMode: 'continue',
        sourceUrl: 'https://media.example.com/watch?token=secret',
        payload: { cookie: 'must-not-surface' },
      },
      {
        id: 'b'.repeat(32),
        state: 'interrupted',
        sourceHost: 'channels.weixin.qq.com',
        label: 'WeChat video',
        progress: 130,
        resumeMode: 'future-mode',
      },
      {
        id: '../../bad',
        state: 'paused',
        sourceHost: 'bad.example',
      },
      {
        id: 'c'.repeat(32),
        state: 'running',
        sourceHost: 'hidden.example',
      },
    ])

    expect(jobs).toEqual([
      {
        id: 'a'.repeat(32),
        state: 'paused',
        createdAt: '',
        updatedAt: '',
        sourceHost: 'media.example.com',
        label: 'Demo download',
        videoQuality: '1080p',
        progress: 42.75,
        downloaded: '512 MiB',
        resumeMode: 'continue',
      },
      {
        id: 'b'.repeat(32),
        state: 'interrupted',
        createdAt: '',
        updatedAt: '',
        sourceHost: 'channels.weixin.qq.com',
        label: 'WeChat video',
        videoQuality: 'best',
        progress: 100,
        downloaded: '—',
        resumeMode: 'restart',
      },
    ])
    const rendered = JSON.stringify(jobs)
    expect(rendered).not.toContain('secret')
    expect(rendered).not.toContain('cookie')
    expect(rendered).not.toContain('sourceUrl')
    expect(rendered).not.toContain('payload')
  })

  it('deduplicates ids and caps the visible recovery list', () => {
    const raw = Array.from({ length: 40 }, (_, index) => ({
      id: index.toString(16).padStart(32, '0'),
      state: index % 2 === 0 ? 'paused' : 'interrupted',
      sourceHost: 'example.com',
      label: `Job ${index}`,
      progress: index,
      resumeMode: 'continue',
    }))
    raw.splice(1, 0, { ...raw[0], label: 'duplicate' })
    const jobs = normalizeLocalEngineResumeJobs(raw)
    expect(jobs).toHaveLength(24)
    expect(new Set(jobs.map((job) => job.id)).size).toBe(jobs.length)
  })
})
'''
    text = text.rstrip() + resume_tests + "\n"
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_python_bridge()
    patch_typescript_bridge()
    patch_tests()
