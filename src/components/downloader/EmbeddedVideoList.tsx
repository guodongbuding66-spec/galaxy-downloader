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
        if (autoScrollIndex < 0) return;
        setMobileVisibleCount((previous) => Math.max(previous, autoScrollIndex + 1));
    }, [autoScrollIndex, setMobileVisibleCount]);

    useEffect(() => {
        if (!autoScrollKey || !autoScrollItemId || lastAutoScrolledKeyRef.current === autoScrollKey) return;

        const element = itemRefs.current.get(autoScrollItemId);
        const container = containerRef.current;
        if (!element || !container) return;

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
        <div className="space-y-1.5">
            <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 text-[11px] font-medium text-muted-foreground">
                    {dict.result.videoList}
                    <span className="ms-1.5 tabular-nums">
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
                    className="h-8 w-40 rounded-md text-xs sm:w-48"
                />
            </div>
            <div
                ref={containerRef}
                className="max-h-[min(56vh,26rem)] overflow-y-auto overscroll-contain border-y md:max-h-[min(60vh,32rem)]"
            >
                <div className="divide-y">
                    {filteredVideos.length === 0 && (
                        <p className="py-6 text-center text-xs text-muted-foreground">
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
                                    if (!video.id) return;
                                    if (element) itemRefs.current.set(video.id, element);
                                    else itemRefs.current.delete(video.id);
                                }}
                                aria-current={isCurrentItem ? 'true' : undefined}
                                className={`grid min-h-10 w-full min-w-0 gap-1.5 px-1.5 py-1.5 text-left transition-colors md:grid-cols-[minmax(0,1fr)_auto] md:items-center ${
                                    isCurrentItem ? 'bg-muted font-medium' : 'hover:bg-muted/50'
                                }`}
                                style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 48px' }}
                            >
                                <div className="flex min-w-0 items-center gap-2">
                                    <span className={`w-7 shrink-0 text-[11px] tabular-nums ${isCurrentItem ? 'text-foreground' : 'text-muted-foreground'}`}>
                                        {originalIndex + 1}
                                    </span>
                                    <span className="min-w-0 flex-1 truncate text-xs" title={displayTitle}>
                                        {displayTitle}
                                    </span>
                                    {video.duration != null && (
                                        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                                            {formatDuration(video.duration)}
                                        </span>
                                    )}
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
                        <div className="p-1.5">
                            {remainingCount > 0 ? (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="w-full text-xs text-muted-foreground"
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
                                    variant="ghost"
                                    size="sm"
                                    className="w-full text-xs text-muted-foreground"
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
