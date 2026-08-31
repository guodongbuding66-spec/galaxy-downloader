import { describe, expect, it } from 'vitest'

import { extractWebDocumentFromHtml } from '@/lib/web-document'

describe('web document parser', () => {
    it('extracts Shopify product copy, gallery images and product video', () => {
        const html = `
            <html>
              <head>
                <meta property="og:title" content="Garden Storage Shed">
                <meta property="og:description" content="Weather-resistant outdoor storage for garden tools.">
                <meta property="og:image" content="https://cdn.shopify.com/s/files/1/product-main.jpg">
                <script type="application/ld+json">
                  {
                    "@type":"Product",
                    "name":"Garden Storage Shed",
                    "description":"Weather-resistant outdoor storage for garden tools.",
                    "image":[
                      "https://cdn.shopify.com/s/files/1/product-main.jpg",
                      "https://cdn.shopify.com/s/files/1/product-side.webp"
                    ],
                    "video":{"contentUrl":"https://cdn.shopify.com/videos/c/o/v/product-demo.mp4"}
                  }
                </script>
              </head>
              <body><img data-src="https://cdn.shopify.com/s/files/1/product-detail.jpg"></body>
            </html>`

        const parsed = extractWebDocumentFromHtml('https://example-shop.com/products/garden-shed', html)
        expect(parsed).not.toBeNull()
        expect(parsed?.documentType).toBe('product')
        expect(parsed?.title).toBe('Garden Storage Shed')
        expect(parsed?.description).toContain('Weather-resistant')
        expect(parsed?.images.map((item) => item.downloadUrl)).toContain('https://cdn.shopify.com/s/files/1/product-side.webp')
        expect(parsed?.videos[0]?.downloadVideoUrl).toBe('https://cdn.shopify.com/videos/c/o/v/product-demo.mp4')
    })

    it('extracts WeChat article body and lazy-loaded images', () => {
        const html = `
            <html><head>
              <meta property="og:title" content="新品发布">
              <meta name="author" content="iSUNOR">
              <meta property="og:image" content="https://mmbiz.qpic.cn/mmbiz_jpg/cover/0">
            </head><body>
              <div id="js_content">
                <p>这是公众号正文第一段。</p>
                <p>这是公众号正文第二段，包含产品介绍。</p>
                <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/photo1/0">
                <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/photo2/0">
              </div>
              <div id="js_toobar3">toolbar</div>
            </body></html>`

        const parsed = extractWebDocumentFromHtml('https://mp.weixin.qq.com/s/demo', html)
        expect(parsed?.platform).toBe('wechat')
        expect(parsed?.documentType).toBe('article')
        expect(parsed?.author).toBe('iSUNOR')
        expect(parsed?.textContent).toContain('公众号正文第一段')
        expect(parsed?.textContent).toContain('公众号正文第二段')
        expect(parsed?.images.length).toBeGreaterThanOrEqual(3)
    })

    it('extracts Douyin image-note media and caption from hydration JSON', () => {
        const html = `
            <html><head>
              <meta property="og:title" content="周末花园改造">
              <script id="__DATA__" type="application/json">
                {
                  "aweme": {
                    "desc": "周末花园改造，记录一下完成效果。",
                    "images": [
                      {"url":"https://p3-sign.douyinpic.com/tos-cn-i-0813/photo-a.jpeg"},
                      {"url":"https://p3-sign.douyinpic.com/tos-cn-i-0813/photo-b.jpeg"},
                      {"url":"https://p3-sign.douyinpic.com/tos-cn-i-0813/photo-c.jpeg"}
                    ]
                  }
                }
              </script>
            </head></html>`

        const parsed = extractWebDocumentFromHtml('https://www.douyin.com/note/123456', html)
        expect(parsed?.platform).toBe('douyin')
        expect(parsed?.documentType).toBe('post')
        expect(parsed?.description).toContain('周末花园改造')
        expect(parsed?.images).toHaveLength(3)
    })
})
