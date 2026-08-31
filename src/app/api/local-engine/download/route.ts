import { NextResponse } from 'next/server';

const GITHUB_LATEST =
  'https://github.com/guodongbuding66-spec/galaxy-downloader/releases/latest/download/GalaxyLocalEngine-Windows.zip';

const DOWNLOAD_NAME = 'GalaxyLocalEngine-Windows.zip';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const upstream = await fetch(GITHUB_LATEST, {
      redirect: 'follow',
      cache: 'no-store',
      headers: {
        Accept: 'application/octet-stream,*/*',
        'User-Agent': 'Galaxy-Downloader-Release-Proxy/1.0',
      },
    });

    if (!upstream.ok || !upstream.body) {
      return NextResponse.json(
        {
          success: false,
          error: `Local Engine package upstream returned HTTP ${upstream.status}`,
          fallback: GITHUB_LATEST,
        },
        {
          status: 502,
          headers: {
            'Cache-Control': 'no-store',
          },
        },
      );
    }

    const headers = new Headers();
    headers.set('Content-Type', upstream.headers.get('content-type') || 'application/zip');
    headers.set('Content-Disposition', `attachment; filename="${DOWNLOAD_NAME}"`);
    headers.set('Cache-Control', 'public, max-age=3600, s-maxage=3600');
    headers.set('X-Content-Type-Options', 'nosniff');
    headers.set('X-Galaxy-Download-Source', 'official-site-proxy');

    const contentLength = upstream.headers.get('content-length');
    if (contentLength) headers.set('Content-Length', contentLength);
    const etag = upstream.headers.get('etag');
    if (etag) headers.set('ETag', etag);
    const lastModified = upstream.headers.get('last-modified');
    if (lastModified) headers.set('Last-Modified', lastModified);

    return new Response(upstream.body, {
      status: 200,
      headers,
    });
  } catch (error) {
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : String(error),
        fallback: GITHUB_LATEST,
      },
      {
        status: 502,
        headers: {
          'Cache-Control': 'no-store',
        },
      },
    );
  }
}
