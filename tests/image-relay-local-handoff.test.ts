import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchImageBlobCandidates,
  ImageRelayLimitError,
} from '@/components/downloader/result-card-utils'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('oversized image relay handoff', () => {
  it('stops fallback candidates when the bounded public relay returns 413', async () => {
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ error: 'Image exceeds 32 MiB proxy limit' }),
      {
        status: 413,
        headers: { 'Content-Type': 'application/json' },
      },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchImageBlobCandidates([
      '/api/proxy-image?url=https%3A%2F%2Fcdn.example%2Foriginal.jpg&mode=download',
      'https://cdn.example/original.jpg',
    ])).rejects.toBeInstanceOf(ImageRelayLimitError)

    // The direct-browser fallback is intentionally not attempted. Large files
    // must be handed to Local Engine instead of consuming browser memory or
    // bypassing the server relay safety policy.
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps ordinary retry behavior for non-limit upstream failures', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('temporary failure', { status: 502 }))
      .mockResolvedValueOnce(new Response(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), {
        status: 200,
        headers: { 'Content-Type': 'image/jpeg' },
      }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await fetchImageBlobCandidates([
      '/api/proxy-image?url=https%3A%2F%2Fcdn.example%2Fphoto.jpg&mode=download',
      'https://cdn.example/photo.jpg',
    ])

    expect(result.blob.type).toBe('image/jpeg')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
