export const DAILYMOTION_HLS_ATTEMPTS = 3
const DAILYMOTION_BLOCKBUSTER_ALPHABET = 'bcdfghjklmnpqrstvwxyz'

export type DailymotionHlsFetchOptions = {
  id: string
  target: URL
  range?: string | null
  userAgent: string
}

export function retryableDailymotionStatus(status: number): boolean {
  return status === 403 || status === 408 || status === 429 || status >= 500
}

function randomLetters(minimum: number, maximum: number): string {
  const length = minimum + Math.floor(Math.random() * (maximum - minimum + 1))
  let value = ''
  for (let index = 0; index < length; index += 1) {
    value += DAILYMOTION_BLOCKBUSTER_ALPHABET[
      Math.floor(Math.random() * DAILYMOTION_BLOCKBUSTER_ALPHABET.length)
    ]
  }
  return value
}

export function dailymotionHlsHeaders(options: DailymotionHlsFetchOptions, attempt: number): Headers {
  const headers = new Headers({
    Accept: '*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'User-Agent': options.userAgent,
  })

  // Dailymotion/CDN filtering can key off otherwise irrelevant HTTP header
  // fingerprints. Add only locally-generated, meaningless names/values; never
  // forward arbitrary browser headers into the upstream request.
  const randomHeaderCount = 2 + Math.floor(Math.random() * 7)
  for (let index = 0; index < randomHeaderCount; index += 1) {
    headers.set(randomLetters(8, 16), randomLetters(8, 24))
  }

  if (attempt === 0) {
    headers.set('Referer', `https://www.dailymotion.com/video/${options.id}`)
    headers.set('Origin', 'https://www.dailymotion.com')
  } else {
    headers.set('Referer', 'https://www.dailymotion.com/')
    headers.set('Origin', 'https://www.dailymotion.com')
  }

  if (options.range && !options.target.pathname.toLowerCase().endsWith('.m3u8')) {
    headers.set('Range', options.range)
  }
  return headers
}

export async function fetchDailymotionHlsResource(options: DailymotionHlsFetchOptions): Promise<Response> {
  let lastResponse: Response | null = null
  let lastError: unknown = null

  for (let attempt = 0; attempt < DAILYMOTION_HLS_ATTEMPTS; attempt += 1) {
    try {
      const upstream = await fetch(options.target.toString(), {
        method: 'GET',
        headers: dailymotionHlsHeaders(options, attempt),
        redirect: 'follow',
        cache: 'no-store',
      })
      lastResponse = upstream
      if (!retryableDailymotionStatus(upstream.status) || attempt === DAILYMOTION_HLS_ATTEMPTS - 1) {
        return upstream
      }
      void upstream.body?.cancel()
    } catch (error) {
      lastError = error
      if (attempt === DAILYMOTION_HLS_ATTEMPTS - 1) break
    }
    await new Promise((resolve) => setTimeout(resolve, 100 * (attempt + 1)))
  }

  if (lastResponse) return lastResponse
  const detail = lastError instanceof Error ? lastError.message : String(lastError || 'unknown error')
  throw new Error(`Dailymotion HLS fetch failed after ${DAILYMOTION_HLS_ATTEMPTS} attempts: ${detail}`)
}
