import { preferredRasterFormat } from '@/lib/image-source';
import { downloadFile } from '@/lib/utils';

import { shouldUseFrontendImageProxy } from './result-card-visibility';

export type ImageLoadState = {
    loading: boolean;
    error: boolean;
    src: string;
    baseSrc: string;
    usedFallback: boolean;
    usedDirectFallback: boolean;
};

type ResolvedImageFetchResult = {
    blob: Blob;
    sourceUrl: string;
};

export type PreparedImageDownload = {
    blob: Blob;
    extension: string;
    converted: boolean;
};

export function replaceTemplate(template: string, token: string, value: string): string {
    return template.replace(token, value);
}

function sourceOrigin(sourceUrl: string | null | undefined): string | null {
    if (!sourceUrl) return null;
    try {
        const parsed = new URL(sourceUrl);
        if (!['http:', 'https:'].includes(parsed.protocol)) return null;
        return `${parsed.origin}/`;
    } catch {
        return null;
    }
}

function buildImageProxyUrl(
    imageUrl: string,
    sourceUrl?: string | null,
    mode: 'preview' | 'download' = 'preview',
): string {
    const params = new URLSearchParams({ url: imageUrl });
    if (mode === 'download') params.set('mode', 'download');
    const referer = sourceOrigin(sourceUrl);
    if (referer) params.set('source', referer);
    return `/api/proxy-image?${params.toString()}`;
}

export function resolveCoverSrc(coverUrl: string, sourceUrl?: string | null): string {
    if (shouldUseFrontendImageProxy(coverUrl)) {
        return buildImageProxyUrl(coverUrl, sourceUrl, 'preview');
    }
    return coverUrl;
}

export function resolveImageSrc(imageUrl: string, sourceUrl?: string | null): string {
    if (shouldUseFrontendImageProxy(imageUrl)) {
        return buildImageProxyUrl(imageUrl, sourceUrl, 'preview');
    }
    return imageUrl;
}

export function resolveImageDownloadSrc(imageUrl: string, sourceUrl?: string | null): string {
    if (shouldUseFrontendImageProxy(imageUrl)) {
        return buildImageProxyUrl(imageUrl, sourceUrl, 'download');
    }
    return imageUrl;
}

export function triggerBlobDownload(blob: Blob, filename: string) {
    const objectUrl = URL.createObjectURL(blob);
    downloadFile(objectUrl, filename);

    // Revoke after the click has been dispatched so browsers can resolve the blob URL.
    window.setTimeout(() => {
        URL.revokeObjectURL(objectUrl);
    }, 1000);
}

function dedupeUrls(urls: string[]): string[] {
    return Array.from(new Set(urls.filter((value) => value.length > 0)));
}

export function resolveImageDownloadExtension(sourceUrl: string, contentType: string | null | undefined): string {
    const normalizedContentType = contentType?.split(';')[0]?.trim().toLowerCase() ?? '';
    const contentTypeMap: Record<string, string> = {
        'image/jpeg': 'jpg',
        'image/jpg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
        'image/gif': 'gif',
        'image/svg+xml': 'svg',
        'image/avif': 'avif',
    };

    const mappedExtension = contentTypeMap[normalizedContentType];
    if (mappedExtension) {
        return mappedExtension;
    }

    try {
        const pathname = new URL(sourceUrl, window.location.origin).pathname;
        const match = pathname.match(/\.([a-z0-9]+)$/i);
        if (match?.[1]) {
            return match[1].toLowerCase();
        }
    } catch {
        // Ignore invalid urls and fall back to jpg.
    }

    return 'jpg';
}

export function createInitialImageStates(images: string[], sourceUrl?: string | null): ImageLoadState[] {
    return images.map((imageUrl) => {
        const baseSrc = resolveImageSrc(imageUrl, sourceUrl);
        return {
            loading: true,
            error: false,
            src: baseSrc,
            baseSrc,
            usedFallback: false,
            usedDirectFallback: false,
        };
    });
}

export async function fetchImageBlobCandidates(candidates: string[]): Promise<ResolvedImageFetchResult> {
    let lastError: unknown = null;

    for (const candidate of dedupeUrls(candidates)) {
        try {
            const response = await fetch(candidate, { cache: 'no-store' });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const blob = await response.blob();
            if (!blob.type.toLowerCase().startsWith('image/')) {
                throw new Error(`Unexpected image content type: ${blob.type || 'unknown'}`);
            }

            return {
                blob,
                sourceUrl: candidate,
            };
        } catch (error) {
            lastError = error;
        }
    }

    throw lastError ?? new Error('Failed to fetch image');
}

async function decodeBlobToCanvas(blob: Blob): Promise<HTMLCanvasElement> {
    const canvas = document.createElement('canvas');

    if (typeof createImageBitmap === 'function') {
        const bitmap = await createImageBitmap(blob);
        try {
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
            const context = canvas.getContext('2d');
            if (!context) throw new Error('Canvas 2D context is unavailable');
            context.drawImage(bitmap, 0, 0);
            return canvas;
        } finally {
            bitmap.close();
        }
    }

    const objectUrl = URL.createObjectURL(blob);
    try {
        const image = document.createElement('img');
        image.src = objectUrl;
        await image.decode();
        canvas.width = image.naturalWidth;
        canvas.height = image.naturalHeight;
        const context = canvas.getContext('2d');
        if (!context) throw new Error('Canvas 2D context is unavailable');
        context.drawImage(image, 0, 0);
        return canvas;
    } finally {
        URL.revokeObjectURL(objectUrl);
    }
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality?: number): Promise<Blob> {
    return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
            if (blob) resolve(blob);
            else reject(new Error(`Unable to encode ${type}`));
        }, type, quality);
    });
}

/**
 * Keep the upstream file byte-for-byte when it is already a common format.
 * WebP/AVIF are converted only as a final compatibility fallback after the
 * download proxy has first asked the CDN for the original/JPEG/PNG response.
 */
export async function prepareImageDownloadBlob(blob: Blob, originalUrl: string): Promise<PreparedImageDownload> {
    const contentType = blob.type.split(';')[0]?.trim().toLowerCase() || '';
    if (contentType !== 'image/webp' && contentType !== 'image/avif') {
        return {
            blob,
            extension: resolveImageDownloadExtension(originalUrl, contentType),
            converted: false,
        };
    }

    const preferred = preferredRasterFormat(originalUrl);
    const targetType = preferred === 'jpg' ? 'image/jpeg' : 'image/png';
    try {
        const canvas = await decodeBlobToCanvas(blob);
        const convertedBlob = await canvasToBlob(canvas, targetType, preferred === 'jpg' ? 0.96 : undefined);
        return {
            blob: convertedBlob,
            extension: preferred,
            converted: true,
        };
    } catch (error) {
        console.warn('Image compatibility conversion failed; keeping the upstream format.', error);
        return {
            blob,
            extension: resolveImageDownloadExtension(originalUrl, contentType),
            converted: false,
        };
    }
}
