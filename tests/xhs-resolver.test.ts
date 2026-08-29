import { describe, expect, it } from 'vitest';

import {
    isAllowedXhsMediaUrl,
    isXhsSourceUrl,
    limitStreamBytes,
    normalizeXhsDetail,
    xhsResolverMode,
} from '../container-backend/src/xhs-resolver';

describe('XHS resolver provider', () => {
    it('recognizes full and short Xiaohongshu links only', () => {
        expect(isXhsSourceUrl('https://www.xiaohongshu.com/explore/abc')).toBe(true);
        expect(isXhsSourceUrl('https://xhslink.com/a/abc')).toBe(true);
        expect(isXhsSourceUrl('https://sub.xhslink.com/a/abc')).toBe(true);
        expect(isXhsSourceUrl('https://example.com/xiaohongshu.com/video')).toBe(false);
        expect(isXhsSourceUrl('not a url')).toBe(false);
    });

    it('normalizes a resolver video into a first-party download route', () => {
        const sourceUrl = 'https://www.xiaohongshu.com/explore/abc';
        const result = normalizeXhsDetail({
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
        }, sourceUrl, 'https://media.example.com');

        expect(result.platform).toBe('xiaohongshu');
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

    it('normalizes image notes without inventing video media', () => {
        const sourceUrl = 'https://www.xiaohongshu.com/explore/images';
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
        }, sourceUrl, 'https://media.example.com');

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

    it('defaults to fallback mode and only accepts explicit prefer mode', () => {
        expect(xhsResolverMode({})).toBe('fallback');
        expect(xhsResolverMode({ XHS_RESOLVER_MODE: 'prefer' })).toBe('prefer');
        expect(xhsResolverMode({ XHS_RESOLVER_MODE: 'unknown' })).toBe('fallback');
    });
});
