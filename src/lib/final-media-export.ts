import pRetry from 'p-retry';

import { downloadBlob, getFFmpeg } from '@/lib/ffmpeg';
import {
  buildRangeHeader,
  decryptAes128Cbc,
  importAes128Key,
  parseHlsMediaPlaylist,
  pickBestVariant,
  type ByteRange,
  type HlsSegment,
} from '@/lib/hls-browser-download';
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

const HLS_CONTENT_TYPES = new Set([
  'application/vnd.apple.mpegurl',
  'application/x-mpegurl',
  'audio/mpegurl',
  'audio/x-mpegurl',
]);
const HLS_DOWNLOAD_CONCURRENCY = 6;
const HLS_DOWNLOAD_RETRIES = 3;
const HLS_MASTER_MAX_DEPTH = 8;
const HLS_FINAL_EXPORT_MAX_SEGMENTS = 1200;
const MP4_AUDIO_COPY_EXTENSIONS = new Set(['aac', 'm4a', 'm4b', 'mp4']);

function extensionFromContentType(contentType: string, fallback: string): string {
  const normalized = contentType.split(';')[0]?.trim().toLowerCase() || '';
  const map: Record<string, string> = {
    'video/mp4': 'mp4',
    'video/webm': 'webm',
    'video/quicktime': 'mov',
    'video/x-matroska': 'mkv',
    'video/mp2t': 'ts',
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

function fileExtension(file: File): string {
  return file.name.match(/\.([a-z0-9]{2,8})$/i)?.[1]?.toLowerCase() || '';
}

/**
 * If an audio stream already lives in an MP4/AAC-compatible container, keep
 * the exact selected bitstream instead of needlessly recompressing it. WebM /
 * Opus and other containers are transcoded to high-bitrate AAC for broad MP4
 * playback compatibility.
 */
export function shouldStreamCopyAudio(file: File): boolean {
  const extension = fileExtension(file);
  const contentType = file.type.split(';')[0]?.trim().toLowerCase() || '';
  return MP4_AUDIO_COPY_EXTENSIONS.has(extension)
    || contentType === 'audio/mp4'
    || contentType === 'audio/aac';
}

function isAlreadyBackendResource(url: string): boolean {
  try {
    const pathname = new URL(url, typeof window !== 'undefined' ? window.location.origin : 'http://localhost').pathname;
    return pathname === '/api/download' || pathname === '/api/hls-proxy';
  } catch {
    return false;
  }
}

function fetchableUrl(url: string): string {
  return isAlreadyBackendResource(url) ? url : getProxiedDownloadUrl(url);
}

export function isHlsMediaResponse(contentType: string, url: string, bytes?: Uint8Array | null): boolean {
  const normalizedType = contentType.split(';')[0]?.trim().toLowerCase() || '';
  if (HLS_CONTENT_TYPES.has(normalizedType)) return true;
  if (extensionFromUrl(url, '') === 'm3u8') return true;
  if (bytes?.byteLength) {
    const prefix = new TextDecoder().decode(bytes.subarray(0, Math.min(bytes.byteLength, 256))).trimStart();
    return prefix.startsWith('#EXTM3U');
  }
  return false;
}

async function readResponseBytes({
  response,
  signal,
  stage,
  progressStart,
  progressEnd,
  onProgress,
}: {
  response: Response;
  signal?: AbortSignal;
  stage: FinalMediaStage;
  progressStart: number;
  progressEnd: number;
  onProgress?: (progress: FinalMediaProgress) => void;
}): Promise<Uint8Array> {
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
  return bytes;
}

async function fetchText(url: string, signal?: AbortSignal): Promise<{ text: string; finalUrl: string }> {
  const response = await fetch(fetchableUrl(url), {
    method: 'GET',
    cache: 'no-store',
    signal,
    headers: { Accept: 'application/vnd.apple.mpegurl, application/x-mpegurl, text/plain, */*' },
  });
  if (!response.ok) throw new Error(`HLS playlist request failed (${response.status})`);
  return { text: await response.text(), finalUrl: response.url || url };
}

async function resolveHlsMediaPlaylist(initialText: string, initialUrl: string, signal?: AbortSignal) {
  let playlistText = initialText;
  let playlistUrl = initialUrl;

  for (let depth = 0; depth < HLS_MASTER_MAX_DEPTH; depth += 1) {
    const variant = pickBestVariant(playlistText, playlistUrl);
    if (!variant) {
      return {
        playlistUrl,
        media: parseHlsMediaPlaylist(playlistText, playlistUrl),
      };
    }
    const next = await fetchText(variant.url, signal);
    playlistText = next.text;
    playlistUrl = next.finalUrl || variant.url;
  }

  if (pickBestVariant(playlistText, playlistUrl)) {
    throw new Error('HLS master playlist nesting is too deep');
  }
  return {
    playlistUrl,
    media: parseHlsMediaPlaylist(playlistText, playlistUrl),
  };
}

async function fetchHlsBytes(url: string, signal?: AbortSignal, byterange?: ByteRange): Promise<Uint8Array> {
  return pRetry(async () => {
    const range = buildRangeHeader(byterange);
    const response = await fetch(fetchableUrl(url), {
      method: 'GET',
      cache: 'no-store',
      signal,
      headers: range ? { Range: range } : undefined,
    });
    if (!response.ok) throw new Error(`HLS media request failed (${response.status})`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength === 0) throw new Error('HLS media resource is empty');
    return bytes;
  }, {
    retries: HLS_DOWNLOAD_RETRIES,
    factor: 2,
    minTimeout: 350,
    maxTimeout: 2500,
    randomize: true,
    signal,
  });
}

async function runWithConcurrency<T>(items: T[], concurrency: number, worker: (item: T, index: number) => Promise<void>) {
  let nextIndex = 0;
  async function runWorker() {
    while (nextIndex < items.length) {
      const current = nextIndex;
      nextIndex += 1;
      await worker(items[current], current);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, () => runWorker()));
}

export function inferJoinedHlsExtension(mapUrl: string | null, segments: Array<Pick<HlsSegment, 'url'>>): 'mp4' | 'ts' {
  if (mapUrl) return 'mp4';
  const extension = extensionFromUrl(segments[0]?.url || '', '').toLowerCase();
  return ['mp4', 'm4s', 'm4v', 'cmfv', 'cmfa'].includes(extension) ? 'mp4' : 'ts';
}

async function createHlsFile({
  initialPlaylistText,
  playlistUrl,
  filenameBase,
  signal,
  stage,
  progressStart,
  progressEnd,
  onProgress,
}: {
  initialPlaylistText: string;
  playlistUrl: string;
  filenameBase: string;
  signal?: AbortSignal;
  stage: FinalMediaStage;
  progressStart: number;
  progressEnd: number;
  onProgress?: (progress: FinalMediaProgress) => void;
}): Promise<RemoteFileResult> {
  const resolved = await resolveHlsMediaPlaylist(initialPlaylistText, playlistUrl, signal);
  const { media } = resolved;
  if (media.segments.length > HLS_FINAL_EXPORT_MAX_SEGMENTS) {
    throw new Error(`HLS video has ${media.segments.length} segments and is too large for in-browser final assembly. Use the HLS compatibility downloader or server-side processing.`);
  }

  const targets: Array<{ url: string; byterange?: ByteRange; keyUrl?: string; iv?: Uint8Array }> = [
    ...(media.mapUrl ? [{ url: media.mapUrl, byterange: media.mapByterange }] : []),
    ...media.segments,
  ];
  const chunks = new Map<number, Uint8Array>();
  const keyCache = new Map<string, Promise<CryptoKey>>();
  let completed = 0;
  let loaded = 0;

  await runWithConcurrency(targets, HLS_DOWNLOAD_CONCURRENCY, async (target, index) => {
    let bytes = await fetchHlsBytes(target.url, signal, target.byterange);
    if (target.keyUrl) {
      if (!target.iv) throw new Error('Encrypted HLS segment is missing an IV');
      if (!keyCache.has(target.keyUrl)) {
        keyCache.set(target.keyUrl, fetchHlsBytes(target.keyUrl, signal).then(importAes128Key));
      }
      bytes = await decryptAes128Cbc(bytes, await keyCache.get(target.keyUrl)!, target.iv);
    }
    chunks.set(index, bytes);
    completed += 1;
    loaded += bytes.byteLength;
    const ratio = targets.length ? completed / targets.length : 1;
    onProgress?.({
      stage,
      progress: Math.round(progressStart + ((progressEnd - progressStart) * ratio)),
      loaded,
    });
  });

  const ordered = targets.map((_, index) => chunks.get(index)).filter(Boolean) as Uint8Array[];
  const total = ordered.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const joined = new Uint8Array(total);
  let offset = 0;
  for (const chunk of ordered) {
    joined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  const extension = inferJoinedHlsExtension(media.mapUrl, media.segments);
  const contentType = extension === 'mp4' ? 'video/mp4' : 'video/mp2t';
  const file = new File([joined], `${filenameBase}.${extension}`, { type: contentType });
  onProgress?.({ stage, progress: progressEnd, loaded: total, total });
  return { file, contentType };
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
  const fetchUrl = fetchableUrl(url);
  const response = await fetch(fetchUrl, {
    method: 'GET',
    cache: 'no-store',
    signal,
  });

  if (!response.ok) {
    throw new Error(`Download request failed (${response.status})`);
  }

  const contentType = response.headers.get('content-type') || '';
  const bytes = await readResponseBytes({ response, signal, stage, progressStart, progressEnd, onProgress });
  const finalUrl = response.url || url;

  if (isHlsMediaResponse(contentType, finalUrl, bytes)) {
    const playlistText = new TextDecoder().decode(bytes);
    onProgress?.({ stage, progress: progressStart });
    return createHlsFile({
      initialPlaylistText: playlistText,
      playlistUrl: finalUrl,
      filenameBase,
      signal,
      stage,
      progressStart,
      progressEnd,
      onProgress,
    });
  }

  const extension = extensionFromContentType(
    contentType,
    extensionFromUrl(url, fallbackExtension),
  );
  const blob = new Blob([bytes], { type: contentType || undefined });
  const file = new File([blob], `${filenameBase}.${extension}`, { type: contentType || undefined });
  onProgress?.({ stage, progress: progressEnd, loaded: bytes.byteLength, total: bytes.byteLength });
  return { file, contentType };
}

function fsFilename(prefix: string, file: File, fallbackExtension: string): string {
  const extension = fileExtension(file) || fallbackExtension;
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
  audioCodec = 'aac',
  audioBitrate = '320k',
  output = 'final-output.mp4',
}: {
  videoInput: string;
  audioInput?: string | null;
  subtitleInput?: string | null;
  coverInput?: string | null;
  subtitleLanguage?: string | null;
  title?: string | null;
  sourceUrl?: string | null;
  audioCodec?: 'copy' | 'aac';
  audioBitrate?: string;
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

  // Never re-encode the selected video. Preserve compatible AAC/MP4 audio too;
  // only incompatible audio is transcoded, at a high compatibility bitrate.
  args.push('-c:v:0', 'copy');
  args.push('-c:a', audioCodec);
  if (audioCodec === 'aac') {
    args.push('-b:a', audioBitrate);
  }

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
    const selectedAudioFile = audio?.file || video.file;
    const audioCodec: 'copy' | 'aac' = shouldStreamCopyAudio(selectedAudioFile) ? 'copy' : 'aac';
    await ffmpeg.exec(buildFinalMediaFfmpegArgs({
      videoInput: videoName,
      audioInput: audioName,
      subtitleInput: subtitleName,
      coverInput: coverName,
      subtitleLanguage: input.subtitleLanguage,
      title: input.title,
      sourceUrl: input.sourceUrl,
      audioCodec,
      audioBitrate: '320k',
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
