import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    detectXhsDetailSchema,
    isAllowedXhsMediaUrl,
    isXhsSourceUrl,
    limitStreamBytes,
    normalizeXhsDetail,
    xhsDownloadResponse,
    xhsParseResponse,
    xhsResolverMode,
} from '../container-backend/src/xhs-resolver';

const sourceUrl = 'https://www.xiaohongshu.com/explore/abc';

function videoResolverPayload() {
    return {
        message: '作品信息解析完成',
        data: {
            作品ID: 'abc',
            作品标题: '测试视频',
            作品描述: '描述',
            作品类型: '视频',
            作者: {
                作者ID: 'author-1',
                作者昵称: '作者',
                作者链接: 'https://www.xiaohongshu.com/user/profile/author-1',
            },
            媒体: [
                {
                    序号: 1,
                    类型: '视频',
                    地址: 'https://sns-video-bd.xhscdn.com/video.mp4',
                    扩展名: 'mp4',
                    预览地址: 'https://sns-webpic-qc.xhscdn.com/cover.jpg',
                },
            ],
        },
        files: [],
        skipped: false,
    };
}

function legacyVideoResolverPayload() {
    return {
        message: '获取小红书作品数据成功',
        params: {
            url: sourceUrl,
            download: false,
            index: null,
            cookie: null,
            proxy: null,
            skip: false,
        },
        data: {
            作品ID: 'abc',
            作品标题: 'Legacy 视频',
            作品描述: 'Legacy 描述',
            作品类型: '视频',
            作者昵称: 'Legacy 作者',
            作者ID: 'author-legacy',
            下载地址: ['https://sns-video-bd.xhscdn.com/legacy-video.mp4'],
            动图地址: [null],
        },
    };
}

afterEach(() => {
    vi.restoreAllMocks();
});

