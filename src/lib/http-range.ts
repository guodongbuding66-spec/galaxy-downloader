const MAX_RANGE_HEADER_LENGTH = 128;
const MAX_SAFE_RANGE_VALUE = Number.MAX_SAFE_INTEGER;
const SINGLE_BYTE_RANGE_RE = /^bytes=(\d*)-(\d*)$/i;

/**
 * Normalize the browser Range forms used for progressive media playback while
 * rejecting multipart, malformed, or unreasonably large values before they are
 * forwarded to an upstream media host.
 */
export function normalizeSingleByteRange(value: string | null | undefined): string | null {
    if (value == null) return null;
    const candidate = value.trim();
    if (!candidate) return null;
    if (candidate.length > MAX_RANGE_HEADER_LENGTH || candidate.includes(',')) {
        throw new Error('Only one bytes range is allowed');
    }

    const match = candidate.match(SINGLE_BYTE_RANGE_RE);
    if (!match) throw new Error('Invalid Range header');
    const startRaw = match[1] || '';
    const endRaw = match[2] || '';
    if (!startRaw && !endRaw) throw new Error('Range cannot be empty');

    const parseBound = (raw: string): number | null => {
        if (!raw) return null;
        if (raw.length > 16) throw new Error('Range value is too large');
        const parsed = Number(raw);
        if (!Number.isSafeInteger(parsed) || parsed < 0 || parsed > MAX_SAFE_RANGE_VALUE) {
            throw new Error('Range value is invalid');
        }
        return parsed;
    };

    const start = parseBound(startRaw);
    const end = parseBound(endRaw);
    if (start === null && (end === null || end <= 0)) {
        throw new Error('Suffix range must be positive');
    }
    if (start !== null && end !== null && start > end) {
        throw new Error('Range start exceeds end');
    }
    return `bytes=${startRaw}-${endRaw}`;
}
