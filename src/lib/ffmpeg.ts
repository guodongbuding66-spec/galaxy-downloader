import { FFmpeg, FFFSType } from '@ffmpeg/ffmpeg';

import { detectLocalProcessingCapabilities } from '@/lib/local-engine';

let ffmpegInstance: FFmpeg | null = null;
let loadPromise: Promise<FFmpeg> | null = null;

const FFMPEG_CORE_VERSION = '0.12.9';
const FFMPEG_ASSET_TIMEOUT_MS = 45_000;
const FFMPEG_INITIALIZATION_TIMEOUT_MS = 45_000;
const LOCAL_FFMPEG_CORE_BASE_URL = '/ffmpeg-core';
const LOCAL_FFMPEG_WASM_PART_URLS = [
  `${LOCAL_FFMPEG_CORE_BASE_URL}/ffmpeg-core.wasm.part-0`,
  `${LOCAL_FFMPEG_CORE_BASE_URL}/ffmpeg-core.wasm.part-1`,
];
const FFMPEG_SINGLE_CORE_BASE_URLS = [
  LOCAL_FFMPEG_CORE_BASE_URL,
  `https://cdn.jsdelivr.net/npm/@ffmpeg/core@${FFMPEG_CORE_VERSION}/dist/esm`,
  `https://cdn.jsdmirror.com/npm/@ffmpeg/core@${FFMPEG_CORE_VERSION}/dist/esm`,
] as const;
const FFMPEG_MULTI_CORE_BASE_URLS = [
  `https://cdn.jsdelivr.net/npm/@ffmpeg/core-mt@${FFMPEG_CORE_VERSION}/dist/esm`,
  `https://cdn.jsdmirror.com/npm/@ffmpeg/core-mt@${FFMPEG_CORE_VERSION}/dist/esm`,
] as const;

type CoreCandidate = {
  baseURL: string;
  multithread: boolean;
};

export function getFFmpegCoreBaseUrls(): readonly string[] {
  return [...FFMPEG_MULTI_CORE_BASE_URLS, ...FFMPEG_SINGLE_CORE_BASE_URLS];
}

export function getPreferredFFmpegCoreCandidates(): readonly CoreCandidate[] {
  const capabilities = detectLocalProcessingCapabilities();
  const candidates: CoreCandidate[] = [];

  if (capabilities.multiThreadFFmpeg) {
    candidates.push(...FFMPEG_MULTI_CORE_BASE_URLS.map((baseURL) => ({
      baseURL,
      multithread: true,
    })));
  }

  candidates.push(...FFMPEG_SINGLE_CORE_BASE_URLS.map((baseURL) => ({
    baseURL,
    multithread: false,
  })));
  return candidates;
}

