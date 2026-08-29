export interface BrowserLocalDownloadProgress {
  loaded: number
  total: number
}

export interface BrowserLocalFile {
  file: File
  storage: 'opfs' | 'memory'
  cleanup: () => Promise<void>
}

interface DownloadToLocalFileOptions {
  url: string
  filename: string
  contentType?: string
  signal?: AbortSignal
  headers?: HeadersInit
  onProgress?: (progress: BrowserLocalDownloadProgress) => void
}

function hasOpfs(): boolean {
  return typeof navigator !== 'undefined'
    && typeof navigator.storage?.getDirectory === 'function'
}

function randomToken(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`
}

async function streamResponseToOpfs(
  response: Response,
  filename: string,
  signal?: AbortSignal,
  onProgress?: (progress: BrowserLocalDownloadProgress) => void,
): Promise<BrowserLocalFile> {
  const root = await navigator.storage.getDirectory()
  const directory = await root.getDirectoryHandle('galaxy-downloader', { create: true })
  const storageName = `${randomToken()}-${filename}`
  const handle = await directory.getFileHandle(storageName, { create: true })
  const writable = await handle.createWritable()
  const total = Number(response.headers.get('content-length') || '0')
  let loaded = 0

  try {
    if (!response.body) {
      const buffer = await response.arrayBuffer()
      if (signal?.aborted) throw new DOMException('Download aborted', 'AbortError')
      await writable.write(buffer)
      loaded = buffer.byteLength
      onProgress?.({ loaded, total: total || loaded })
    } else {
      const reader = response.body.getReader()
      try {
        while (true) {
          if (signal?.aborted) {
            await reader.cancel().catch(() => undefined)
            throw new DOMException('Download aborted', 'AbortError')
          }

          const { done, value } = await reader.read()
          if (done) break
          if (!value) continue
          await writable.write(value)
          loaded += value.byteLength
          onProgress?.({ loaded, total })
        }
      } finally {
        reader.releaseLock()
      }
    }

    await writable.close()
    const stored = await handle.getFile()
    const file = new File([stored], filename, {
      type: response.headers.get('content-type') || stored.type || undefined,
      lastModified: stored.lastModified,
    })

    return {
      file,
      storage: 'opfs',
      cleanup: async () => {
        await directory.removeEntry(storageName).catch(() => undefined)
      },
    }
  } catch (error) {
    await writable.abort().catch(() => undefined)
    await directory.removeEntry(storageName).catch(() => undefined)
    throw error
  }
}

async function streamResponseToMemory(
  response: Response,
  filename: string,
  contentType?: string,
  signal?: AbortSignal,
  onProgress?: (progress: BrowserLocalDownloadProgress) => void,
): Promise<BrowserLocalFile> {
  const total = Number(response.headers.get('content-length') || '0')
  const chunks: Uint8Array[] = []
  let loaded = 0

  if (!response.body) {
    const bytes = new Uint8Array(await response.arrayBuffer())
    chunks.push(bytes)
    loaded = bytes.byteLength
  } else {
    const reader = response.body.getReader()
    try {
      while (true) {
        if (signal?.aborted) {
          await reader.cancel().catch(() => undefined)
          throw new DOMException('Download aborted', 'AbortError')
        }
        const { done, value } = await reader.read()
        if (done) break
        if (!value) continue
        chunks.push(value)
        loaded += value.byteLength
        onProgress?.({ loaded, total })
      }
    } finally {
      reader.releaseLock()
    }
  }

  const blob = new Blob(chunks, {
    type: response.headers.get('content-type') || contentType || undefined,
  })
  const file = new File([blob], filename, { type: blob.type })
  onProgress?.({ loaded: file.size, total: total || file.size })
  return {
    file,
    storage: 'memory',
    cleanup: async () => undefined,
  }
}

export async function downloadToBrowserLocalFile({
  url,
  filename,
  contentType,
  signal,
  headers,
  onProgress,
}: DownloadToLocalFileOptions): Promise<BrowserLocalFile> {
  const response = await fetch(url, {
    method: 'GET',
    cache: 'no-store',
    signal,
    headers,
  })

  if (!response.ok) {
    throw new Error(`Download failed with HTTP ${response.status}`)
  }

  if (hasOpfs()) {
    try {
      return await streamResponseToOpfs(response, filename, signal, onProgress)
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      console.warn('[Galaxy Local] OPFS streaming failed, falling back to memory:', error)
    }
  }

  // A Response body cannot be consumed twice. If OPFS failed after consuming
  // bytes, retry the same URL for the memory fallback.
  if (response.bodyUsed) {
    const retry = await fetch(url, {
      method: 'GET',
      cache: 'no-store',
      signal,
      headers,
    })
    if (!retry.ok) throw new Error(`Download retry failed with HTTP ${retry.status}`)
    return streamResponseToMemory(retry, filename, contentType, signal, onProgress)
  }

  return streamResponseToMemory(response, filename, contentType, signal, onProgress)
}
