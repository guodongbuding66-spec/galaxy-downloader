import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { normalizeSingleByteRange } from '@/lib/http-range'
import { isSafePublicHttpUrl } from '@/lib/public-url'
import { extractWebDocumentFromHtml } from '@/lib/web-document'

describe('document media download plumbing', () => {
    it('keeps raw embedded product videos while the API wraps the download URL with the media proxy', () => {
        const parsed = extractWebDocumentFromHtml('https://shop.example/products/item', `
            <meta property="og:title" content="Example product">
            <meta property="og:description" content="Product copy long enough to be a document result.">
            <script type="application/ld+json">
              {"@type":"Product","video":{"contentUrl":"https://cdn.example/video/demo.mp4"}}
            </script>
        `)
        expect(parsed?.videos[0]?.originDownloadVideoUrl).toBe('https://cdn.example/video/demo.mp4')

        const route = readFileSync(resolve(process.cwd(), 'src/app/api/web-document/route.ts'), 'utf8')
        expect(route).toContain("new URL('/api/proxy-media', request.nextUrl.origin)")
        expect(route).toContain("proxy.searchParams.set('source', sourceUrl)")
    })

    it('uses one literal public-url boundary for document, image, and media fetches', () => {
        const blocked = [
            'http://localhost/video.mp4',
            'http://printer/video.mp4',
            'http://127.0.0.1/video.mp4',
            'http://10.0.0.5/video.mp4',
            'http://169.254.169.254/latest/meta-data/',
            'http://192.0.2.10/video.mp4',
            'http://198.18.0.1/video.mp4',
            'http://203.0.113.10/video.mp4',
            'http://[::1]/video.mp4',
            'http://[::ffff:127.0.0.1]/video.mp4',
            'http://[fe80::1]/video.mp4',
            'http://[fec0::1]/video.mp4',
            'http://[2001:db8::1]/video.mp4',
            'https://user:secret@example.com/video.mp4',
        ]
        for (const value of blocked) {
            expect(isSafePublicHttpUrl(new URL(value)), value).toBe(false)
        }
        expect(isSafePublicHttpUrl(new URL('https://cdn.example.com/video.mp4'))).toBe(true)
        expect(isSafePublicHttpUrl(new URL('https://[2606:4700:4700::1111]/video.mp4'))).toBe(true)

        for (const path of [
            'src/app/api/proxy-image/route.ts',
            'src/app/api/proxy-media/route.ts',
            'src/app/api/web-document/route.ts',
        ]) {
            const source = readFileSync(resolve(process.cwd(), path), 'utf8')
            expect(source, path).toContain('isSafePublicHttpUrl')
        }
    })

    it('revalidates image, media, and document redirect hops instead of auto-following them', () => {
        const imageProxy = readFileSync(resolve(process.cwd(), 'src/app/api/proxy-image/route.ts'), 'utf8')
        const mediaProxy = readFileSync(resolve(process.cwd(), 'src/app/api/proxy-media/route.ts'), 'utf8')
        const documentRoute = readFileSync(resolve(process.cwd(), 'src/app/api/web-document/route.ts'), 'utf8')

        for (const source of [imageProxy, mediaProxy, documentRoute]) {
            expect(source).toContain("redirect: 'manual'")
            expect(source).toContain('new URL(location, current)')
        }
    })

    it('only forwards one valid byte range', () => {
        expect(normalizeSingleByteRange(null)).toBeNull()
        expect(normalizeSingleByteRange('bytes=0-')).toBe('bytes=0-')
        expect(normalizeSingleByteRange('BYTES=100-200')).toBe('bytes=100-200')
        expect(normalizeSingleByteRange('bytes=-500')).toBe('bytes=-500')

        for (const invalid of [
            'bytes=-',
            'bytes=-0',
            'bytes=500-100',
            'bytes=0-10,20-30',
            'items=0-10',
            'bytes=0 - 10',
            `bytes=${'1'.repeat(140)}-`,
        ]) {
            expect(() => normalizeSingleByteRange(invalid), invalid).toThrow()
        }

        const mediaProxy = readFileSync(resolve(process.cwd(), 'src/app/api/proxy-media/route.ts'), 'utf8')
        expect(mediaProxy).toContain('normalizeSingleByteRange')
        expect(mediaProxy).toContain("{ error: 'Range must be a single valid bytes range' }")
    })
})
