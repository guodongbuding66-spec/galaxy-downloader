import {
  cancelLocalEngineBridgeJob,
  getLocalEngineBridgeStatus,
  submitLocalEngineBridgeJob,
  type LocalEngineBridgeStatus,
} from '@/lib/local-engine-bridge'
import {
  createFinalMediaFile as createBrowserFinalMediaFile,
  type FinalMediaInput,
  type FinalMediaProgress,
  type FinalMediaStage,
} from './final-media-export'

export * from './final-media-export'

const POLL_INTERVAL_MS = 700
const MAX_TRANSIENT_STATUS_FAILURES = 8

function abortError(message = 'Export aborted'): DOMException {
  return new DOMException(message, 'AbortError')
}

function stageForStatus(status: LocalEngineBridgeStatus): FinalMediaStage {
  switch (status.state) {
    case 'starting':
      return 'resolving'
    case 'downloading':
      return 'downloading-video'
    case 'processing':
      return 'assembling'
    case 'completed':
      return 'completed'
    default:
      return status.busy ? 'downloading-video' : 'resolving'
  }
}

function progressForStatus(status: LocalEngineBridgeStatus): number {
  switch (status.state) {
    case 'starting':
      return Math.max(2, Math.min(8, Math.round(status.progress || 2)))
    case 'downloading':
      return Math.max(8, Math.min(92, 8 + Math.round(status.progress * 0.84)))
    case 'processing':
      return Math.max(93, Math.min(98, Math.round(status.progress || 95)))
    case 'completed':
      return 100
    default:
      return status.busy ? Math.max(3, Math.min(92, Math.round(status.progress))) : 2
  }
}

function reportLocalProgress(input: FinalMediaInput, status: LocalEngineBridgeStatus): void {
  const progress: FinalMediaProgress = {
    stage: stageForStatus(status),
    progress: progressForStatus(status),
  }
  input.onProgress?.(progress)
}

async function wait(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) throw abortError()
  await new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(resolve, ms)
    const onAbort = () => {
      window.clearTimeout(timer)
      reject(abortError())
    }
    signal?.addEventListener('abort', onAbort, { once: true })
    window.setTimeout(() => signal?.removeEventListener('abort', onAbort), ms + 10)
  })
}

async function runWithConnectedLocalEngine(
  input: FinalMediaInput,
  initialStatus: LocalEngineBridgeStatus,
): Promise<void> {
  if (!input.sourceUrl) {
    throw new Error('Local engine requires the original media URL')
  }
  if (initialStatus.busy) {
    throw new Error('Galaxy Local Engine is already processing another download')
  }

  input.onProgress?.({ stage: 'resolving', progress: 2 })

  await submitLocalEngineBridgeJob({
    sourceUrl: input.sourceUrl,
    videoQuality: 'best',
    audioQuality: 'best',
    includeAudio: Boolean(input.audioUrl),
    includeSubtitle: Boolean(input.subtitleUrl),
    subtitleLanguage: input.subtitleLanguage || null,
    includeCover: Boolean(input.coverUrl),
    browser: 'none',
    playlist: false,
  })

  let transientFailures = 0
  let sawBusy = false

  while (true) {
    if (input.signal?.aborted) {
      await cancelLocalEngineBridgeJob().catch(() => undefined)
      throw abortError()
    }

    const status = await getLocalEngineBridgeStatus()
    if (!status) {
      transientFailures += 1
      if (transientFailures > MAX_TRANSIENT_STATUS_FAILURES) {
        throw new Error('Lost connection to Galaxy Local Engine while the download was running')
      }
      await wait(POLL_INTERVAL_MS, input.signal)
      continue
    }

    transientFailures = 0
    sawBusy = sawBusy || status.busy
    reportLocalProgress(input, status)

    if (status.state === 'failed') {
      throw new Error(status.detail || status.status || 'Galaxy Local Engine download failed')
    }
    if (status.state === 'cancelled') {
      throw abortError('Local download cancelled')
    }
    if (status.state === 'completed') {
      input.onProgress?.({ stage: 'completed', progress: 100 })
      return
    }

    // The bridge accepts the job on the Tk event loop. Give it a short grace
    // period before treating a ready/idle snapshot as a missed handoff.
    if (sawBusy && !status.busy && status.state === 'ready') {
      throw new Error('Galaxy Local Engine returned to Ready before completing the download')
    }

    await wait(POLL_INTERVAL_MS, input.signal)
  }
}

/**
 * Unified finished-video entry point.
 *
 * If Galaxy Local Engine is connected, the normal "Build and download" button
 * uses the desktop engine automatically. This prevents users from accidentally
 * starting the separate ffmpeg.wasm path while the desktop engine sits at
 * "Waiting for a download job". Browser processing remains the automatic
 * fallback only when the desktop engine is unavailable.
 */
export async function createFinalMediaFile(input: FinalMediaInput): Promise<void> {
  if (typeof window !== 'undefined' && input.sourceUrl) {
    const localStatus = await getLocalEngineBridgeStatus()
    if (localStatus) {
      await runWithConnectedLocalEngine(input, localStatus)
      return
    }
  }

  await createBrowserFinalMediaFile(input)
}
