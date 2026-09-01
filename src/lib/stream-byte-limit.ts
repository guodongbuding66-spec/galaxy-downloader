export class ByteLimitExceededError extends Error {
    readonly maxBytes: number

    constructor(maxBytes: number) {
        super(`Response body exceeds ${maxBytes} byte limit`)
        this.name = 'ByteLimitExceededError'
        this.maxBytes = maxBytes
    }
}

export function declaredContentLength(headers: Headers): number | null {
    const raw = headers.get('content-length')?.trim()
    if (!raw) return null
    const value = Number(raw)
    return Number.isSafeInteger(value) && value >= 0 ? value : null
}

function limitedStreamFromReader(
    reader: ReadableStreamDefaultReader<Uint8Array>,
    maxBytes: number,
    initialChunks: Uint8Array[] = [],
    initialBytes = 0,
): ReadableStream<Uint8Array> {
    let totalBytes = initialBytes
    let queuedChunks = initialChunks.slice()

    return new ReadableStream<Uint8Array>({
        start(controller) {
            for (const chunk of queuedChunks) controller.enqueue(chunk)
            queuedChunks = []
        },
        async pull(controller) {
            try {
                const { done, value } = await reader.read()
                if (done) {
                    controller.close()
                    return
                }

                totalBytes += value.byteLength
                if (totalBytes > maxBytes) {
                    await reader.cancel('response body byte limit exceeded').catch(() => undefined)
                    controller.error(new ByteLimitExceededError(maxBytes))
                    return
                }

                controller.enqueue(value)
            } catch (error) {
                controller.error(error)
            }
        },
        async cancel(reason) {
            await reader.cancel(reason).catch(() => undefined)
        },
    })
}

export function limitReadableStream(
    body: ReadableStream<Uint8Array>,
    maxBytes: number,
): ReadableStream<Uint8Array> {
    if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
        throw new TypeError('maxBytes must be a positive safe integer')
    }
    return limitedStreamFromReader(body.getReader(), maxBytes)
}

function concatChunks(chunks: Uint8Array[], totalBytes: number): Uint8Array {
    const output = new Uint8Array(totalBytes)
    let offset = 0
    for (const chunk of chunks) {
        output.set(chunk, offset)
        offset += chunk.byteLength
    }
    return output
}

/**
 * Read only enough bytes to identify a generic binary response, then replay
 * those bytes into a size-limited stream. The rest of the upstream body is
 * never buffered in memory.
 */
export async function sniffPrefixAndLimitStream(
    body: ReadableStream<Uint8Array>,
    maxBytes: number,
    prefixBytes: number,
): Promise<{ prefix: Uint8Array; stream: ReadableStream<Uint8Array> }> {
    if (!Number.isSafeInteger(maxBytes) || maxBytes <= 0) {
        throw new TypeError('maxBytes must be a positive safe integer')
    }
    if (!Number.isSafeInteger(prefixBytes) || prefixBytes <= 0) {
        throw new TypeError('prefixBytes must be a positive safe integer')
    }

    const reader = body.getReader()
    const initialChunks: Uint8Array[] = []
    let initialBytes = 0

    try {
        while (initialBytes < prefixBytes) {
            const { done, value } = await reader.read()
            if (done) break

            initialBytes += value.byteLength
            if (initialBytes > maxBytes) {
                await reader.cancel('response body byte limit exceeded').catch(() => undefined)
                throw new ByteLimitExceededError(maxBytes)
            }
            initialChunks.push(value)
        }

        const combined = concatChunks(initialChunks, initialBytes)
        return {
            prefix: combined.slice(0, Math.min(prefixBytes, combined.byteLength)),
            stream: limitedStreamFromReader(reader, maxBytes, initialChunks, initialBytes),
        }
    } catch (error) {
        await reader.cancel(error).catch(() => undefined)
        throw error
    }
}