async function fetchBlobURL(
  url: string,
  mimeType: string,
  signal: AbortSignal
): Promise<string> {
  const response = await fetch(url, {
    method: 'GET',
    cache: 'force-cache',
    signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  const buffer = await response.arrayBuffer();
  const blob = new Blob([buffer], { type: mimeType });
  return URL.createObjectURL(blob);
}

async function fetchCombinedBlobURL(
  urls: readonly string[],
  mimeType: string,
  signal: AbortSignal
): Promise<string> {
  const parts = await Promise.all(urls.map(async (url) => {
    const response = await fetch(url, {
      method: 'GET',
      cache: 'force-cache',
      signal,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    return response.arrayBuffer();
  }));

  return URL.createObjectURL(new Blob(parts, { type: mimeType }));
}

async function withTimeout<T>(
  timeoutMs: number,
  operation: (signal: AbortSignal) => Promise<T>
): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => {
    controller.abort(new DOMException(`Timed out after ${timeoutMs}ms`, 'AbortError'));
  }, timeoutMs);

  try {
    return await operation(controller.signal);
  } finally {
    clearTimeout(timeoutId);
  }
}

async function loadFFmpegCoreFromSource(
  ffmpeg: FFmpeg,
  candidate: CoreCandidate,
) {
  const { baseURL, multithread } = candidate;
  let coreURL: string | null = null;
  let wasmURL: string | null = null;
  let workerURL: string | null = null;

  try {
    coreURL = await withTimeout(
      FFMPEG_ASSET_TIMEOUT_MS,
      (signal) => fetchBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript', signal)
    );
    wasmURL = await withTimeout(
      FFMPEG_ASSET_TIMEOUT_MS,
      (signal) => baseURL === LOCAL_FFMPEG_CORE_BASE_URL
        ? fetchCombinedBlobURL(LOCAL_FFMPEG_WASM_PART_URLS, 'application/wasm', signal)
        : fetchBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm', signal)
    );

    if (multithread) {
      workerURL = await withTimeout(
        FFMPEG_ASSET_TIMEOUT_MS,
        (signal) => fetchBlobURL(`${baseURL}/ffmpeg-core.worker.js`, 'text/javascript', signal)
      );
    }

    await withTimeout(FFMPEG_INITIALIZATION_TIMEOUT_MS, (signal) => ffmpeg.load({
      coreURL,
      wasmURL,
      ...(workerURL ? { workerURL } : {}),
    }, { signal }));
  } finally {
    if (!ffmpeg.loaded) {
      if (coreURL) URL.revokeObjectURL(coreURL);
      if (wasmURL) URL.revokeObjectURL(wasmURL);
      if (workerURL) URL.revokeObjectURL(workerURL);
    }
  }
}

export async function getFFmpeg(): Promise<FFmpeg> {
  if (ffmpegInstance?.loaded) return ffmpegInstance;
  if (loadPromise) return loadPromise;

  loadPromise = (async () => {
    let lastError: unknown = null;

    for (const candidate of getPreferredFFmpegCoreCandidates()) {
      const ffmpeg = new FFmpeg();
      ffmpeg.on('log', ({ message }) => console.log('[FFmpeg]', message));

      try {
        await loadFFmpegCoreFromSource(ffmpeg, candidate);
        console.log(
          `[FFmpeg] Loaded ${candidate.multithread ? 'multi-thread' : 'single-thread'} core from:`,
          candidate.baseURL,
        );
        ffmpegInstance = ffmpeg;
        return ffmpeg;
      } catch (candidateError) {
        lastError = candidateError;
        ffmpeg.terminate();
        console.warn('[FFmpeg] Failed to load core from:', candidate.baseURL, candidateError);
      }
    }

    loadPromise = null;
    throw new Error(`Failed to load FFmpeg: ${lastError instanceof Error ? lastError.message : String(lastError)}`);
  })();

  return loadPromise;
}

export function terminateFFmpeg() {
  if (ffmpegInstance) {
    ffmpegInstance.terminate();
    ffmpegInstance = null;
  }
  loadPromise = null;
}

export type FFmpegStage =
  | 'downloading'
  | 'converting'
  | 'reading-video'
  | 'reading-audio'
  | 'merging';

export type ExtractStage = Extract<FFmpegStage, 'downloading' | 'converting'>;
export type MergeStage = Extract<FFmpegStage, 'reading-video' | 'reading-audio' | 'merging'>;

export interface ProgressInfo {
  loaded?: number;
  total?: number;
}

export interface ExtractAudioOptions {
  videoUrl?: string;
  videoFile?: File;
  signal?: AbortSignal;
  onProgress?: (progress: number, stage: ExtractStage, info?: ProgressInfo) => void;
}

export interface MergeVideoAudioOptions {
  videoFile: File;
  audioFile: File;
  signal?: AbortSignal;
  onProgress?: (progress: number, stage: MergeStage, info?: ProgressInfo) => void;
}

function getFileExtension(filename: string): string | null {
  const match = /\.([a-z0-9]+)$/i.exec(filename);
  return match ? match[1].toLowerCase() : null;
}

function buildTempFilename(prefix: string, file: File, fallbackExtension: string): string {
  const extension = getFileExtension(file.name) ?? fallbackExtension;
  return `${prefix}.${extension}`;
}

async function mountWorkerFile(
  ffmpeg: FFmpeg,
  file: File,
  mountPoint: string,
): Promise<{ path: string; cleanup: () => Promise<void> }> {
  await ffmpeg.createDir(mountPoint).catch(() => undefined);
  await ffmpeg.mount(FFFSType.WORKERFS, { files: [file] }, mountPoint);

  return {
    path: `${mountPoint}/${file.name}`,
    cleanup: async () => {
      await ffmpeg.unmount(mountPoint).catch(() => undefined);
      await ffmpeg.deleteDir(mountPoint).catch(() => undefined);
    },
  };
}

async function readLocalFile<TStage extends FFmpegStage>(
  file: File,
  stage: TStage,
  signal?: AbortSignal,
  onProgress?: (progress: number, stage: TStage, info?: ProgressInfo) => void,
  progressStart = 0,
  progressEnd = 100
): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    const total = file.size;
    const range = Math.max(0, progressEnd - progressStart);
    let settled = false;

    const cleanupAbort = () => signal?.removeEventListener('abort', handleAbort);
    const rejectOnce = (error: Error) => {
      if (settled) return;
      settled = true;
      cleanupAbort();
      reject(error);
    };
    const resolveOnce = (data: Uint8Array) => {
      if (settled) return;
      settled = true;
      cleanupAbort();
      resolve(data);
    };
    const handleAbort = () => {
      if (reader.readyState === FileReader.LOADING) reader.abort();
      rejectOnce(new DOMException('File read was aborted', 'AbortError'));
    };

    if (signal?.aborted) {
      handleAbort();
      return;
    }

    signal?.addEventListener('abort', handleAbort, { once: true });
    reader.onprogress = (event) => {
      if (settled) return;
      const loaded = event.loaded;
      const eventTotal = event.total || total;
      const ratio = eventTotal > 0 ? loaded / eventTotal : 0;
      onProgress?.(Math.round(progressStart + (ratio * range)), stage, { loaded, total: eventTotal });
    };
    reader.onload = (e) => {
      const result = e.target?.result;
      if (result instanceof ArrayBuffer) {
        onProgress?.(progressEnd, stage, { loaded: total, total });
        resolveOnce(new Uint8Array(result));
      } else {
        rejectOnce(new Error('Failed to read file as ArrayBuffer'));
      }
    };
    reader.onerror = () => rejectOnce(new Error(`File read error: ${reader.error?.message || 'unknown error'}`));
    reader.readAsArrayBuffer(file);
  });
}

