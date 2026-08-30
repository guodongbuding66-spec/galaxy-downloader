import { useEffect, useMemo, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDictionary } from '@/i18n/client';
import type { PageInfo } from '@/lib/types';
import { formatDuration } from '@/lib/utils';

import { CollectionItemActions, type CollectionPreviewMediaType } from './CollectionItemActions';
import { canPreviewPageAudio, canPreviewPageVideo } from './media-preview';
import { replaceTemplate } from './result-card-utils';
import { LOAD_MORE_BATCH, useChunkedMobileList } from './use-chunked-mobile-list';
import { useTemporaryDownloadKeys } from './use-temporary-download-keys';

const DEFAULT_VISIBLE_PARTS = 36;

export function MultiPartList({
    pages,
    currentPage,
    onSelectPage,
}: {
    pages: PageInfo[];
    currentPage?: number;
    onSelectPage?: (page: number, mediaType: CollectionPreviewMediaType) => void;
}) {
    const dict = useDictionary();
    const { loadingKeys, triggerDownload } = useTemporaryDownloadKeys();
    const [searchQuery, setSearchQuery] = useState('');
    const containerRef = useRef<HTMLDivElement | null>(null);
    const itemRefs = useRef(new Map<number, HTMLDivElement>());
    const lastAutoScrolledKeyRef = useRef<string | null>(null);
    const normalizedQuery = searchQuery.trim().toLowerCase();

    const filteredPages = useMemo(() => {
        if (!normalizedQuery) return pages;

        return pages.filter((page) => {
            const title = page.part?.trim().toLowerCase() || '';
            const pageNumber = String(page.page);
            return title.includes(normalizedQuery)
                || pageNumber.includes(normalizedQuery)
                || `p${pageNumber}`.includes(normalizedQuery);
        });
    }, [normalizedQuery, pages]);

    const autoScrollIndex = useMemo(
        () => filteredPages.findIndex((page) => page.page === currentPage),
        [currentPage, filteredPages]
    );
    const {
        canCollapseMobile,
        collapse,
        isMobile,
        loadMore,
        minimumVisibleCount,
        remainingCount,
        setMobileVisibleCount,
        visibleItems: visiblePages,
    } = useChunkedMobileList(
        filteredPages,
        autoScrollIndex >= 0 ? Math.max(DEFAULT_VISIBLE_PARTS, autoScrollIndex + 1) : DEFAULT_VISIBLE_PARTS
    );

    useEffect(() => {
        if (autoScrollIndex < 0) return;
        setMobileVisibleCount((previous) => Math.max(previous, autoScrollIndex + 1));
    }, [autoScrollIndex, setMobileVisibleCount]);

    useEffect(() => {
        if (!currentPage || autoScrollIndex < 0) return;

        const autoScrollKey = `${pages.length}:${currentPage}:${normalizedQuery}`;
        if (lastAutoScrolledKeyRef.current === autoScrollKey) return;

        const element = itemRefs.current.get(currentPage);
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
    }, [autoScrollIndex, currentPage, normalizedQuery, pages.length, visiblePages.length]);

    return (
        <div className="space-y-3">
            <div className="flex flex-col gap-2 text-xs text-foreground/75 sm:flex-row sm:items-center sm:justify-between">
                <span className="min-w-0 font-medium">
                    {replaceTemplate(dict.result.totalParts, '{count}', String(pages.length))}
                    {normalizedQuery && (
                        <span className="ms-2 tabular-nums text-muted-foreground">
                            {filteredPages.length}/{pages.length}
                        </span>
                    )}
                </span>
                <Input
                    type="search"
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
                <div className="space-y-2 pe-2" role="list">
                    {filteredPages.length === 0 && (
                        <p className="py-6 text-center text-sm text-muted-foreground">
                            {dict.result.collectionNoSearchResults}
                        </p>
                    )}
                    {visiblePages.map((page) => {
                        const displayTitle = page.part?.trim() || `P${page.page}`;
                        const videoKey = `${page.page}-video`;
                        const audioKey = `${page.page}-audio`;
                        const isCurrentPage = page.page === currentPage;

                        return (
                            <div
                                key={page.page}
                                ref={(element) => {
                                    if (element) {
                                        itemRefs.current.set(page.page, element);
                                    } else {
                                        itemRefs.current.delete(page.page);
                                    }
                                }}
                                role="listitem"
                                aria-current={isCurrentPage ? 'true' : undefined}
                                className={`flex w-full max-w-full flex-col gap-3 overflow-hidden rounded-xl border p-3 text-left transition-colors md:grid md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-4 ${
                                    isCurrentPage
                                        ? 'border-primary bg-primary/5 ring-1 ring-primary/15'
                                        : 'border-border/80 bg-background/60 hover:bg-muted/40'
                                }`}
                                style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 128px' }}
                            >
                                <div className="flex w-full min-w-0 items-start gap-3 overflow-hidden">
                                    <span className={`mt-0.5 shrink-0 rounded-md px-2 py-1 text-[11px] font-semibold tabular-nums ${
                                        isCurrentPage ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground/70'
                                    }`}>
                                        P{page.page}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <div className="line-clamp-2 break-words text-[13px] font-medium leading-5" title={displayTitle}>
                                            {displayTitle}
                                        </div>
                                        {page.duration != null && (
                                            <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                                                {formatDuration(page.duration)}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <CollectionItemActions
                                    title={displayTitle}
                                    canPlayVideo={canPreviewPageVideo(page)}
                                    canPlayAudio={canPreviewPageAudio(page)}
                                    videoDownloadUrl={page.downloadVideoUrl}
                                    audioDownloadUrl={page.downloadAudioUrl}
                                    videoLoading={loadingKeys.has(videoKey)}
                                    audioLoading={loadingKeys.has(audioKey)}
                                    onPlay={(mediaType) => onSelectPage?.(page.page, mediaType)}
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
