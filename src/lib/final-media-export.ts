import { downloadBlob, getFFmpeg } from '@/lib/ffmpeg';
import { getProxiedDownloadUrl, sanitizeFilename } from '@/lib/utils';

export type FinalMediaStage =
  | 'resolving'
  | 'downloading-video'
  | 'downloading-audio'
  | 'downloading-subtitle'
  | 'downloading-cover'
  | 'loading-ffmpeg'
  | 'assembling'
  | 'saving'
  | 'completed';

export interface FinalMediaProgress {
  stage: FinalMediaStage;
  progress: number;
  loaded?: number;
  total?: number;
}

export interface FinalMediaInput {
  title: string;
  videoUrl: string;
  audioUrl?: string | null;
  subtitleUrl?: string | null;
  subtitleLanguage?: string | null;
  subtitleFormat?: string | null;
  coverUrl?: string | null;
  sourceUrl?: string | null;
  signal?: AbortSignal;
  onProgress?: (progress: FinalMediaProgress) => void;
}

interface RemoteFileResult {
  file: File;
  contentType: string;
}

function extensionFromContentType(contentType: string, fallback: string): string {
  const normalized = contentType.split(';')[0]?.trim().toLowerCase() || '';
  const map: Record<string, string> = {
    'video/mp4': 'mp4',
    'video/webm': 'webm',
    'video/quicktime': 'mov',
    'video/x-matroska': 'mkv',
    'audio/mp4': 'm4a',
    'audio/mpeg': 'mp3',
    'audio/aac': 'aac',
    'audio/webm': 'webm',
    'audio/ogg': 'ogg',
    'text/vtt': 'vtt',
    'application/x-subrip': 'srt',
    'text/srt': 'srt',
    'image/jpeg': 'jpg',
    'image/png': 'png',
    'image/webp': 'webp',
  };
  return map[normalized] || fallback;
}

function extensionFromUrl(url: string, fallback: string): string {
  try {
    const pathname = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost').pathname;
    const match = pathname.match(/\.([a-z0-9]{2,8})$/i);
    return match?.[1]?.toLowerCase() || fallback;
  } catch {
    return fallback;
  }
}

async function fetchRemoteFile({
  url,
  filenameBase,
  fallbackExtension,
  signal,
  stage,
  progressStart,
  progressEnd,
  onProgress,
}: {
  url: string;
  filenameBase: string;
  fallbackExtension: string;
  signal?: AbortSignal;
  stage: FinalMediaStage;
  progressStart: number;
  progressEnd: number;
  onProgress?: (progress: FinalMediaProgress) => void;
}): Promise<RemoteFileResult> {
  const fetchUrl = getProxiedDownloadUrl(url);
  const response = await fetch(fetchUrl, {
    method: 'GET',
    cache: 'no-store',
    signal,
  });

  if (!response.ok) {
    throw new Error(`Download request failed (${response.status})`);
  }

  const contentType = response.headers.get('content-type') || '';
  const total = Number(response.headers.get('content-length') || '0');
  const chunks: Uint8Array[] = [];
  let loaded = 0;

  if (response.body) {
    const reader = response.body.getReader();
    while (true) {
      if (signal?.aborted) {
        await reader.cancel().catch(() => undefined);
        throw new DOMException('Download aborted', 'AbortError');
      }

      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      chunks.push(value);
      loaded += value.byteLength;
      const ratio = total > 0 ? Math.min(1, loaded / total) : 0;
      onProgress?.({
        stage,
        progress: Math.round(progressStart + ((progressEnd - progressStart) * ratio)),
        loaded,
        total,
      });
    }
  } else {
    const buffer = new Uint8Array(await response.arrayBuffer());
    chunks.push(buffer);
    loaded = buffer.byteLength;
  }

  if (loaded === 0) {
    throw new Error('Downloaded media is empty');
  }

  const bytes = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }

  const extension = extensionFromContentType(
    contentType,
    extensionFromUrl(url, fallbackExtension),
  );
  const blob = new Blob([bytes], { type: contentType || undefined });
  const file = new File([blob], `${filenameBase}.${extension}`, { type: contentType || undefined });
  onProgress?.({ stage, progress: progressEnd, loaded, total: total || loaded });
  return { file, contentType };
}