async function downloadVideoData(
  videoUrl: string,
  signal?: AbortSignal,
  onProgress?: (progress: number, stage: ExtractStage, info?: ProgressInfo) => void
): Promise<Uint8Array> {
  const response = await fetch(videoUrl, { method: 'GET', cache: 'no-store', signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);

  const total = Number(response.headers.get('content-length') || '0');
  if (!response.body) {
    const fallbackData = new Uint8Array(await response.arrayBuffer());
    onProgress?.(100, 'downloading', { loaded: fallbackData.byteLength, total });
    return fallbackData;
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;

  while (true) {
    if (signal?.aborted) {
      await reader.cancel().catch(() => undefined);
      throw new DOMException('Video download was aborted', 'AbortError');
    }
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    chunks.push(value);
    loaded += value.byteLength;
    onProgress?.(total > 0 ? Math.round((loaded * 100) / total) : 0, 'downloading', { loaded, total });
  }

  const combined = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  onProgress?.(100, 'downloading', { loaded, total });
  return combined;
}

export async function extractAudioFromVideo({
  videoUrl,
  videoFile,
  signal,
  onProgress,
}: ExtractAudioOptions): Promise<Blob> {
  const ffmpeg = await getFFmpeg();
  let inputPath = 'input.mp4';
  let mountedCleanup: (() => Promise<void>) | null = null;

  try {
    onProgress?.(0, 'downloading');
    if (videoFile) {
      const mounted = await mountWorkerFile(ffmpeg, videoFile, '/galaxy-audio-source');
      inputPath = mounted.path;
      mountedCleanup = mounted.cleanup;
      onProgress?.(100, 'downloading', { loaded: videoFile.size, total: videoFile.size });
    } else if (videoUrl) {
      const videoData = await downloadVideoData(videoUrl, signal, onProgress);
      await ffmpeg.writeFile(inputPath, videoData, { signal });
    } else {
      throw new Error('Either videoUrl or videoFile must be provided');
    }

    const handleProgress = ({ progress }: { progress: number }) => {
      onProgress?.(Math.round(progress * 100), 'converting');
    };
    ffmpeg.on('progress', handleProgress);

    try {
      await ffmpeg.exec([
        '-i', inputPath,
        '-vn',
        '-acodec', 'libmp3lame',
        '-q:a', '2',
        'output.mp3'
      ], undefined, { signal });

      const outputData = await ffmpeg.readFile('output.mp3', undefined, { signal });
      if (typeof outputData === 'string') throw new Error('Unexpected string output from ffmpeg');
      const buffer = new ArrayBuffer(outputData.byteLength);
      new Uint8Array(buffer).set(outputData);
      return new Blob([buffer], { type: 'audio/mpeg' });
    } finally {
      ffmpeg.off('progress', handleProgress);
      await ffmpeg.deleteFile('output.mp3').catch(() => undefined);
    }
  } finally {
    if (mountedCleanup) {
      await mountedCleanup();
    } else {
      await ffmpeg.deleteFile(inputPath).catch(() => undefined);
    }
  }
}

export async function mergeVideoAudio({
  videoFile,
  audioFile,
  signal,
  onProgress,
}: MergeVideoAudioOptions): Promise<Blob> {
  const ffmpeg = await getFFmpeg();
  const outputName = 'merged-output.mp4';

  onProgress?.(10, 'reading-video', { loaded: videoFile.size, total: videoFile.size });
  const videoMount = await mountWorkerFile(ffmpeg, videoFile, '/galaxy-video-input');
  onProgress?.(40, 'reading-video', { loaded: videoFile.size, total: videoFile.size });

  let audioMount: Awaited<ReturnType<typeof mountWorkerFile>> | null = null;
  try {
    onProgress?.(40, 'reading-audio', { loaded: audioFile.size, total: audioFile.size });
    audioMount = await mountWorkerFile(ffmpeg, audioFile, '/galaxy-audio-input');
    onProgress?.(50, 'reading-audio', { loaded: audioFile.size, total: audioFile.size });

    const handleProgress = ({ progress }: { progress: number }) => {
      onProgress?.(50 + Math.round(progress * 50), 'merging');
    };
    ffmpeg.on('progress', handleProgress);

    try {
      await ffmpeg.exec([
        '-i', videoMount.path,
        '-i', audioMount.path,
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-shortest',
        '-movflags', '+faststart',
        outputName,
      ], undefined, { signal });

      const outputData = await ffmpeg.readFile(outputName, undefined, { signal });
      if (typeof outputData === 'string') throw new Error('Unexpected string output from ffmpeg during merge');
      const buffer = new ArrayBuffer(outputData.byteLength);
      new Uint8Array(buffer).set(outputData);
      return new Blob([buffer], { type: 'video/mp4' });
    } finally {
      ffmpeg.off('progress', handleProgress);
      await ffmpeg.deleteFile(outputName).catch(() => undefined);
    }
  } finally {
    if (audioMount) await audioMount.cleanup();
    await videoMount.cleanup();
  }
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
