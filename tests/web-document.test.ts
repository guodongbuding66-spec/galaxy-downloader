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
        expect(parsed?.platform).toBe('shopify')
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

    it('extracts an Instagram photo carousel and caption from hydration JSON', () => {
        const html = `
            <html><head>
              <meta property="og:title" content="Backyard project">
              <meta property="og:description" content="Finished the backyard project today.">
              <script id="__DATA__" type="application/json">
                {
                  "shortcode_media": {
                    "edge_media_to_caption": {"edges":[{"node":{"text":"Finished the backyard project today."}}]},
                    "edge_sidecar_to_children": {"edges":[
                      {"node":{"display_url":"https://scontent.cdninstagram.com/photo-a.jpg","is_video":false}},
                      {"node":{"display_url":"https://scontent.cdninstagram.com/photo-b.jpg","is_video":false}},
                      {"node":{"display_url":"https://scontent.cdninstagram.com/photo-c.jpg","is_video":false}}
                    ]}
                  }
                }
              </script>
            </head></html>`

        const parsed = extractWebDocumentFromHtml('https://www.instagram.com/p/ABC123/', html)
        expect(parsed?.platform).toBe('instagram')
        expect(parsed?.documentType).toBe('post')
        expect(parsed?.description).toContain('backyard project')
        expect(parsed?.images).toHaveLength(3)
    })

    it('does not convert a video-only social post into a one-image document result', () => {
        const html = `
            <html><head>
              <meta property="og:title" content="Video post">
              <meta property="og:description" content="This is a normal video post.">
              <meta property="og:image" content="https://scontent.cdninstagram.com/video-poster.jpg">
              <meta property="og:video" content="https://video.cdninstagram.com/post.mp4">
              <meta property="og:type" content="video.other">
            </head></html>`

        expect(extractWebDocumentFromHtml('https://www.instagram.com/p/VIDEO123/', html)).toBeNull()
    })

    it('keeps mixed media carousels in the document result', () => {
        const html = `
            <html><head>
              <meta property="og:title" content="Mixed carousel">
              <meta property="og:description" content="Two photos and one short clip.">
              <script type="application/json">
                {
                  "items": [
                    {"image_url":"https://pbs.twimg.com/media/photo-a.jpg"},
                    {"image_url":"https://pbs.twimg.com/media/photo-b.jpg"},
                    {"video_url":"https://video.twimg.com/ext_tw_video/clip.mp4"}
                  ]
                }
              </script>
            </head></html>`

        const parsed = extractWebDocumentFromHtml('https://x.com/example/status/123', html)
        expect(parsed?.platform).toBe('x')
        expect(parsed?.images).toHaveLength(2)
        expect(parsed?.videos).toHaveLength(1)
    })

    it('labels major commerce platforms instead of collapsing them into generic', () => {
        const fixtures: Array<[string, string]> = [
            ['https://www.amazon.com/dp/B000000001', 'amazon'],
            ['https://www.ebay.com/itm/123456', 'ebay'],
            ['https://www.aliexpress.com/item/100500000000.html', 'aliexpress'],
            ['https://www.alibaba.com/product-detail/example_1600000000000.html', 'alibaba'],
        ]
        const html = `
            <meta property="og:title" content="Product">
            <meta property="og:description" content="A product description with enough text for document parsing.">
            <meta property="og:image" content="https://cdn.example.com/product.jpg">
        `

        for (const [url, platform] of fixtures) {
            expect(extractWebDocumentFromHtml(url, html)?.platform).toBe(platform)
        }
    })
})