import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function loadUtils({ primary, container }: { primary: string; container?: string }) {
  vi.stubEnv('NODE_ENV', 'production');
  vi.stubEnv('NEXT_PUBLIC_API_BASE_URL', primary);
  if (container) {
    vi.stubEnv('NEXT_PUBLIC_CONTAINER_API_BASE_URL', container);
  } else {
    vi.stubEnv('NEXT_PUBLIC_CONTAINER_API_BASE_URL', '');
  }
  vi.resetModules();
  return import('../src/lib/utils.ts');
}

describe('optional first-party media backend routing', () => {
  it('keeps the existing shared download endpoint when no Container backend is configured', async () => {
    const { getProxiedDownloadUrl } = await loadUtils({
      primary: 'https://shared.example',
    });
    const sharedDownload = 'https://shared.example/api/download?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc&type=video&quality=2160&formatId=137';

    expect(getProxiedDownloadUrl(sharedDownload)).toBe(sharedDownload);
  });

  it('reroutes a source-aware shared download to the Container and preserves selectors', async () => {
    const { getProxiedDownloadUrl } = await loadUtils({
      primary: 'https://shared.example',
      container: 'https://container.example',
    });
    const sharedDownload = 'https://shared.example/api/download?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc&type=video&quality=2160&formatId=137';

    const rewritten = new URL(getProxiedDownloadUrl(sharedDownload));
    expect(rewritten.origin).toBe('https://container.example');
    expect(rewritten.pathname).toBe('/api/download');
    expect(rewritten.searchParams.get('url')).toBe('https://www.youtube.com/watch?v=abc');
    expect(rewritten.searchParams.get('type')).toBe('video');
    expect(rewritten.searchParams.get('quality')).toBe('2160');
    expect(rewritten.searchParams.get('formatId')).toBe('137');
  });

  it('does not rewrite a plain CDN URL directly to the Container', async () => {
    const { getProxiedDownloadUrl } = await loadUtils({
      primary: 'https://shared.example',
      container: 'https://container.example',
    });
    const media = 'https://cdn.example/path/video.mp4?token=abc';

    const proxied = new URL(getProxiedDownloadUrl(media));
    expect(proxied.origin).toBe('https://shared.example');
    expect(proxied.pathname).toBe('/api/download');
    expect(proxied.searchParams.get('url')).toBe(media);
  });

  it('never nests an already configured Container download endpoint', async () => {
    const { getProxiedDownloadUrl } = await loadUtils({
      primary: 'https://shared.example',
      container: 'https://container.example',
    });
    const containerDownload = 'https://container.example/api/download?url=https%3A%2F%2Fexample.com%2Fvideo&type=video&quality=best';

    expect(getProxiedDownloadUrl(containerDownload)).toBe(containerDownload);
  });
});
