import { useState } from 'react';
import { Download, Loader2, Package } from 'lucide-react';
import Image from 'next/image';

import { Button } from '@/components/ui/button';
import { useDictionary } from '@/i18n/client';
import { toast } from '@/lib/deferred-toast';
import { sanitizeFilename } from '@/lib/utils';

import { shouldHideSingleImagePreview } from './result-card-visibility';
import {
    createInitialImageStates,
    fetchImageBlobCandidates,
    replaceTemplate,
    resolveImageDownloadExtension,
    resolveImageSrc,
    triggerBlobDownload,
    type ImageLoadState,
} from './result-card-utils';

export function ImageNoteGrid({
    images,
    title,
    singleImageMode = false,
}: {
    images: string[];
    title: string;
    singleImageMode?: boolean;
}) {
    const imageSetKey = images.map(resolveImageSrc).join('\u0000');

    return (
        <ImageNoteGridContent
            key={imageSetKey}
            images={images}
            title={title}
            singleImageMode={singleImageMode}
        />
    );
}

function ImageNoteGridContent({
    images,
    title,
    singleImageMode = false,
}: {
    images: string[];
    title: string;
    singleImageMode?: boolean;
}) {
    const dict = useDictionary();
    const [imageStates, setImageStates] = useState<ImageLoadState[]>(() => createInitialImageStates(images));
    const [isPackaging, setIsPackaging] = useState(false);
    const [packagingProgress, setPackagingProgress] = useState(0);

    const updateImageState = (index: number, updater: (state: ImageLoadState) => ImageLoadState) => {
        setImageStates((previous) => previous.map((state, currentIndex) => (
            currentIndex === index ? updater(state) : state
        )));
    };

    const handleImageLoad = (index: number) => {
        updateImageState(index, (state) => ({ ...state, loading: false, error: false }));
    };

    const handleImageError = (index: number, originalUrl: string) => {
        updateImageState(index, (state) => {
            if (!state.usedFallback && state.src !== originalUrl) {
                return { ...state, loading: true, error: false, src: originalUrl, usedFallback: true };
            }
            return { ...state, loading: false, error: true };
        });
    };

    const handleDownload = async (index: number, originalUrl: string) => {
        try {
            const state = imageStates[index];
            const { blob, sourceUrl } = await fetchImageBlobCandidates([
                state?.src ?? resolveImageSrc(originalUrl),
                originalUrl,
            ]);
            const extension = resolveImageDownloadExtension(sourceUrl, blob.type);
            const filenameSuffix = singleImageMode ? 'cover' : String(index + 1);
            triggerBlobDownload(blob, `${sanitizeFilename(title)}-${filenameSuffix}.${extension}`);
        } catch (error) {
            console.error(`Failed to download image ${index}:`, error);
            toast.error(dict.errors.downloadError);
        }
    };

    const handlePackageDownload = async () => {
        setIsPackaging(true);
        setPackagingProgress(0);

        try {
            const { default: JSZip } = await import('jszip');
            const zip = new JSZip();
            let successCount = 0;

            for (let index = 0; index < images.length; index++) {
                const state = imageStates[index];
                const hasError = state?.error ?? false;
                if (!hasError) {
                    try {
                        const { blob, sourceUrl } = await fetchImageBlobCandidates([
                            state?.src ?? resolveImageSrc(images[index]!),
                            images[index]!,
                        ]);
                        const extension = resolveImageDownloadExtension(sourceUrl, blob.type);
                        zip.file(`${sanitizeFilename(title)}-${index + 1}.${extension}`, blob);
                        successCount++;
                    } catch (error) {
                        console.error(`Failed to add image ${index} to zip:`, error);
                    }
                }
                setPackagingProgress(Math.round(((index + 1) / images.length) * 100));
            }

            if (successCount === 0) {
                toast.error(dict.errors.allImagesLoadFailed);
                return;
            }

            const zipBlob = await zip.generateAsync({ type: 'blob' });
            triggerBlobDownload(zipBlob, `${sanitizeFilename(title)}.zip`);
        } catch (error) {
            console.error('Failed to package images:', error);
            toast.error(dict.errors.packageFailed);
        } finally {
            setIsPackaging(false);
            setPackagingProgress(0);
        }
    };

    const loadedCount = imageStates.filter((state) => !state.loading).length;
    const allLoaded = loadedCount === images.length;
    const successCount = imageStates.filter((state) => !state.error).length;
    const singleImageState = singleImageMode ? imageStates[0] : undefined;
    const shouldHideSingleImage = shouldHideSingleImagePreview(singleImageMode, singleImageState);

    if (shouldHideSingleImage) return null;

    return (
        <div className="space-y-2">
            {!singleImageMode && (
                <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground">{dict.result.imageNote}</span>
                        <span className="ms-1.5 tabular-nums">
                            {replaceTemplate(dict.result.imageCount, '{count}', String(images.length))}
                        </span>
                        {!allLoaded && (
                            <span className="ms-1.5 text-[10px]" role="status" aria-live="polite">
                                {dict.result.imageLoadingProgress.replace('{loaded}', String(loadedCount)).replace('{total}', String(images.length))}
                            </span>
                        )}
                    </div>
                    <Button
                        size="xs"
                        variant="outline"
                        disabled={!allLoaded || isPackaging || successCount === 0}
                        onClick={handlePackageDownload}
                        className="shrink-0"
                    >
                        {isPackaging ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Package className="h-3.5 w-3.5" aria-hidden="true" />}
                        <span>{isPackaging ? `${dict.result.packaging} ${packagingProgress}%` : dict.result.packageDownload}</span>
                    </Button>
                </div>
            )}

            <div className={`${singleImageMode ? 'grid grid-cols-1' : 'grid grid-cols-2'} max-h-[34rem] gap-2 overflow-y-auto pe-0.5`}>
                {images.map((imageUrl, index) => {
                    const state = imageStates[index];
                    const isLoading = state?.loading ?? true;
                    const hasError = state?.error ?? false;
                    const displaySrc = state?.src ?? resolveImageSrc(imageUrl);

                    return (
                        <div
                            key={index}
                            className="group relative overflow-hidden rounded-md bg-muted outline outline-1 outline-black/10 dark:outline-white/10"
                        >
                            <div className={`${singleImageMode ? 'aspect-video' : 'aspect-square'} relative flex items-center justify-center bg-muted`}>
                                {!hasError && (
                                    <Image
                                        src={displaySrc}
                                        alt={singleImageMode ? (title || dict.result.coverLabel) : replaceTemplate(dict.result.imageAlt, '{index}', String(index + 1))}
                                        fill
                                        unoptimized
                                        sizes={singleImageMode ? '(max-width: 1024px) 100vw, 720px' : '(max-width: 768px) 50vw, 33vw'}
                                        className={`object-cover transition-opacity duration-150 ${isLoading ? 'opacity-0' : 'opacity-100'}`}
                                        onLoad={() => handleImageLoad(index)}
                                        onError={() => handleImageError(index, imageUrl)}
                                    />
                                )}
                                {isLoading && (
                                    <div className="absolute inset-0 flex items-center justify-center" role="status">
                                        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden="true" />
                                        <span className="sr-only">{dict.result.loading}</span>
                                    </div>
                                )}
                                {!isLoading && hasError && (
                                    <div className="absolute inset-0 flex flex-col items-center justify-center px-3 text-center text-[11px] text-muted-foreground">
                                        <span>{singleImageMode ? dict.result.coverLabel : replaceTemplate(dict.result.imageIndexLabel, '{index}', String(index + 1))}</span>
                                        <span className="mt-1 opacity-70">{dict.result.loadFailed}</span>
                                    </div>
                                )}
                            </div>

                            {!isLoading && !hasError && (
                                <div className="absolute bottom-1.5 end-1.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100">
                                    <Button
                                        size="icon"
                                        variant="secondary"
                                        className="h-8 w-8 rounded-md bg-background/90 backdrop-blur-sm"
                                        onClick={() => void handleDownload(index, imageUrl)}
                                        aria-label={singleImageMode ? dict.result.downloadCover : dict.result.downloadImage}
                                    >
                                        <Download className="h-3.5 w-3.5" aria-hidden="true" />
                                    </Button>
                                </div>
                            )}

                            {!singleImageMode && (
                                <div className="absolute end-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-white">
                                    {index + 1}
                                </div>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}