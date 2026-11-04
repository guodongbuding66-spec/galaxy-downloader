import { useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, Download, Expand, Loader2, Package } from 'lucide-react';
import Image from 'next/image';

import { Button } from '@/components/ui/button';
import { useAppLocale, useDictionary } from '@/i18n/client';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { imageGalleryCopy, selectedImageIndices, visibleImageIndices, type ImageDimensions } from './image-gallery-model';
import { toast } from '@/lib/deferred-toast';
import { buildDocumentArchiveMarkdown, type ArchiveImageFile } from '@/lib/document-archive';
import { LOCAL_ENGINE_REQUIRED_VERSION } from '@/lib/local-engine';
import { submitLocalImageDownload } from '@/lib/local-image-engine';
import { sanitizeFilename } from '@/lib/utils';

import { shouldHideSingleImagePreview } from './result-card-visibility';
import {
    createInitialImageStates,
    fetchImageBlobCandidates,
    ImageRelayLimitError,
    prepareImageDownloadBlob,
    replaceTemplate,
    resolveImageDownloadSrc,
    resolveImageSrc,
    triggerBlobDownload,
    type ImageLoadState,
} from './result-card-utils';

const LOCAL_ENGINE_BATCH_THRESHOLD = 20;
const LOCAL_ENGINE_LABEL = `Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+`;

type ArchiveMetadata = {
    description?: string | null;
    markdownContent?: string | null;
    author?: string | null;
    publishedAt?: string | null;
    sourceUrl?: string | null;
};

function pageLanguage(): string {
    return typeof document === 'undefined' ? 'en' : document.documentElement.lang.toLowerCase();
}

function oversizedImageMessage(): string {
    const language = pageLanguage();
    if (language.startsWith('zh')) return `原图超过服务器中转上限。请下载安装并启动 Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ 后重试，原图会直接下载到你的电脑。`;
    if (language.startsWith('ja')) return `元画像がサーバー中継上限を超えています。Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ を起動して再試行してください。`;
    if (language.startsWith('es')) return `La imagen original supera el límite del servidor. Inicia Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ y vuelve a intentarlo.`;
    if (language.startsWith('ru')) return `Оригинал превышает лимит серверного прокси. Запустите Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ и повторите попытку.`;
    return `The original image exceeds the server relay limit. Start Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ and retry for a direct local download.`;
}

function largeBatchMessage(count: number): string {
    const language = pageLanguage();
    if (language.startsWith('zh')) return `本次包含 ${count} 张原图。为避免占用服务器带宽和浏览器内存，超过 ${LOCAL_ENGINE_BATCH_THRESHOLD} 张的批量下载必须使用 Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+。`;
    if (language.startsWith('ja')) return `${count} 枚の原画像があります。${LOCAL_ENGINE_BATCH_THRESHOLD} 枚を超える一括保存には Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ が必要です。`;
    if (language.startsWith('es')) return `Este lote contiene ${count} imágenes. Los lotes de más de ${LOCAL_ENGINE_BATCH_THRESHOLD} imágenes requieren Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+.`;
    if (language.startsWith('ru')) return `В наборе ${count} изображений. Для пакетов больше ${LOCAL_ENGINE_BATCH_THRESHOLD} изображений требуется Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+.`;
    return `This batch contains ${count} originals. Batches over ${LOCAL_ENGINE_BATCH_THRESHOLD} images require Galaxy Local Engine ${LOCAL_ENGINE_REQUIRED_VERSION}+ to avoid server bandwidth and browser-memory pressure.`;
}

export function ImageNoteGrid({
    images,
    title,
    singleImageMode = false,
    description,
    markdownContent,
    author,
    publishedAt,
    sourceUrl,
}: {
    images: string[];
    title: string;
    singleImageMode?: boolean;
    description?: string | null;
    markdownContent?: string | null;
    author?: string | null;
    publishedAt?: string | null;
    sourceUrl?: string | null;
}) {
    const imageSetKey = images.map((imageUrl) => resolveImageSrc(imageUrl, sourceUrl)).join('\u0000');

    return (
        <ImageNoteGridContent
            key={imageSetKey}
            images={images}
            title={title}
            singleImageMode={singleImageMode}
            description={description}
            markdownContent={markdownContent}
            author={author}
            publishedAt={publishedAt}
            sourceUrl={sourceUrl}
        />
    );
}

