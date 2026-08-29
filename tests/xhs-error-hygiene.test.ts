import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    resetXhsResolverCircuitState,
    xhsDownloadResponse,
    xhsParseResponse,
} from '../container-backend/src/xhs-resolver';

const sourceUrl = 'https://www.xiaohongshu.com/explore/error-hygiene';

function videoPayload(mediaUrl = 'https://sns-video-bd.xhscdn.com/video.mp4') {
    return {
        message: 'ok',
        data: {
            作品ID: 'error-hygiene',
            作品标题: 'Error hygiene video',
            作品类型: '视频',
            媒体: [
                {
                    序号: 1,
                    类型: '视频',
                    地址: mediaUrl,
                    扩展名: 'mp4',
                },
            ],
        },
    };
}

afterEach(() => {
    vi.restoreAllMocks();
    resetXhsResolverCircuitState();
});

describe('XHS public error hygiene', () => {
    it('redacts resolver-provided upstream diagnostics', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
            Response.json({
                message: 'private resolver detail host=resolver.internal token=super-secret',
            }, { status: 503 }),
        );

        const request = new Request(`https://media.example.com/api/parse?url=${encodeURIComponent(sourceUrl)}`);
        const response = await xhsParseResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
        }, 'xhs-redact-1');
        const body = await response.json() as { error: string; code: string };

        expect(response.status).toBe(502);
        expect(body.code).toBe('PARSE_FAILED');
        expect(body.error).toBe('XHS provider parsing failed upstream.');
        expect(JSON.stringify(body)).not.toContain('resolver.internal');
        expect(JSON.stringify(body)).not.toContain('super-secret');
        expect(response.headers.get('cache-control')).toBe('no-store');
    });

    it('redacts network exception text that may contain internal addresses', async () => {
        vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(
            new Error('connect ECONNREFUSED http://10.0.0.8:8080 token=private-value'),
        );

        const request = new Request(`https://media.example.com/api/parse?url=${encodeURIComponent(sourceUrl)}`);
        const response = await xhsParseResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
        }, 'xhs-redact-2');
        const text = await response.text();

        expect(response.status).toBe(502);
        expect(text).toContain('XHS provider parsing failed upstream.');
        expect(text).not.toContain('10.0.0.8');
        expect(text).not.toContain('private-value');
    });

    it('returns stable 429 retry semantics without echoing resolver text', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
            Response.json({ message: 'quota account=private-customer-id' }, { status: 429 }),
        );

        const request = new Request(`https://media.example.com/api/parse?url=${encodeURIComponent(sourceUrl)}`);
        const response = await xhsParseResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
            XHS_RESOLVER_FAILURE_THRESHOLD: '5',
        }, 'xhs-rate-limited');
        const body = await response.json() as { error: string };

        expect(response.status).toBe(429);
        expect(response.headers.get('retry-after')).toBe('60');
        expect(body.error).toBe('XHS provider is rate limited. Please retry later.');
        expect(JSON.stringify(body)).not.toContain('private-customer-id');
    });

    it('uses the open-circuit cooldown as Retry-After', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
            Response.json({ message: 'internal outage detail' }, { status: 503 }),
        );
        const runtime = {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
            XHS_RESOLVER_FAILURE_THRESHOLD: '1',
            XHS_RESOLVER_COOLDOWN_MS: '60000',
        };
        const request = new Request(`https://media.example.com/api/parse?url=${encodeURIComponent(sourceUrl)}`);

        const first = await xhsParseResponse(request, sourceUrl, runtime, 'xhs-circuit-1');
        const second = await xhsParseResponse(request, sourceUrl, runtime, 'xhs-circuit-2');
        const secondBody = await second.json() as { error: string };
        const retryAfter = Number.parseInt(second.headers.get('retry-after') || '0', 10);

        expect(first.status).toBe(502);
        expect(second.status).toBe(503);
        expect(secondBody.error).toBe('XHS provider is temporarily unavailable.');
        expect(retryAfter).toBeGreaterThan(0);
        expect(retryAfter).toBeLessThanOrEqual(60);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('redacts untrusted media URLs from download failures', async () => {
        vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
            Response.json(videoPayload('https://evil.example.com/video.mp4?token=cdn-secret')),
        );

        const request = new Request(
            `https://media.example.com/api/download?url=${encodeURIComponent(sourceUrl)}&type=video`,
        );
        const response = await xhsDownloadResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
        }, 'xhs-download-redact');
        const text = await response!.text();

        expect(response?.status).toBe(502);
        expect(text).toContain('XHS provider download failed upstream.');
        expect(text).not.toContain('evil.example.com');
        expect(text).not.toContain('cdn-secret');
    });

    it('keeps the stream-size policy actionable without exposing internal limits', async () => {
        vi.spyOn(globalThis, 'fetch')
            .mockResolvedValueOnce(Response.json(videoPayload()))
            .mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3, 4]), {
                status: 200,
                headers: {
                    'Content-Type': 'video/mp4',
                    'Content-Length': '4',
                },
            }));

        const request = new Request(
            `https://media.example.com/api/download?url=${encodeURIComponent(sourceUrl)}&type=video`,
        );
        const response = await xhsDownloadResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
            XHS_MAX_STREAM_BYTES: '3',
        }, 'xhs-size-limit');
        const body = await response!.json() as { error: string };

        expect(response?.status).toBe(413);
        expect(body.error).toBe('XHS media exceeds the configured size limit.');
    });
});
