export const VIMEO_CONTROL_TIMEOUT_MS = 5_500
export const VIMEO_CONTROL_ATTEMPTS = 2

export type VimeoControlPage = {
  ok: boolean
  status: number
  text: string
}

class VimeoControlHttpError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
  ) {
    super(message)
    this.name = 'VimeoControlHttpError'
  }
}

export function isRetryableVimeoControlStatus(status: number): boolean {
  return status === 408 || status === 425 || status === 429 || status >= 500
}

function shouldRetryVimeoControlError(error: unknown): boolean {
  if (error instanceof VimeoControlHttpError) return error.retryable
  return error instanceof Error
}

export async function runVimeoControlRequest<T>(
  label: string,
  operation: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  let lastError: unknown = null

  for (let attempt = 1; attempt <= VIMEO_CONTROL_ATTEMPTS; attempt += 1) {
    try {
      return await operation(AbortSignal.timeout(VIMEO_CONTROL_TIMEOUT_MS))
    } catch (error) {
      lastError = error
      if (!shouldRetryVimeoControlError(error) || attempt >= VIMEO_CONTROL_ATTEMPTS) break
      await new Promise((resolve) => setTimeout(resolve, 150 * attempt))
    }
  }

  const detail = lastError instanceof Error ? lastError.message : String(lastError || 'unknown error')
  throw new Error(`${label} failed: ${detail}`)
}

export async function fetchVimeoControlJson<T>(
  url: string,
  headers: HeadersInit,
  label = 'Vimeo JSON request',
): Promise<T> {
  return runVimeoControlRequest(label, async (signal) => {
    const response = await fetch(url, {
      headers,
      redirect: 'follow',
      cache: 'no-store',
      signal,
    })

    if (!response.ok) {
      void response.body?.cancel()
      throw new VimeoControlHttpError(
        `HTTP ${response.status}`,
        isRetryableVimeoControlStatus(response.status),
      )
    }

    return response.json() as Promise<T>
  })
}

export async function fetchVimeoControlPage(
  url: string,
  headers: HeadersInit,
  label = 'Vimeo player request',
): Promise<VimeoControlPage> {
  return runVimeoControlRequest(label, async (signal) => {
    const response = await fetch(url, {
      headers,
      redirect: 'follow',
      cache: 'no-store',
      signal,
    })

    if (!response.ok && isRetryableVimeoControlStatus(response.status)) {
      void response.body?.cancel()
      throw new VimeoControlHttpError(`HTTP ${response.status}`, true)
    }

    const text = response.ok ? await response.text() : ''
    return { ok: response.ok, status: response.status, text }
  })
}
