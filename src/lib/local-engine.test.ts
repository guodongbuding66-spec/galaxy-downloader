import { describe, expect, it } from 'vitest';

import {
  buildLocalDesktopEngineUri,
  detectLocalProcessingCapabilities,
  resolveLocalDesktopVideoQuality,
  resolveLocalEngineCollectionMode,
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

describe('desktop yt-dlp quality selection', () => {
  it('prefers the parser height over a numeric format id', () => {
    expect(resolveLocalDesktopVideoQuality({
      quality: '137',
      label: 'MP4 · H264',
      height: 1080,
    })).toBe('1080');
  });

  it('reads an explicit resolution label when height metadata is absent', () => {
    expect(resolveLocalDesktopVideoQuality({
      quality: 'dash-video',
      label: 'Full HD · 1080p · 60fps',
    })).toBe('1080');
  });

  it('accepts known resolution presets but does not treat arbitrary format ids as heights', () => {
    expect(resolveLocalDesktopVideoQuality({ quality: '720' })).toBe('720');
    expect(resolveLocalDesktopVideoQuality({ quality: '1440p' })).toBe('1440');
    expect(resolveLocalDesktopVideoQuality({ quality: '137' })).toBe('best');
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
      collectionMode: 'selected',
      selectedItems: [2, 4, 4],
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
    expect(parsed.searchParams.get('collection')).toBe('selected');
    expect(parsed.searchParams.get('items')).toBe('2,4');
    expect(parsed.searchParams.get('playlist')).toBe('0');
  });

  it('uses single-item safe defaults without cookies or side options', () => {
    const parsed = new URL(buildLocalDesktopEngineUri({ sourceUrl: 'https://example.com/video' }));
    expect(parsed.searchParams.get('video')).toBe('best');
    expect(parsed.searchParams.get('audio')).toBe('best');
    expect(parsed.searchParams.get('include_audio')).toBe('1');
    expect(parsed.searchParams.get('subtitle')).toBe('0');
    expect(parsed.searchParams.get('cover')).toBe('0');
    expect(parsed.searchParams.get('browser')).toBe('none');
    expect(parsed.searchParams.get('collection')).toBe('single');
    expect(parsed.searchParams.get('playlist')).toBe('0');
  });

  it('supports entire collections while keeping the legacy playlist marker', () => {
    const parsed = new URL(buildLocalDesktopEngineUri({
      sourceUrl: 'https://example.com/collection',
      collectionMode: 'all',
    }));
    expect(parsed.searchParams.get('collection')).toBe('all');
    expect(parsed.searchParams.get('playlist')).toBe('1');
    expect(parsed.searchParams.has('items')).toBe(false);
  });

  it('downgrades an empty selected collection to a safe single item', () => {
    expect(resolveLocalEngineCollectionMode({ collectionMode: 'selected', selectedItems: [] })).toBe('single');
  });
});
