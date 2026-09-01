import { NextResponse } from 'next/server';

import {
  LOCAL_ENGINE_GITHUB_URL,
  LOCAL_ENGINE_REQUIRED_VERSION,
} from '@/lib/local-engine';

const DOWNLOAD_NAME = 'GalaxyLocalEngine-Windows.zip';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const requestedVersion = new URL(request.url).searchParams.get('version')?.trim()
    || LOCAL_ENGINE_REQUIRED_VERSION;

  // This endpoint is an official-package relay, not a generic GitHub release
  // proxy. Only the exact version required by the running website is allowed.
  if (requestedVersion !== LOCAL_ENGINE_REQUIRED_VERSION) {
    return NextResponse.json(
      {
        success: false,
        error: `This website build requires Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}.`,
        requiredVersion: LOCAL_ENGINE_REQUIRED_VERSION,
      },
      {
        status: 400,
        headers: { 'Cache-Control': 'no-store' },
      },
    );
  }

  try {
    const upstream = await fetch(LOCAL_ENGINE_GITHUB_URL, {
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
          error: `Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION} package upstream returned HTTP ${upstream.status}`,
          requiredVersion: LOCAL_ENGINE_REQUIRED_VERSION,
          fallback: LOCAL_ENGINE_GITHUB_URL,
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
    headers.set('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0');
    headers.set('Pragma', 'no-cache');
    headers.set('Expires', '0');
    headers.set('X-Content-Type-Options', 'nosniff');
    headers.set('X-Galaxy-Download-Source', 'official-site-proxy');
    headers.set('X-Galaxy-Local-Engine-Version', LOCAL_ENGINE_REQUIRED_VERSION);

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
        requiredVersion: LOCAL_ENGINE_REQUIRED_VERSION,
        fallback: LOCAL_ENGINE_GITHUB_URL,
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
