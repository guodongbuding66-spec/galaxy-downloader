import { describe, expect, it } from 'vitest'

import {
    bestSrcsetCandidate,
    originalImageCandidates,
    preferredRasterFormat,
} from '@/lib/image-source'
import {
    resolveImageDownloadSrc,
    resolveImageSrc,
} from '@/components/downloader/result-card-utils'

describe('document image source policy', () => {
    it('selects the largest srcset candidate instead of the thumbnail', () => {
        expect(bestSrcsetCandidate(
            'https://cdn.example/320.jpg 320w, https://cdn.example/1280.jpg 1280w, https://cdn.example/640.jpg 640w',
        )).toBe('https://cdn.example/1280.jpg')

        expect(bestSrcsetCandidate(
            'https://cdn.example/1x.jpg 1x, https://cdn.example/3x.jpg 3x, https://cdn.example/2x.jpg 2x',
        )).toBe('https://cdn.example/3x.jpg')
    })

    it('tries the original WeChat qpic dimensions before the parsed derivative', () => {
        const raw = 'https://mmbiz.qpic.cn/mmbiz_jpg/demo/640?wx_fmt=jpeg&tp=webp&from=appmsg'
        const candidates = originalImageCandidates(raw)

        expect(candidates).toHaveLength(2)
        const original = new URL(candidates[0]!)
        expect(original.pathname).toBe('/mmbiz_jpg/demo/0')
        expect(original.searchParams.get('wx_fmt')).toBe('jpeg')
        expect(original.searchParams.has('tp')).toBe(false)
        expect(candidates[1]).toBe(raw)
        expect(preferredRasterFormat(raw)).toBe('jpg')
    })

    it('keeps PNG as the lossless fallback when the original format is unknown', () => {
        expect(preferredRasterFormat('https://cdn.example/image?id=123')).toBe('png')
        expect(preferredRasterFormat('https://mmbiz.qpic.cn/mmbiz_png/demo/640?wx_fmt=png')).toBe('png')
    })

    it('uses a distinct download proxy that asks for compatible source formats', () => {
        const image = 'https://mmbiz.qpic.cn/mmbiz_jpg/demo/640?wx_fmt=jpeg'
        const source = 'https://mp.weixin.qq.com/s/example?token=secret'
        const preview = resolveImageSrc(image, source)
        const download = resolveImageDownloadSrc(image, source)

        expect(preview).toContain('/api/proxy-image?')
        expect(preview).not.toContain('mode=download')
        expect(download).toContain('mode=download')
        expect(download).toContain(encodeURIComponent('https://mp.weixin.qq.com/'))
        expect(download).not.toContain('token%3Dsecret')
    })
})
