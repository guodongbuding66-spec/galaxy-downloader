import { describe, expect, it } from 'vitest'

import {
    ByteLimitExceededError,
    declaredContentLength,
    limitReadableStream,
    sniffPrefixAndLimitStream,
} from '@/lib/stream-byte-limit'

function byteStream(...chunks: number[][]): ReadableStream<Uint8Array> {
    return new ReadableStream<Uint8Array>({
        start(controller) {
            for (const chunk of chunks) controller.enqueue(new Uint8Array(chunk))
            controller.close()
        },
    })
}

describe('stream byte limiter', () => {
    it('parses only safe non-negative content lengths', () => {
        expect(declaredContentLength(new Headers({ 'content-length': '123' }))).toBe(123)
        expect(declaredContentLength(new Headers({ 'content-length': '-1' }))).toBeNull()
        expect(declaredContentLength(new Headers({ 'content-length': 'NaN' }))).toBeNull()
        expect(declaredContentLength(new Headers())).toBeNull()
    })

    it('passes a response that stays within the byte limit', async () => {
        const limited = limitReadableStream(byteStream([1, 2], [3]), 3)
        const bytes = new Uint8Array(await new Response(limited).arrayBuffer())
        expect(Array.from(bytes)).toEqual([1, 2, 3])
    })

    it('aborts a chunked response once actual bytes exceed the limit', async () => {
        const limited = limitReadableStream(byteStream([1, 2], [3, 4]), 3)
        await expect(new Response(limited).arrayBuffer()).rejects.toBeInstanceOf(ByteLimitExceededError)
    })

    it('sniffs a small prefix and replays the complete body without buffering the rest', async () => {
        const { prefix, stream } = await sniffPrefixAndLimitStream(
            byteStream([0xff, 0xd8], [0xff, 0xd9], [7, 8, 9]),
            16,
            3,
        )

        expect(Array.from(prefix)).toEqual([0xff, 0xd8, 0xff])
        const bytes = new Uint8Array(await new Response(stream).arrayBuffer())
        expect(Array.from(bytes)).toEqual([0xff, 0xd8, 0xff, 0xd9, 7, 8, 9])
    })
})
