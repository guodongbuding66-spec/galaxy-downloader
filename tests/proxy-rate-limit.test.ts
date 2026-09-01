import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
    PROXY_RATE_LIMITS,
    ProxyRateLimiter,
    enforceProxyRateLimit,
    type DurableObjectNamespaceLike,
} from '../worker/proxy-rate-limit'

afterEach(() => {
    vi.useRealTimers()
})

function fakeState() {
    const values = new Map<string, unknown>()
    return {
        storage: {
            async get<T>(key: string): Promise<T | undefined> {
                return values.get(key) as T | undefined
            },
            async put<T>(key: string, value: T): Promise<void> {
                values.set(key, value)
            },
        },
    }
}

describe('Cloudflare proxy rate limiter', () => {
    it('returns 429 after the media bucket is exhausted within one window', async () => {
        vi.useFakeTimers()
        vi.setSystemTime(new Date('2026-09-01T00:00:15Z'))

        const limiter = new ProxyRateLimiter(fakeState())
        const limit = PROXY_RATE_LIMITS['media-download'].limit

        for (let index = 0; index < limit; index += 1) {
            const response = await limiter.fetch(new Request('https://internal.invalid/check?bucket=media-download'))
            expect(response.status).toBe(200)
        }

        const blocked = await limiter.fetch(new Request('https://internal.invalid/check?bucket=media-download'))
        expect(blocked.status).toBe(429)
        expect(blocked.headers.get('retry-after')).toBeTruthy()
        expect(blocked.headers.get('ratelimit-remaining')).toBe('0')
    })

    it('keeps image preview and download traffic in separate buckets', async () => {
        const seen: string[] = []
        const namespace: DurableObjectNamespaceLike = {
            idFromName(name: string) {
                seen.push(`id:${name}`)
                return name
            },
            get() {
                return {
                    async fetch(input: RequestInfo | URL) {
                        seen.push(String(input))
                        return new Response('{}', { status: 200 })
                    },
                }
            },
        }

        await enforceProxyRateLimit(new Request('https://galaxy.example/api/proxy-image?mode=download', {
            headers: { 'cf-connecting-ip': '203.0.113.7' },
        }), namespace)
        await enforceProxyRateLimit(new Request('https://galaxy.example/api/proxy-image', {
            headers: { 'cf-connecting-ip': '203.0.113.7' },
        }), namespace)

        expect(seen.some((value) => value.includes('bucket=image-download'))).toBe(true)
        expect(seen.some((value) => value.includes('bucket=image-preview'))).toBe(true)
    })

    it('skips the edge limiter in local development when Cloudflare client IP is absent', async () => {
        const namespace: DurableObjectNamespaceLike = {
            idFromName() {
                throw new Error('should not be called')
            },
            get() {
                throw new Error('should not be called')
            },
        }

        await expect(enforceProxyRateLimit(
            new Request('http://localhost:3000/api/proxy-image'),
            namespace,
        )).resolves.toBeNull()
    })

    it('keeps the Worker binding and migration in deploy config', () => {
        const wrangler = readFileSync(resolve(process.cwd(), 'wrangler.jsonc'), 'utf8')
        const worker = readFileSync(resolve(process.cwd(), 'worker/index.ts'), 'utf8')

        expect(wrangler).toContain('PROXY_RATE_LIMITER')
        expect(wrangler).toContain('ProxyRateLimiter')
        expect(wrangler).toContain('"tag": "v2"')
        expect(worker).toContain('enforceProxyRateLimit')
    })
})