describe('XHS resolver provider', () => {
    it('recognizes full and short Xiaohongshu links only', () => {
        expect(isXhsSourceUrl(sourceUrl)).toBe(true);
        expect(isXhsSourceUrl('https://xhslink.com/a/abc')).toBe(true);
        expect(isXhsSourceUrl('https://sub.xhslink.com/a/abc')).toBe(true);
        expect(isXhsSourceUrl('https://example.com/xiaohongshu.com/video')).toBe(false);
        expect(isXhsSourceUrl('not a url')).toBe(false);
    });

    it('normalizes a resolver video into a first-party download route', () => {
        const result = normalizeXhsDetail(videoResolverPayload().data, sourceUrl, 'https://media.example.com');

        expect(detectXhsDetailSchema(videoResolverPayload().data)).toBe('media-v1');
        expect(result.platform).toBe('xiaohongshu');
        expect(result.resolverSchema).toBe('media-v1');
        expect(result.noteType).toBe('video');
        expect(result.kind).toBe('video');
        expect(result.cover).toBe('https://sns-webpic-qc.xhscdn.com/cover.jpg');
        expect(result.originDownloadVideoUrl).toBeNull();
        expect(result.downloadVideoUrl).toBe(
            'https://media.example.com/api/download?url=https%3A%2F%2Fwww.xiaohongshu.com%2Fexplore%2Fabc&type=video&quality=best',
        );
        expect(result.mediaActions).toEqual({
            video: 'direct-download',
            audio: 'extract-audio',
        });
        expect(result.qualityOptions).toEqual([
            expect.objectContaining({
                quality: 'best',
                ext: 'mp4',
                downloadUrl: result.downloadVideoUrl,
            }),
        ]);
    });

    it('auto-detects and normalizes the legacy server resolver schema', () => {
        const legacy = legacyVideoResolverPayload();
        const result = normalizeXhsDetail(legacy.data, sourceUrl, 'https://media.example.com');

        expect(detectXhsDetailSchema(legacy.data)).toBe('download-address-v1');
        expect(result.resolverSchema).toBe('download-address-v1');
        expect(result.title).toBe('Legacy 视频');
        expect(result.author).toBe('Legacy 作者');
        expect(result.noteType).toBe('video');
        expect(result.kind).toBe('video');
        expect(result.qualityOptions).toEqual([
            expect.objectContaining({ quality: 'best', ext: 'mp4' }),
        ]);
    });

    it('normalizes image notes without inventing video media', () => {
        const imageSourceUrl = 'https://www.xiaohongshu.com/explore/images';
        const result = normalizeXhsDetail({
            作品标题: '图文笔记',
            作品类型: '图文',
            媒体: [
                {
                    序号: 1,
                    类型: '图片',
                    地址: 'https://sns-webpic-qc.xhscdn.com/1.jpg',
                    扩展名: 'jpg',
                },
                {
                    序号: 2,
                    类型: '图片',
                    地址: 'https://sns-webpic-qc.xhscdn.com/2.webp',
                    扩展名: 'webp',
                },
            ],
        }, imageSourceUrl, 'https://media.example.com');

        expect(result.noteType).toBe('image');
        expect(result.kind).toBe('image');
        expect(result.downloadVideoUrl).toBeNull();
        expect(result.downloadAudioUrl).toBeNull();
        expect(result.images).toEqual([
            {
                index: 1,
                url: 'https://sns-webpic-qc.xhscdn.com/1.jpg',
                downloadUrl: 'https://sns-webpic-qc.xhscdn.com/1.jpg',
            },
            {
                index: 2,
                url: 'https://sns-webpic-qc.xhscdn.com/2.webp',
                downloadUrl: 'https://sns-webpic-qc.xhscdn.com/2.webp',
            },
        ]);
    });

    it('normalizes legacy image-address arrays as image notes', () => {
        const imageSourceUrl = 'https://www.xiaohongshu.com/explore/legacy-images';
        const detail = {
            作品标题: 'Legacy 图集',
            作品类型: '图集',
            作者昵称: 'Legacy 作者',
            下载地址: [
                'https://sns-webpic-qc.xhscdn.com/legacy-1.jpg',
                'https://sns-webpic-qc.xhscdn.com/legacy-2.webp',
            ],
            动图地址: ['NaN', 'NaN'],
        };
        const result = normalizeXhsDetail(detail, imageSourceUrl, 'https://media.example.com');

        expect(detectXhsDetailSchema(detail)).toBe('download-address-v1');
        expect(result.noteType).toBe('image');
        expect(result.images).toEqual([
            {
                index: 1,
                url: 'https://sns-webpic-qc.xhscdn.com/legacy-1.jpg',
                downloadUrl: 'https://sns-webpic-qc.xhscdn.com/legacy-1.jpg',
            },
            {
                index: 2,
                url: 'https://sns-webpic-qc.xhscdn.com/legacy-2.webp',
                downloadUrl: 'https://sns-webpic-qc.xhscdn.com/legacy-2.webp',
            },
        ]);
    });

    it('allowlists XHS media hosts and supports operator-controlled suffixes', () => {
        expect(isAllowedXhsMediaUrl('https://sns-video-bd.xhscdn.com/video.mp4')).toBe(true);
        expect(isAllowedXhsMediaUrl('https://www.xiaohongshu.com/media/video.mp4')).toBe(true);
        expect(isAllowedXhsMediaUrl('https://evil.example.com/video.mp4')).toBe(false);
        expect(isAllowedXhsMediaUrl('http://127.0.0.1/video.mp4', {
            XHS_MEDIA_HOST_SUFFIXES: '127.0.0.1',
        })).toBe(false);
        expect(isAllowedXhsMediaUrl('https://media.example-cdn.com/video.mp4', {
            XHS_MEDIA_HOST_SUFFIXES: 'example-cdn.com',
        })).toBe(true);
    });

    it('hard-limits a streaming response even without Content-Length', async () => {
        const withinLimit = new ReadableStream<Uint8Array>({
            start(controller) {
                controller.enqueue(new Uint8Array([1, 2]));
                controller.enqueue(new Uint8Array([3, 4]));
                controller.close();
            },
        });
        const accepted = await new Response(limitStreamBytes(withinLimit, 4)).arrayBuffer();
        expect(accepted.byteLength).toBe(4);

        const overLimit = new ReadableStream<Uint8Array>({
            start(controller) {
                controller.enqueue(new Uint8Array([1, 2]));
                controller.enqueue(new Uint8Array([3, 4]));
                controller.close();
            },
        });
        await expect(new Response(limitStreamBytes(overLimit, 3)).arrayBuffer())
            .rejects.toThrow('XHS media exceeded the 3 byte stream limit');
    });

    it('sends the stable resolver contract and optional Bearer token', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
            Response.json(videoResolverPayload()),
        );

        const request = new Request(`https://media.example.com/api/parse?url=${encodeURIComponent(sourceUrl)}`);
        const response = await xhsParseResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
            XHS_RESOLVER_TOKEN: 'secret-token',
        }, 'req-1');
        const payload = await response.json() as { success: boolean; data: Record<string, unknown>; details?: Record<string, unknown> };

        expect(response.status).toBe(200);
        expect(payload.success).toBe(true);
        expect(payload.data.platform).toBe('xiaohongshu');
        expect(payload.details?.schema).toBe('media-v1');
        expect(fetchMock).toHaveBeenCalledTimes(1);

        const [resolverUrl, init] = fetchMock.mock.calls[0];
        expect(String(resolverUrl)).toBe('https://resolver.example.com/xhs/detail');
        expect(init?.method).toBe('POST');
        expect(new Headers(init?.headers).get('authorization')).toBe('Bearer secret-token');
        expect(JSON.parse(String(init?.body))).toEqual({ url: sourceUrl, download: false });
    });

    it('re-resolves video, forwards Range and streams only an allowlisted CDN', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch')
            .mockResolvedValueOnce(Response.json(videoResolverPayload()))
            .mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3]), {
                status: 206,
                headers: {
                    'Content-Type': 'video/mp4',
                    'Content-Length': '3',
                    'Content-Range': 'bytes 0-2/100',
                    'Accept-Ranges': 'bytes',
                },
            }));

        const request = new Request(
            `https://media.example.com/api/download?url=${encodeURIComponent(sourceUrl)}&type=video&quality=best`,
            { headers: { Range: 'bytes=0-2' } },
        );
        const response = await xhsDownloadResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com/xhs/detail',
            XHS_MAX_STREAM_BYTES: '10',
        }, 'req-2');

        expect(response).not.toBeNull();
        expect(response?.status).toBe(206);
        expect(response?.headers.get('x-galaxy-provider')).toBe('xhs-resolver');
        expect(response?.headers.get('x-max-stream-bytes')).toBe('10');
        expect(new Uint8Array(await response!.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
        expect(fetchMock).toHaveBeenCalledTimes(2);

        const [mediaUrl, mediaInit] = fetchMock.mock.calls[1];
        expect(String(mediaUrl)).toBe('https://sns-video-bd.xhscdn.com/video.mp4');
        expect(new Headers(mediaInit?.headers).get('range')).toBe('bytes=0-2');
        expect(new Headers(mediaInit?.headers).get('referer')).toBe(sourceUrl);
    });

    it('streams legacy resolver video addresses through the same guarded tunnel', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch')
            .mockResolvedValueOnce(Response.json(legacyVideoResolverPayload()))
            .mockResolvedValueOnce(new Response(new Uint8Array([7, 8, 9]), {
                status: 200,
                headers: {
                    'Content-Type': 'video/mp4',
                    'Content-Length': '3',
                },
            }));

        const request = new Request(
            `https://media.example.com/api/download?url=${encodeURIComponent(sourceUrl)}&type=video`,
        );
        const response = await xhsDownloadResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
            XHS_MAX_STREAM_BYTES: '10',
        }, 'req-legacy');

        expect(response?.status).toBe(200);
        expect(new Uint8Array(await response!.arrayBuffer())).toEqual(new Uint8Array([7, 8, 9]));
        expect(String(fetchMock.mock.calls[1][0])).toBe('https://sns-video-bd.xhscdn.com/legacy-video.mp4');
    });

    it('blocks a redirect from an allowlisted CDN to an untrusted host', async () => {
        const fetchMock = vi.spyOn(globalThis, 'fetch')
            .mockResolvedValueOnce(Response.json(videoResolverPayload()))
            .mockResolvedValueOnce(new Response(null, {
                status: 302,
                headers: { Location: 'https://evil.example.com/video.mp4' },
            }));

        const request = new Request(
            `https://media.example.com/api/download?url=${encodeURIComponent(sourceUrl)}&type=video`,
        );
        const response = await xhsDownloadResponse(request, sourceUrl, {
            XHS_RESOLVER_URL: 'https://resolver.example.com',
        }, 'req-3');

        expect(response?.status).toBe(502);
        expect(await response?.json()).toEqual(expect.objectContaining({
            success: false,
            details: { provider: 'xhs-resolver' },
        }));
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('defaults to fallback mode and only accepts explicit prefer mode', () => {
        expect(xhsResolverMode({})).toBe('fallback');
        expect(xhsResolverMode({ XHS_RESOLVER_MODE: 'prefer' })).toBe('prefer');
        expect(xhsResolverMode({ XHS_RESOLVER_MODE: 'unknown' })).toBe('fallback');
    });
});
