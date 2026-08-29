import { FFFSType, type FFmpeg } from '@ffmpeg/ffmpeg'

import { downloadToBrowserLocalFile, type BrowserLocalFile } from '@/lib/browser-local-file'
import { downloadBlob, getFFmpeg } from '@/lib/ffmpeg'
import {
  buildFinalMediaFfmpegArgs,
  createFinalMediaFile as createLegacyFinalMediaFile,
  shouldStreamCopyAudio,
  type FinalMediaInput,
  type FinalMediaProgress,
  type FinalMediaStage,
} from './final-media-export'
import { getProxiedDownloadUrl, sanitizeFilename } from '@/lib/utils'

export type { FinalMediaInput, FinalMediaProgress, FinalMediaStage }
export {
  buildFinalMediaFfmpegArgs,
  inferJoinedHlsExtension,
  isHlsMediaResponse,
  resolveLogicalHlsBaseUrl,
  shouldStreamCopyAudio,
} from './final-media-export'

interface MountedFile {
  path: string
  cleanup: () => Promise<void>
}

function fileExtension(url: string, fallback: string): string {
  try {
    const pathname = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost').pathname
    return pathname.match(/\.([a-z0-9]{2,8})$/i)?.[1]?.toLowerCase() || fallback
  } catch {
    return fallback
  }
}