function fsFilename(prefix: string, file: File, fallbackExtension: string): string {
  const extension = file.name.match(/\.([a-z0-9]{2,8})$/i)?.[1]?.toLowerCase() || fallbackExtension;
  return `${prefix}.${extension}`;
}

function toBytes(file: File): Promise<Uint8Array> {
  return file.arrayBuffer().then((buffer) => new Uint8Array(buffer));
}

function normalizeLanguage(language: string | null | undefined): string {
  const value = language?.trim().toLowerCase();
  if (!value) return 'und';
  const primary = value.split(/[-_]/)[0];
  const map: Record<string, string> = {
    zh: 'zho',
    en: 'eng',
    ja: 'jpn',
    es: 'spa',
    ru: 'rus',
    fr: 'fra',
    de: 'deu',
    ko: 'kor',
    pt: 'por',
    it: 'ita',
  };
  return map[primary] || primary.slice(0, 3) || 'und';
}

export function buildFinalMediaFfmpegArgs({
  videoInput,
  audioInput,
  subtitleInput,
  coverInput,
  subtitleLanguage,
  title,
  sourceUrl,
  output = 'final-output.mp4',
}: {
  videoInput: string;
  audioInput?: string | null;
  subtitleInput?: string | null;
  coverInput?: string | null;
  subtitleLanguage?: string | null;
  title?: string | null;
  sourceUrl?: string | null;
  output?: string;
}): string[] {
  const args: string[] = ['-i', videoInput];
  let inputIndex = 1;
  const audioIndex = audioInput ? inputIndex++ : null;
  if (audioInput) args.push('-i', audioInput);
  const subtitleIndex = subtitleInput ? inputIndex++ : null;
  if (subtitleInput) args.push('-i', subtitleInput);
  const coverIndex = coverInput ? inputIndex++ : null;
  if (coverInput) args.push('-i', coverInput);

  args.push('-map', '0:v:0');
  if (audioIndex !== null) {
    args.push('-map', `${audioIndex}:a:0`);
  } else {
    args.push('-map', '0:a:0?');
  }
  if (subtitleIndex !== null) args.push('-map', `${subtitleIndex}:0`);
  if (coverIndex !== null) args.push('-map', `${coverIndex}:v:0`);

  // Preserve the selected video bitstream. Audio is normalized to AAC for MP4
  // compatibility. Subtitles are embedded as a selectable mov_text track.
  args.push('-c:v:0', 'copy');
  args.push('-c:a', 'aac', '-b:a', '256k');

  if (subtitleIndex !== null) {
    args.push('-c:s', 'mov_text');
    args.push('-metadata:s:s:0', `language=${normalizeLanguage(subtitleLanguage)}`);
    args.push('-disposition:s:0', 'default');
  }

  if (coverIndex !== null) {
    args.push('-c:v:1', 'mjpeg');
    args.push('-disposition:v:1', 'attached_pic');
    args.push('-metadata:s:v:1', 'title=Cover');
  }

  if (title?.trim()) args.push('-metadata', `title=${title.trim()}`);
  if (sourceUrl?.trim()) args.push('-metadata', `comment=Source: ${sourceUrl.trim()}`);
  args.push('-movflags', '+faststart');
  // `-shortest` is useful when only video + a separately downloaded audio
  // track are present, but it must not consider a short subtitle/cover stream
  // and accidentally truncate the finished movie.
  if (audioIndex !== null && subtitleIndex === null && coverIndex === null) {
    args.push('-shortest');
  }
  args.push(output);
  return args;
}

