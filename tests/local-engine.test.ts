import { describe, expect, it } from 'vitest'

import {
  LOCAL_ENGINE_GITHUB_URL,
  LOCAL_ENGINE_RELEASE_TAG,
  LOCAL_ENGINE_RELEASE_URL,
  LOCAL_ENGINE_REQUIRED_VERSION,
  buildLocalDesktopEngineUri,
  canProcessMediaLocally,
  detectLocalProcessingCapabilities,
  normalizeLocalEngineDanmakuFormats,
  shouldUseFileBackedInputs,
} from '../src/lib/local-engine'

describe('local media engine capabilities', () => {
  it('uses the multithread profile only with SharedArrayBuffer and cross-origin isolation', () => {
    const capabilities = detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: true,
      navigator: {
        storage: { getDirectory() {} },
        serviceWorker: {},
        wakeLock: {},
      },
    })

    expect(capabilities).toEqual({
      webAssembly: true,
      sharedArrayBuffer: true,
      crossOriginIsolated: true,
      multiThreadFFmpeg: true,
      opfs: true,
      serviceWorker: true,
      wakeLock: true,
      profile: 'multi-thread',
    })
    expect(canProcessMediaLocally(capabilities)).toBe(true)
    expect(shouldUseFileBackedInputs(capabilities)).toBe(true)
  })

  it('falls back to the single-thread profile without cross-origin isolation', () => {
    const capabilities = detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: false,
      navigator: {},
    })

    expect(capabilities.profile).toBe('single-thread')
    expect(capabilities.multiThreadFFmpeg).toBe(false)
    expect(canProcessMediaLocally(capabilities)).toBe(true)
    expect(shouldUseFileBackedInputs(capabilities)).toBe(false)
  })

  it('reports unsupported browsers without throwing', () => {
    const capabilities = detectLocalProcessingCapabilities({})

    expect(capabilities).toEqual({
      webAssembly: false,
      sharedArrayBuffer: false,
      crossOriginIsolated: false,
      multiThreadFFmpeg: false,
      opfs: false,
      serviceWorker: false,
      wakeLock: false,
      profile: 'unsupported',
    })
    expect(canProcessMediaLocally(capabilities)).toBe(false)
  })

  it('pins the website and GitHub mirror to the exact required Local Engine release', () => {
    const expectedRelease = '0.15.0'
    expect(LOCAL_ENGINE_REQUIRED_VERSION).toBe(expectedRelease)
    expect(LOCAL_ENGINE_RELEASE_TAG).toBe(`local-engine-v${expectedRelease}`)
    expect(LOCAL_ENGINE_RELEASE_URL).toContain(`version=${expectedRelease}`)
    expect(LOCAL_ENGINE_GITHUB_URL).toContain(`/releases/download/local-engine-v${expectedRelease}/`)
    expect(LOCAL_ENGINE_GITHUB_URL).not.toContain('/releases/latest/')
  })

  it('normalizes danmaku formats and carries them through the desktop protocol only when enabled', () => {
    expect(normalizeLocalEngineDanmakuFormats(['ASS', 'json', 'ass', 'srt'])).toEqual(['ass', 'json'])
    expect(normalizeLocalEngineDanmakuFormats([])).toEqual(['xml'])

    const enabled = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://www.bilibili.com/video/BV1demo',
      includeDanmaku: true,
      danmakuFormats: ['ass', 'json'],
    }))
    expect(enabled.searchParams.get('danmaku')).toBe('1')
    expect(enabled.searchParams.get('danmaku_formats')).toBe('ass,json')

    const defaultFormats = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://www.bilibili.com/video/BV1demo',
      includeDanmaku: true,
    }))
    expect(defaultFormats.searchParams.get('danmaku_formats')).toBe('xml')

    const disabled = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://www.bilibili.com/video/BV1demo',
      includeDanmaku: false,
      danmakuFormats: ['ass', 'json'],
    }))
    expect(disabled.searchParams.get('danmaku')).toBe('0')
    expect(disabled.searchParams.get('danmaku_formats')).toBeNull()
  })

  it('keeps cover embedding and cover sidecar protocol options independent', () => {
    const defaults = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
    }))
    expect(defaults.searchParams.get('cover')).toBe('0')
    expect(defaults.searchParams.get('cover_sidecar')).toBe('0')

    const sidecarOnly = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
      includeCover: false,
      keepCoverSidecar: true,
    }))
    expect(sidecarOnly.searchParams.get('cover')).toBe('0')
    expect(sidecarOnly.searchParams.get('cover_sidecar')).toBe('1')

    const embedOnly = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
      includeCover: true,
      keepCoverSidecar: false,
    }))
    expect(embedOnly.searchParams.get('cover')).toBe('1')
    expect(embedOnly.searchParams.get('cover_sidecar')).toBe('0')

    const both = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
      includeCover: true,
      keepCoverSidecar: true,
    }))
    expect(both.searchParams.get('cover')).toBe('1')
    expect(both.searchParams.get('cover_sidecar')).toBe('1')
  })

  it('keeps NFO protocol opt-in explicit and independent from cover sidecars', () => {
    const defaults = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
    }))
    expect(defaults.searchParams.get('nfo')).toBe('0')
    expect(defaults.searchParams.get('cover')).toBe('0')
    expect(defaults.searchParams.get('cover_sidecar')).toBe('0')

    const nfoOnly = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
      includeNfo: true,
      includeCover: false,
      keepCoverSidecar: false,
    }))
    expect(nfoOnly.searchParams.get('nfo')).toBe('1')
    expect(nfoOnly.searchParams.get('cover')).toBe('0')
    expect(nfoOnly.searchParams.get('cover_sidecar')).toBe('0')

    const coversWithoutNfo = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
      includeNfo: false,
      includeCover: true,
      keepCoverSidecar: true,
    }))
    expect(coversWithoutNfo.searchParams.get('nfo')).toBe('0')
    expect(coversWithoutNfo.searchParams.get('cover')).toBe('1')
    expect(coversWithoutNfo.searchParams.get('cover_sidecar')).toBe('1')

    const allSidecars = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/video',
      includeNfo: true,
      includeCover: true,
      keepCoverSidecar: true,
    }))
    expect(allSidecars.searchParams.get('nfo')).toBe('1')
    expect(allSidecars.searchParams.get('cover')).toBe('1')
    expect(allSidecars.searchParams.get('cover_sidecar')).toBe('1')
  })
})