function isHlsUrl(url: string | null | undefined): boolean {
  if (!url) return false
  try {
    return new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
      .pathname.toLowerCase().endsWith('.m3u8')
  } catch {
    return /\.m3u8(?:$|\?)/i.test(url)
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

async function mountFile(ffmpeg: FFmpeg, file: File, mountPoint: string): Promise<MountedFile> {
  await ffmpeg.createDir(mountPoint).catch(() => undefined)
  await ffmpeg.mount(FFFSType.WORKERFS, { files: [file] }, mountPoint)
  return {
    path: `${mountPoint}/${file.name}`,
    cleanup: async () => {
      await ffmpeg.unmount(mountPoint).catch(() => undefined)
      await ffmpeg.deleteDir(mountPoint).catch(() => undefined)
    },
  }
}

async function downloadLocalCandidate({
  url,
  filename,
  signal,
  stage,
  progressStart,
  progressEnd,
  onProgress,
}: {
  url: string
  filename: string
  signal?: AbortSignal
  stage: FinalMediaStage
  progressStart: number
  progressEnd: number
  onProgress?: (progress: FinalMediaProgress) => void
}): Promise<BrowserLocalFile> {
  const direct = url.trim()
  const proxied = getProxiedDownloadUrl(direct)
  const candidates = [...new Set([direct, proxied].filter(Boolean))]
  let lastError: unknown = null

  for (const candidate of candidates) {
    try {
      return await downloadToBrowserLocalFile({
        url: candidate,
        filename,
        signal,
        onProgress: ({ loaded, total }) => {
          const ratio = total > 0 ? Math.min(1, loaded / total) : 0
          onProgress?.({
            stage,
            progress: Math.round(progressStart + ((progressEnd - progressStart) * ratio)),
            loaded,
            total,
          })
        },
      })
    } catch (error) {
      if (isAbortError(error)) throw error
      lastError = error
      console.warn('[Galaxy Local] media candidate failed:', candidate, error)
    }
  }

  throw lastError instanceof Error ? lastError : new Error('Unable to download media locally')
}

async function writeSmallFile(ffmpeg: FFmpeg, name: string, file: File, signal?: AbortSignal) {
  const bytes = new Uint8Array(await file.arrayBuffer())
  await ffmpeg.writeFile(name, bytes, { signal })
}

async function createBrowserLocalFinalMediaFile(input: FinalMediaInput): Promise<void> {
  if (isHlsUrl(input.videoUrl) || isHlsUrl(input.audioUrl)) {
    throw new Error('GALAXY_USE_LEGACY_HLS')
  }

  const safeTitle = sanitizeFilename(input.title || 'media').slice(0, 120) || 'media'
  input.onProgress?.({ stage: 'resolving', progress: 2 })

  const localResources: BrowserLocalFile[] = []
  const mounts: MountedFile[] = []
  const ffmpegTempFiles: string[] = []

  try {
    const video = await downloadLocalCandidate({
      url: input.videoUrl,
      filename: `${safeTitle}-video.${fileExtension(input.videoUrl, 'mp4')}`,
      signal: input.signal,
      stage: 'downloading-video',
      progressStart: 3,
      progressEnd: 36,
      onProgress: input.onProgress,
    })
    localResources.push(video)

    const audio = input.audioUrl
      ? await downloadLocalCandidate({
          url: input.audioUrl,
          filename: `${safeTitle}-audio.${fileExtension(input.audioUrl, 'm4a')}`,
          signal: input.signal,
          stage: 'downloading-audio',
          progressStart: 36,
          progressEnd: 52,
          onProgress: input.onProgress,
        })
      : null
    if (audio) localResources.push(audio)

    const subtitle = input.subtitleUrl
      ? await downloadLocalCandidate({
          url: input.subtitleUrl,
          filename: `${safeTitle}-subtitle.${input.subtitleFormat || fileExtension(input.subtitleUrl, 'vtt')}`,
          signal: input.signal,
          stage: 'downloading-subtitle',
          progressStart: 52,
          progressEnd: 57,
          onProgress: input.onProgress,
        })
      : null
    if (subtitle) localResources.push(subtitle)

    const cover = input.coverUrl
      ? await downloadLocalCandidate({
          url: input.coverUrl,
          filename: `${safeTitle}-cover.${fileExtension(input.coverUrl, 'jpg')}`,
          signal: input.signal,
          stage: 'downloading-cover',
          progressStart: 57,
          progressEnd: 62,
          onProgress: input.onProgress,
        })
      : null
    if (cover) localResources.push(cover)

    input.onProgress?.({ stage: 'loading-ffmpeg', progress: 64 })
    const ffmpeg = await getFFmpeg()
    if (input.signal?.aborted) throw new DOMException('Export aborted', 'AbortError')

    const videoMount = await mountFile(ffmpeg, video.file, '/galaxy-final-video')
    mounts.push(videoMount)
    const audioMount = audio ? await mountFile(ffmpeg, audio.file, '/galaxy-final-audio') : null
    if (audioMount) mounts.push(audioMount)

    const subtitleName = subtitle ? `final-subtitle.${input.subtitleFormat || fileExtension(subtitle.file.name, 'vtt')}` : null
    const coverName = cover ? `final-cover.${fileExtension(cover.file.name, 'jpg')}` : null
    const outputName = 'final-output.mp4'

    if (subtitle && subtitleName) {
      await writeSmallFile(ffmpeg, subtitleName, subtitle.file, input.signal)
      ffmpegTempFiles.push(subtitleName)
    }
    if (cover && coverName) {
      await writeSmallFile(ffmpeg, coverName, cover.file, input.signal)
      ffmpegTempFiles.push(coverName)
    }
    ffmpegTempFiles.push(outputName)

    const handleProgress = ({ progress }: { progress: number }) => {
      input.onProgress?.({
        stage: 'assembling',
        progress: 66 + Math.round(Math.max(0, Math.min(1, progress)) * 30),
      })
    }
    ffmpeg.on('progress', handleProgress)

    try {
      input.onProgress?.({ stage: 'assembling', progress: 66 })
      const selectedAudioFile = audio?.file || video.file
      await ffmpeg.exec(buildFinalMediaFfmpegArgs({
        videoInput: videoMount.path,
        audioInput: audioMount?.path || null,
        subtitleInput: subtitleName,
        coverInput: coverName,
        subtitleLanguage: input.subtitleLanguage,
        title: input.title,
        sourceUrl: input.sourceUrl,
        audioCodec: shouldStreamCopyAudio(selectedAudioFile) ? 'copy' : 'aac',
        audioBitrate: '320k',
        output: outputName,
      }), undefined, { signal: input.signal })

      input.onProgress?.({ stage: 'saving', progress: 97 })
      const outputData = await ffmpeg.readFile(outputName, undefined, { signal: input.signal })
      if (typeof outputData === 'string') throw new Error('Unexpected FFmpeg output')
      downloadBlob(new Blob([outputData], { type: 'video/mp4' }), `${safeTitle}.mp4`)
      input.onProgress?.({ stage: 'completed', progress: 100 })
    } finally {
      ffmpeg.off('progress', handleProgress)
      await Promise.all(ffmpegTempFiles.map((name) => ffmpeg.deleteFile(name).catch(() => undefined)))
    }
  } finally {
    await Promise.allSettled(mounts.reverse().map((mount) => mount.cleanup()))
    await Promise.allSettled(localResources.map((resource) => resource.cleanup()))
  }
}

/**
 * Local-first facade used by the existing one-click finished-video button.
 * Normal direct media is downloaded to browser-local storage and mounted into
 * ffmpeg.wasm. The mature HLS implementation remains the compatibility path.
 */
export async function createFinalMediaFile(input: FinalMediaInput): Promise<void> {
  try {
    await createBrowserLocalFinalMediaFile(input)
  } catch (error) {
    if (isAbortError(error)) throw error
    if (error instanceof Error && error.message === 'GALAXY_USE_LEGACY_HLS') {
      await createLegacyFinalMediaFile(input)
      return
    }
    throw error
  }
}
