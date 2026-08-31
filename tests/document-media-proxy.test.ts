import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

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

    it('blocks loopback and private-network targets in both media proxy routes', () => {
        const imageProxy = readFileSync(resolve(process.cwd(), 'src/app/api/proxy-image/route.ts'), 'utf8')
        const mediaProxy = readFileSync(resolve(process.cwd(), 'src/app/api/proxy-media/route.ts'), 'utf8')

        for (const source of [imageProxy, mediaProxy]) {
            expect(source).toContain("host === 'localhost'")
            expect(source).toContain('isPrivateIpv4')
            expect(source).toContain("host === '::1'")
            expect(source).toContain("host.startsWith('fe80:')")
        }
    })
})