export async function createFinalMediaFile(input: FinalMediaInput): Promise<void> {
  const safeTitle = sanitizeFilename(input.title || 'media').slice(0, 120) || 'media';
  input.onProgress?.({ stage: 'resolving', progress: 2 });

  const video = await fetchRemoteFile({
    url: input.videoUrl,
    filenameBase: `${safeTitle}-video`,
    fallbackExtension: 'mp4',
    signal: input.signal,
    stage: 'downloading-video',
    progressStart: 3,
    progressEnd: 36,
    onProgress: input.onProgress,
  });

  const audio = input.audioUrl
    ? await fetchRemoteFile({
        url: input.audioUrl,
        filenameBase: `${safeTitle}-audio`,
        fallbackExtension: 'm4a',
        signal: input.signal,
        stage: 'downloading-audio',
        progressStart: 36,
        progressEnd: 52,
        onProgress: input.onProgress,
      })
    : null;

  const subtitle = input.subtitleUrl
    ? await fetchRemoteFile({
        url: input.subtitleUrl,
        filenameBase: `${safeTitle}-subtitle`,
        fallbackExtension: input.subtitleFormat || 'vtt',
        signal: input.signal,
        stage: 'downloading-subtitle',
        progressStart: 52,
        progressEnd: 57,
        onProgress: input.onProgress,
      })
    : null;

  const cover = input.coverUrl
    ? await fetchRemoteFile({
        url: input.coverUrl,
        filenameBase: `${safeTitle}-cover`,
        fallbackExtension: 'jpg',
        signal: input.signal,
        stage: 'downloading-cover',
        progressStart: 57,
        progressEnd: 62,
        onProgress: input.onProgress,
      })
    : null;

  input.onProgress?.({ stage: 'loading-ffmpeg', progress: 64 });
  const ffmpeg = await getFFmpeg();
  if (input.signal?.aborted) throw new DOMException('Export aborted', 'AbortError');

  const videoName = fsFilename('final-video', video.file, 'mp4');
  const audioName = audio ? fsFilename('final-audio', audio.file, 'm4a') : null;
  const subtitleName = subtitle ? fsFilename('final-subtitle', subtitle.file, input.subtitleFormat || 'vtt') : null;
  const coverName = cover ? fsFilename('final-cover', cover.file, 'jpg') : null;
  const outputName = 'final-output.mp4';
  const tempFiles = [videoName, audioName, subtitleName, coverName, outputName].filter(Boolean) as string[];

  await ffmpeg.writeFile(videoName, await toBytes(video.file), { signal: input.signal });
  if (audio && audioName) await ffmpeg.writeFile(audioName, await toBytes(audio.file), { signal: input.signal });
  if (subtitle && subtitleName) await ffmpeg.writeFile(subtitleName, await toBytes(subtitle.file), { signal: input.signal });
  if (cover && coverName) await ffmpeg.writeFile(coverName, await toBytes(cover.file), { signal: input.signal });

  const handleProgress = ({ progress }: { progress: number }) => {
    input.onProgress?.({
      stage: 'assembling',
      progress: 66 + Math.round(Math.max(0, Math.min(1, progress)) * 30),
    });
  };
  ffmpeg.on('progress', handleProgress);

  try {
    input.onProgress?.({ stage: 'assembling', progress: 66 });
    await ffmpeg.exec(buildFinalMediaFfmpegArgs({
      videoInput: videoName,
      audioInput: audioName,
      subtitleInput: subtitleName,
      coverInput: coverName,
      subtitleLanguage: input.subtitleLanguage,
      title: input.title,
      sourceUrl: input.sourceUrl,
      output: outputName,
    }), undefined, { signal: input.signal });

    input.onProgress?.({ stage: 'saving', progress: 97 });
    const outputData = await ffmpeg.readFile(outputName, undefined, { signal: input.signal });
    if (typeof outputData === 'string') throw new Error('Unexpected FFmpeg output');
    const buffer = new ArrayBuffer(outputData.byteLength);
    new Uint8Array(buffer).set(outputData);
    downloadBlob(new Blob([buffer], { type: 'video/mp4' }), `${safeTitle}.mp4`);
    input.onProgress?.({ stage: 'completed', progress: 100 });
  } finally {
    ffmpeg.off('progress', handleProgress);
    await Promise.all(tempFiles.map((name) => ffmpeg.deleteFile(name).catch(() => undefined)));
  }
}