function archiveText(title: string, metadata: ArchiveMetadata): string {
    return [
        title.trim(),
        metadata.author ? `Author: ${metadata.author}` : '',
        metadata.publishedAt ? `Published: ${metadata.publishedAt}` : '',
        metadata.sourceUrl ? `Source: ${metadata.sourceUrl}` : '',
        '',
        metadata.description?.trim() || '',
    ].filter((line, index, lines) => line || (index > 0 && lines[index - 1])).join('\n').trim();
}

function ImageNoteGridContent({
    images,
    title,
    singleImageMode = false,
    description,
    markdownContent,
    author,
    publishedAt,
    sourceUrl,
}: {
    images: string[];
    title: string;
    singleImageMode?: boolean;
    description?: string | null;
    markdownContent?: string | null;
    author?: string | null;
    publishedAt?: string | null;
    sourceUrl?: string | null;
}) {
    const dict = useDictionary();
    const copy = imageGalleryCopy(useAppLocale());
    const [selected, setSelected] = useState<Set<number>>(() => new Set(images.map((_, index) => index)));
    const [dimensions, setDimensions] = useState<Record<number, ImageDimensions>>({});
    const [minimumLongEdge, setMinimumLongEdge] = useState(0);
    const [previewIndex, setPreviewIndex] = useState<number | null>(null);
    const previewTriggerRef = useRef<HTMLButtonElement | null>(null);
    const selectedIndices = selectedImageIndices(images.length, selected);
    const visibleIndices = visibleImageIndices(images.length, dimensions, minimumLongEdge);
    const [imageStates, setImageStates] = useState<ImageLoadState[]>(() => createInitialImageStates(images, sourceUrl));
    const [isPackaging, setIsPackaging] = useState(false);
    const [packagingProgress, setPackagingProgress] = useState(0);

    const updateImageState = (index: number, updater: (state: ImageLoadState) => ImageLoadState) => {
        setImageStates((previous) => previous.map((state, currentIndex) => (
            currentIndex === index ? updater(state) : state
        )));
    };

    const handleImageLoad = (index: number, width: number, height: number) => {
        if (width > 0 && height > 0) setDimensions((previous) => ({ ...previous, [index]: { width, height } }));
        updateImageState(index, (state) => ({ ...state, loading: false, error: false }));
    };

    const handleImageError = (index: number, originalUrl: string) => {
        updateImageState(index, (state) => {
            const downloadProxy = resolveImageDownloadSrc(originalUrl, sourceUrl);
            if (!state.usedFallback && state.src !== downloadProxy) {
                return {
                    ...state,
                    loading: true,
                    error: false,
                    src: downloadProxy,
                    usedFallback: true,
                };
            }
            if (!state.usedDirectFallback && state.src !== originalUrl) {
                return {
                    ...state,
                    loading: true,
                    error: false,
                    src: originalUrl,
                    usedFallback: true,
                    usedDirectFallback: true,
                };
            }
            return { ...state, loading: false, error: true };
        });
    };

    const downloadCandidates = (index: number, originalUrl: string): string[] => {
        const state = imageStates[index];
        return [
            resolveImageDownloadSrc(originalUrl, sourceUrl),
            state?.src || '',
            resolveImageSrc(originalUrl, sourceUrl),
            originalUrl,
        ];
    };

    const handleDownload = async (index: number, originalUrl: string) => {
        const local = await submitLocalImageDownload({
            images: [originalUrl],
            title: `${sanitizeFilename(title)}-${singleImageMode ? 'cover' : index + 1}`,
            sourceUrl,
            package: false,
        });
        if (local.accepted) {
            toast.success('Galaxy Local Engine', {
                description: dict.result.downloadImage,
            });
            return;
        }
        if (local.available && local.busy) {
            toast.error('Galaxy Local Engine', {
                description: local.message || dict.errors.downloadError,
            });
            return;
        }

        try {
            const { blob } = await fetchImageBlobCandidates(downloadCandidates(index, originalUrl));
            const prepared = await prepareImageDownloadBlob(blob, originalUrl);
            const filenameSuffix = singleImageMode ? 'cover' : String(index + 1);
            triggerBlobDownload(
                prepared.blob,
                `${sanitizeFilename(title)}-${filenameSuffix}.${prepared.extension}`,
            );
        } catch (error) {
            console.error(`Failed to download image ${index}:`, error);
            if (error instanceof ImageRelayLimitError) {
                toast.error(LOCAL_ENGINE_LABEL, { description: oversizedImageMessage() });
                return;
            }
            toast.error(dict.errors.downloadError);
        }
    };

    const handlePackageDownload = async () => {
        if (!selectedIndices.length || isPackaging) return;
        setIsPackaging(true);
        setPackagingProgress(0);

        try {
            const local = await submitLocalImageDownload({
                images: selectedIndices.map((index) => images[index]!),
                title: sanitizeFilename(title),
                sourceUrl,
                package: true,
                description,
                markdownContent,
                author,
                publishedAt,
            });
            if (local.accepted) {
                toast.success('Galaxy Local Engine', {
                    description: dict.result.packageDownload,
                });
                return;
            }
            if (local.available && local.busy) {
                toast.error('Galaxy Local Engine', {
                    description: local.message || dict.errors.packageFailed,
                });
                return;
            }
            if (selectedIndices.length > LOCAL_ENGINE_BATCH_THRESHOLD) {
                toast.error(LOCAL_ENGINE_LABEL, {
                    description: largeBatchMessage(selectedIndices.length),
                });
                return;
            }

            const { default: JSZip } = await import('jszip');
            const zip = new JSZip();
            let successCount = 0;
            const archiveImages: ArchiveImageFile[] = [];
            const safeTitle = sanitizeFilename(title);

            for (let position = 0; position < selectedIndices.length; position++) {
                const index = selectedIndices[position]!;
                const originalUrl = images[index]!;
                try {
                    const { blob } = await fetchImageBlobCandidates(downloadCandidates(index, originalUrl));
                    const prepared = await prepareImageDownloadBlob(blob, originalUrl);
                    const filename = `${safeTitle}-${index + 1}.${prepared.extension}`;
                    zip.file(filename, prepared.blob);
                    archiveImages.push({ sourceUrl: originalUrl, filename });
                    successCount++;
                } catch (error) {
                    if (error instanceof ImageRelayLimitError) throw error;
                    console.error(`Failed to add image ${index} to zip:`, error);
                }
                setPackagingProgress(Math.round(((position + 1) / selectedIndices.length) * 100));
            }

            if (successCount === 0) {
                toast.error(dict.errors.allImagesLoadFailed);
                return;
            }

            const metadata = { description, markdownContent, author, publishedAt, sourceUrl };
            const text = archiveText(title, metadata);
            if (text) zip.file(`${safeTitle}.txt`, text);
            zip.file(`${safeTitle}.md`, buildDocumentArchiveMarkdown(title, metadata, archiveImages));

            const zipBlob = await zip.generateAsync({ type: 'blob' });
            triggerBlobDownload(zipBlob, `${safeTitle}.zip`);
        } catch (error) {
            console.error('Failed to package images:', error);
            if (error instanceof ImageRelayLimitError) {
                toast.error(LOCAL_ENGINE_LABEL, { description: oversizedImageMessage() });
                return;
            }
            toast.error(dict.errors.packageFailed);
        } finally {
            setIsPackaging(false);
            setPackagingProgress(0);
        }
    };

    const loadedCount = imageStates.filter((state) => !state.loading).length;
    const allLoaded = loadedCount === images.length;
    const singleImageState = singleImageMode ? imageStates[0] : undefined;
    const shouldHideSingleImage = shouldHideSingleImagePreview(singleImageMode, singleImageState);

    if (shouldHideSingleImage) return null;

    const previewState = previewIndex === null ? undefined : imageStates[previewIndex];
    const previewDimensions = previewIndex === null ? undefined : dimensions[previewIndex];
    const movePreview = (direction: number) => setPreviewIndex((current) => current === null ? null : (current + direction + images.length) % images.length);

    return (
        <div className="space-y-3">
            {!singleImageMode && (
                <div className="space-y-3 rounded-xl border bg-background p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="min-w-0 text-xs text-muted-foreground">
                            <span className="font-medium text-foreground">{dict.result.imageNote}</span>
                            <span className="ms-2 tabular-nums">{replaceTemplate(dict.result.imageCount, '{count}', String(images.length))}</span>
                            {!allLoaded && <span className="ms-2 text-[10px]" role="status" aria-live="polite">{dict.result.imageLoadingProgress.replace('{loaded}', String(loadedCount)).replace('{total}', String(images.length))}</span>}
                        </div>
                        <Button size="sm" variant="outline" disabled={isPackaging || selectedIndices.length === 0} onClick={handlePackageDownload}>
                            {isPackaging ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Package className="h-3.5 w-3.5" aria-hidden="true" />}
                            {isPackaging ? `${dict.result.packaging} ${packagingProgress}%` : `${dict.result.packageDownload} (${selectedIndices.length})`}
                        </Button>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 border-t pt-3">
                        <span className="me-auto text-xs tabular-nums text-muted-foreground" role="status">{copy.selected.replace('{count}', String(selectedIndices.length)).replace('{total}', String(images.length))}</span>
                        <Button size="xs" variant="ghost" onClick={() => setSelected(new Set(images.map((_, index) => index)))}>{copy.all}</Button>
                        <Button size="xs" variant="ghost" onClick={() => setSelected(new Set())}>{copy.none}</Button>
                        {minimumLongEdge > 0 && <Button size="xs" variant="ghost" onClick={() => setSelected(new Set(visibleIndices))}>{copy.visible}</Button>}
                        <select aria-label={copy.dimensions} value={minimumLongEdge} onChange={(event) => setMinimumLongEdge(Number(event.target.value))} className="h-8 max-w-full rounded-md border border-input bg-background px-2 text-xs">
                            <option value={0}>{copy.any}</option>
                            {[1000, 2000].map((size) => <option key={size} value={size}>{copy.minimum.replace('{size}', String(size))}</option>)}
                        </select>
                    </div>
                    <p className="text-[11px] leading-5 text-muted-foreground">{copy.selectHint}</p>
                </div>
            )}

            {visibleIndices.length === 0 && <p role="status" className="rounded-lg border border-dashed p-5 text-center text-sm text-muted-foreground">{copy.empty}</p>}
            <div className={`${singleImageMode ? 'grid grid-cols-1' : 'grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4'} gap-3`}>
                {visibleIndices.map((index) => {
                    const imageUrl = images[index]!;
                    const state = imageStates[index];
                    const isLoading = state?.loading ?? true;
                    const hasError = state?.error ?? false;
                    const displaySrc = state?.src ?? resolveImageSrc(imageUrl, sourceUrl);
                    const size = dimensions[index];

                    return (
                        <div key={`${index}:${imageUrl}`} className="relative overflow-hidden rounded-xl border bg-background">
                            <div className={`${singleImageMode ? 'aspect-video' : 'aspect-square'} relative flex items-center justify-center bg-muted/50`}>
                                {!hasError && <Image
                                    src={displaySrc}
                                    alt={singleImageMode ? (title || dict.result.coverLabel) : replaceTemplate(dict.result.imageAlt, '{index}', String(index + 1))}
                                    fill unoptimized sizes={singleImageMode ? '(max-width: 1024px) 100vw, 720px' : '(max-width: 640px) 50vw, 25vw'}
                                    className={`workspace-image object-contain transition-opacity duration-150 ${isLoading ? 'opacity-0' : 'opacity-100'}`}
                                    onLoad={(event) => handleImageLoad(index, event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)}
                                    onError={() => handleImageError(index, imageUrl)}
                                />}
                                {isLoading && <div className="absolute inset-0 flex items-center justify-center" role="status"><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" /><span className="sr-only">{dict.result.loading}</span></div>}
                                {!isLoading && hasError && <div className="absolute inset-0 flex flex-col items-center justify-center px-3 text-center text-xs text-muted-foreground"><span>{singleImageMode ? dict.result.coverLabel : replaceTemplate(dict.result.imageIndexLabel, '{index}', String(index + 1))}</span><span className="mt-1">{dict.result.loadFailed}</span></div>}
                                {!singleImageMode && <label className="absolute start-2 top-2 flex h-8 w-8 items-center justify-center rounded-lg border bg-background/95 shadow-sm"><input type="checkbox" checked={selected.has(index)} aria-label={`${copy.select} ${index + 1}`} className="h-4 w-4 accent-primary" onChange={(event) => setSelected((previous) => { const next = new Set(previous); if (event.target.checked) next.add(index); else next.delete(index); return next; })} /></label>}
                            </div>
                            <div className="flex min-h-12 items-center gap-1 border-t px-2 py-1.5">
                                <div className="me-auto min-w-0 text-[11px] tabular-nums text-muted-foreground"><span className="font-medium text-foreground">{index + 1}</span>{size && <span className="ms-2">{size.width} × {size.height}</span>}</div>
                                <Button size="icon" variant="ghost" className="h-8 w-8" disabled={isLoading || hasError} aria-label={`${copy.preview} ${index + 1}`} onClick={(event) => { previewTriggerRef.current = event.currentTarget; setPreviewIndex(index); }}><Expand className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                                <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => void handleDownload(index, imageUrl)} aria-label={`${singleImageMode ? dict.result.downloadCover : dict.result.downloadImage} ${index + 1}`}><Download className="h-3.5 w-3.5" aria-hidden="true" /></Button>
                            </div>
                        </div>
                    );
                })}
            </div>

            <Dialog open={previewIndex !== null} onOpenChange={(open) => { if (!open) setPreviewIndex(null); }}>
                <DialogContent className="max-h-[94dvh] max-w-5xl overflow-y-auto overscroll-contain rounded-xl p-4 sm:p-5" onCloseAutoFocus={(event) => { event.preventDefault(); previewTriggerRef.current?.focus(); }} onKeyDown={(event) => {
                    if (event.key === 'ArrowLeft') { event.preventDefault(); movePreview(-1); }
                    if (event.key === 'ArrowRight') { event.preventDefault(); movePreview(1); }
                }}>
                    <DialogTitle className="pe-8">{title || copy.preview}</DialogTitle>
                    <DialogDescription>{previewIndex === null ? '' : `${previewIndex + 1} / ${images.length}`}{previewDimensions ? ` · ${previewDimensions.width} × ${previewDimensions.height} px` : ''}</DialogDescription>
                    {previewIndex !== null && <div className="relative flex h-[min(65dvh,720px)] min-h-40 items-center justify-center rounded-lg bg-muted/50">
                        {previewState?.error ? <p className="text-sm text-muted-foreground">{dict.result.loadFailed}</p> : <Image src={previewState?.src || resolveImageSrc(images[previewIndex]!, sourceUrl)} alt={replaceTemplate(dict.result.imageAlt, '{index}', String(previewIndex + 1))} fill unoptimized sizes="(max-width: 1024px) 100vw, 1000px" className="workspace-image object-contain" onError={() => handleImageError(previewIndex, images[previewIndex]!)} onLoad={(event) => handleImageLoad(previewIndex, event.currentTarget.naturalWidth, event.currentTarget.naturalHeight)} />}
                    </div>}
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex gap-2"><Button variant="outline" size="sm" disabled={images.length < 2} onClick={() => movePreview(-1)}><ChevronLeft className="h-4 w-4" aria-hidden="true" />{copy.previous}</Button><Button variant="outline" size="sm" disabled={images.length < 2} onClick={() => movePreview(1)}>{copy.next}<ChevronRight className="h-4 w-4" aria-hidden="true" /></Button></div>
                        <Button size="sm" onClick={() => { if (previewIndex !== null) void handleDownload(previewIndex, images[previewIndex]!); }}><Download className="h-4 w-4" aria-hidden="true" />{dict.result.downloadImage}</Button>
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}
