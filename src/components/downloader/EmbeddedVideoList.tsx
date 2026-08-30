import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDictionary } from '@/i18n/client';
import type { EmbeddedVideoInfo } from '@/lib/types';
import { formatDuration } from '@/lib/utils';

import { CollectionItemActions, type CollectionPreviewMediaType } from './CollectionItemActions';
import { canPreviewEmbeddedVideoAudio, canPreviewEmbeddedVideoVideo } from './media-preview';
import { LOAD_MORE_BATCH, useChunkedMobileList } from './use-chunked-mobile-list';
import { replaceTemplate } from './result-card-utils';
import { useTemporaryDownloadKeys } from './use-temporary-download-keys';

const DEFAULT_VISIBLE_PARTS = 100;

export function EmbeddedVideoList({
    videos,
    currentItemId,
    autoScrollKey,
    autoScrollItemId,
    onSelectItem,
}: {
    videos: EmbeddedVideoInfo[];
    currentItemId?: string;
    autoScrollKey?: string;
    autoScrollItemId?: string;
    onSelectItem?: (itemId: string, mediaType: CollectionPreviewMediaType) => void;
}) {
    const dict = useDictionary();
    const { loadingKeys, triggerDownload } = useTemporaryDownloadKeys();
    const [searchQuery, setSearchQuery] = useState('');
    const containerRef = useRef<HTMLDivElement | null>(null);
    const itemRefs = useRef(new Map<string, HTMLDivElement>());
    const lastAutoScrolledKeyRef = useRef<string | null>(null);
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const indexedVideos = useMemo(
        () => videos.map((video, originalIndex) => ({ video, originalIndex })),
        [videos]
    );
    const filteredVideos = useMemo(
        () => normalizedQuery
            ? indexedVideos.filter(({ video }) => (video.title || '').toLowerCase().includes(normalizedQuery))
            : indexedVideos,
        [indexedVideos, normalizedQuery]
    );
    const autoScrollIndex = useMemo(
        () => filteredVideos.findIndex(({ video }) => video.id === autoScrollItemId),
        [autoScrollItemId, filteredVideos]
    );
    const {
        canCollapseMobile,
        collapse,
        isMobile,
        loadMore,
        minimumVisibleCount,
        remainingCount,
        setMobileVisibleCount,
        visibleItems: visibleVideos,
    } = useChunkedMobileList(
        filteredVideos,
        autoScrollIndex >= 0 ? Math.max(DEFAULT_VISIBLE_PARTS, autoScrollIndex + 1) : DEFAULT_VISIBLE_PARTS
    );

    useEffect(() => {
        if (autoScrollIndex < 0) {
            return;
        }

        setMobileVisibleCount((previous) => Math.max(previous, autoScrollIndex + 1));
    }, [autoScrollIndex, setMobileVisibleCount]);

    useEffect(() => {
        if (!autoScrollKey || !autoScrollItemId || lastAutoScrolledKeyRef.current === autoScrollKey) {
            return;
        }

        const element = itemRefs.current.get(autoScrollItemId);
        const container = containerRef.current;
        if (!element || !container) {
            return;
        }

        const containerRect = container.getBoundingClientRect();
        const elementRect = element.getBoundingClientRect();

        if (elementRect.top < containerRect.top) {
            container.scrollTop += elementRect.top - containerRect.top;
        } else if (elementRect.bottom > containerRect.bottom) {
            container.scrollTop += elementRect.bottom - containerRect.bottom;
        }

        lastAutoScrolledKeyRef.current = autoScrollKey;
    }, [autoScrollItemId, autoScrollKey, visibleVideos.length]);

    return (
        <div className="space-y-3">
            <div className="flex flex-col gap-2 text-xs text-foreground/75 sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0 font-medium">
                    <span>{dict.result.videoList}</span>
                    <span className="ms-2 text-muted-foreground">
                        {replaceTemplate(dict.result.videoCount, '{count}', String(filteredVideos.length))}
                    </span>
                </span>
                <Input
                    value={searchQuery}
                    onChange={(event) => {
                        setSearchQuery(event.target.value);
                        setMobileVisibleCount(minimumVisibleCount);
                    }}
                    placeholder={dict.result.collectionSearchPlaceholder}
                    aria-label={dict.result.collectionSearchPlaceholder}
                    className="h-11 w-full text-base sm:h-10 sm:w-56 sm:text-sm"
                />
            </div>
            <div
                ref={containerRef}
                className="max-h-[min(56vh,26rem)] overflow-y-auto overscroll-contain pe-1 md:max-h-[min(60vh,32rem)]"
            >
                <div className="space-y-2 pe-2">
                    {filteredVideos.length === 0 && (
                        <p className="py-6 text-center text-sm text-muted-foreground">
                            {dict.result.collectionNoSearchResults}
                        </p>
                    )}
                    {visibleVideos.map(({ video, originalIndex }) => {
                        const videoDownloadUrl = video.downloadVideoUrl || video.originDownloadVideoUrl || null;
                        const audioDownloadUrl = video.downloadAudioUrl || video.originDownloadAudioUrl || null;
                        const displayTitle = video.title?.trim()
                            || replaceTemplate(dict.result.articleVideoUntitled, '{index}', String(originalIndex + 1));
                        const videoKey = `${video.id || originalIndex}-video`;
                        const audioKey = `${video.id || originalIndex}-audio`;
                        const isCurrentItem = Boolean(currentItemId) && video.id === currentItemId;

                        return (
                            <div
                                key={video.id || originalIndex}
                                ref={(element) => {
                                    if (!video.id) {
                                        return;
                                    }

                                    if (element) {
                                        itemRefs.current.set(video.id, element);
                                    } else {
                                        itemRefs.current.delete(video.id);
                                    }
                                }}
                                aria-current={isCurrentItem ? 'true' : undefined}
                                className={`flex w-full max-w-full flex-col gap-3 overflow-hidden rounded-xl border p-3 text-left transition-colors md:grid md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-4 ${
                                    isCurrentItem
                                        ? 'border-primary/70 bg-primary/5 ring-1 ring-primary/15'
                                        : 'border-border/80 bg-background/60 hover:bg-muted/40'
                                }`}
                                style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 128px' }}
                            >
                                <div className="flex w-full min-w-0 items-start gap-3 overflow-hidden">
                                    <span className={`mt-0.5 shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold tabular-nums ${
                                        isCurrentItem ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground/70'
                                    }`}>
                                        {originalIndex + 1}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <div className="line-clamp-2 break-words text-[13px] font-medium leading-5" title={displayTitle}>
                                            {displayTitle}
                                        </div>
                                        {video.duration != null && (
                                            <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                                                {formatDuration(video.duration)}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <CollectionItemActions
                                    title={displayTitle}
                                    canPlayVideo={canPreviewEmbeddedVideoVideo(video)}
                                    canPlayAudio={canPreviewEmbeddedVideoAudio(video)}
                                    videoDownloadUrl={videoDownloadUrl}
                                    audioDownloadUrl={audioDownloadUrl}
                                    videoLoading={loadingKeys.has(videoKey)}
                                    audioLoading={loadingKeys.has(audioKey)}
                                    onPlay={(mediaType) => onSelectItem?.(video.id, mediaType)}
                                    onDownloadVideo={(url) => triggerDownload(url, videoKey)}
                                    onDownloadAudio={(url) => triggerDownload(url, audioKey)}
                                />
                            </div>
                        );
                    })}
                    {isMobile && (remainingCount > 0 || canCollapseMobile) && (
                        <div className="rounded-xl border border-border/70 p-2">
                            {remainingCount > 0 ? (
                                <Button
                                    type="button"
                                    variant="outline"
                                    className="min-h-10 w-full text-xs"
                                    onClick={loadMore}
                                >
                                    {replaceTemplate(
                                        dict.result.loadMoreItems,
                                        '{count}',
                                        String(Math.min(LOAD_MORE_BATCH, remainingCount))
                                    )}
                                </Button>
                            ) : (
                                <Button
                                    type="button"
                                    variant="outline"
                                    className="min-h-10 w-full text-xs"
                                    onClick={collapse}
                                >
                                    {replaceTemplate(dict.result.collapseParts, '{count}', String(minimumVisibleCount))}
                                </Button>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
