import { afterEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

import { GET } from '@/app/api/proxy-image/route'

const WECHAT_IMAGE = 'https://mmbiz.qpic.cn/sz_mmbiz_jpg/skIv7LAPeGJrjaOJNmWNB9HNHTIic2UT1WDnUk32R5hlic5lWfnNY1BmEic1uW6vyEPyoqicl4thq1x3iaicluEicnicqA/640?wx_fmt=jpeg&tp=webp&wxfrom=5'

afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
})

describe('proxy-image original image behavior', () => {
    it('requests WeChat original dimensions and does not advertise WebP for downloads', async () => {
        const calls: Array<{ url: string; headers: Headers }> = []
        const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
            calls.push({
                url: String(input),
                headers: new Headers(init?.headers),
            })
            return new Response(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), {
                status: 200,
                headers: { 'Content-Type': 'image/jpeg' },
            })
        })
        vi.stubGlobal('fetch', fetchMock)

        const params = new URLSearchParams({
            url: WECHAT_IMAGE,
            mode: 'download',
            source: 'https://mp.weixin.qq.com/',
        })
        const response = await GET(new NextRequest(`https://galaxy.example/api/proxy-image?${params.toString()}`))

        expect(response.status).toBe(200)
        expect(response.headers.get('content-type')).toBe('image/jpeg')
        expect(response.headers.get('x-galaxy-max-image-bytes')).toBe(String(32 * 1024 * 1024))
        expect(calls).toHaveLength(1)

        const requested = new URL(calls[0]!.url)
        expect(requested.pathname.endsWith('/0')).toBe(true)
        expect(requested.searchParams.get('wx_fmt')).toBe('jpeg')
        expect(requested.searchParams.has('tp')).toBe(false)
        expect(calls[0]!.headers.get('accept')).not.toContain('image/webp')
        expect(calls[0]!.headers.get('accept')).not.toContain('image/avif')
        expect(calls[0]!.headers.get('referer')).toBe('https://mp.weixin.qq.com/')
    })

    it('falls back to the exact parsed URL when the original candidate is rejected', async () => {
        const requestedUrls: string[] = []
        const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
            const value = String(input)
            requestedUrls.push(value)
            if (new URL(value).pathname.endsWith('/0')) {
                return new Response('blocked', {
                    status: 403,
                    headers: { 'Content-Type': 'text/plain' },
                })
            }
            return new Response(new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), {
                status: 200,
                headers: { 'Content-Type': 'image/jpeg' },
            })
        })
        vi.stubGlobal('fetch', fetchMock)

        const params = new URLSearchParams({ url: WECHAT_IMAGE, mode: 'download' })
        const response = await GET(new NextRequest(`https://galaxy.example/api/proxy-image?${params.toString()}`))

        expect(response.status).toBe(200)
        expect(requestedUrls).toHaveLength(2)
        expect(new URL(requestedUrls[0]!).pathname.endsWith('/0')).toBe(true)
        expect(new URL(requestedUrls[1]!).pathname.endsWith('/640')).toBe(true)
    })

    it('rejects a declared oversized image before streaming it to the client', async () => {
        const fetchMock = vi.fn(async () => new Response(new Uint8Array([0xff, 0xd8, 0xff]), {
            status: 200,
            headers: {
                'Content-Type': 'image/jpeg',
                'Content-Length': String(32 * 1024 * 1024 + 1),
            },
        }))
        vi.stubGlobal('fetch', fetchMock)

        const params = new URLSearchParams({ url: WECHAT_IMAGE, mode: 'download' })
        const response = await GET(new NextRequest(`https://galaxy.example/api/proxy-image?${params.toString()}`))

        expect(response.status).toBe(413)
        await expect(response.json()).resolves.toEqual({ error: 'Image exceeds 32 MiB proxy limit' })
    })
})
