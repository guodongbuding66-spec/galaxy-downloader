import { describe, expect, it } from 'vitest';

import {
  buildLocalDesktopEngineUri,
  detectLocalProcessingCapabilities,
  shouldUseFileBackedInputs,
} from './local-engine';

describe('local engine capabilities', () => {
  it('detects multi-thread local media support only when isolation is available', () => {
    const capabilities = detectLocalProcessingCapabilities({
      WebAssembly: {},
      SharedArrayBuffer: {},
      crossOriginIsolated: true,
      navigator: {
        storage: { getDirectory: () => undefined },
        serviceWorker: {},
        wakeLock: {},
      },
    });

    expect(capabilities.profile).toBe('multi-thread');
    expect(capabilities.multiThreadFFmpeg).toBe(true);
    expect(capabilities.opfs).toBe(true);
    expect(shouldUseFileBackedInputs(capabilities)).toBe(true);
  });
});

describe('desktop yt-dlp protocol', () => {
  it('preserves source query parameters and selected local options', () => {
    const uri = buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/watch?v=abc123&list=demo',
      videoQuality: '1080p',
      audioQuality: '192',
      includeAudio: true,
      includeSubtitle: true,
      subtitleLanguage: 'zh-Hans',
      includeCover: true,
      browser: 'edge',
    });

    const parsed = new URL(uri);
    expect(parsed.protocol).toBe('galaxy-downloader:');
    expect(parsed.hostname).toBe('download');
    expect(parsed.searchParams.get('url')).toBe('https://example.com/watch?v=abc123&list=demo');
    expect(parsed.searchParams.get('video')).toBe('1080p');
    expect(parsed.searchParams.get('audio')).toBe('192');
    expect(parsed.searchParams.get('include_audio')).toBe('1');
    expect(parsed.searchParams.get('subtitle')).toBe('1');
    expect(parsed.searchParams.get('subtitle_lang')).toBe('zh-Hans');
    expect(parsed.searchParams.get('cover')).toBe('1');
    expect(parsed.searchParams.get('browser')).toBe('edge');
  });

  it('uses safe defaults without browser cookies', () => {
    const parsed = new URL(buildLocalDesktopEngineUri({ sourceUrl: 'https://example.com/video' }));
    expect(parsed.searchParams.get('video')).toBe('best');
    expect(parsed.searchParams.get('audio')).toBe('best');
    expect(parsed.searchParams.get('include_audio')).toBe('1');
    expect(parsed.searchParams.get('subtitle')).toBe('0');
    expect(parsed.searchParams.get('cover')).toBe('0');
    expect(parsed.searchParams.get('browser')).toBe('none');
    expect(parsed.searchParams.get('playlist')).toBe('0');
  });
});
