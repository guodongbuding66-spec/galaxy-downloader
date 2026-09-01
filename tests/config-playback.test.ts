import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

async function loadConfig({ primary, container }: { primary: string; container?: string }) {
  vi.stubEnv('NODE_ENV', 'production')
  vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', primary)
  vi.stubEnv('NEXT_PUBLIC_CONTAINER_API_BASE_URL', container || '')
  vi.resetModules()
  return import('../src/lib/config.ts')
}

describe('playback backend routing', () => {
  it('uses the range-aware Container /api/play endpoint when configured', async () => {
    const { API_ENDPOINTS } = await loadConfig({
      primary: 'https://shared.example',
      container: 'https://container.example',
    })

    expect(API_ENDPOINTS.unified.play).toBe('https://container.example/api/play')
    expect(API_ENDPOINTS.unified.download).toBe('https://shared.example/api/download')
  })

  it('preserves the existing shared playback behavior when Container is absent', async () => {
    const { API_ENDPOINTS } = await loadConfig({
      primary: 'https://shared.example',
    })

    expect(API_ENDPOINTS.unified.play).toBe('https://shared.example/api/download')
  })

  it('ignores an invalid Container URL instead of generating a malformed playback URL', async () => {
    const { API_ENDPOINTS } = await loadConfig({
      primary: 'https://shared.example',
      container: 'javascript:alert(1)',
    })

    expect(API_ENDPOINTS.unified.play).toBe('https://shared.example/api/download')
  })
})
