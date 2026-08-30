import { Button } from '@/components/ui/button';
import { useDictionary } from '@/i18n/client';
import type { PageInfo } from '@/lib/types';
import { formatDuration } from '@/lib/utils';

import { CollectionItemActions, type CollectionPreviewMediaType } from './CollectionItemActions';
import { canPreviewPageAudio, canPreviewPageVideo } from './media-preview';
import { LOAD_MORE_BATCH, useChunkedMobileList } from './use-chunked-mobile-list';
import { replaceTemplate } from './result-card-utils';
import { useTemporaryDownloadKeys } from './use-temporary-download-keys';

const DEFAULT_VISIBLE_PARTS = 100;

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
    const {
        canCollapseMobile,
        collapse,
        isMobile,
        loadMore,
        minimumVisibleCount,
        remainingCount,
        visibleItems: visiblePages,
    } = useChunkedMobileList(pages, Math.max(DEFAULT_VISIBLE_PARTS, currentPage || 1));

    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between gap-2 text-xs font-medium text-foreground/75">
                <span>
                    {replaceTemplate(dict.result.totalParts, '{count}', String(pages.length))}
                </span>
            </div>
            <div className="max-h-[min(56vh,26rem)] overflow-y-auto overscroll-contain pe-1 md:max-h-[min(60vh,32rem)]">
                <div className="space-y-2 pe-2">
                    {visiblePages.map((page) => {
                        const displayTitle = page.part?.trim() || `P${page.page}`;
                        const videoKey = `${page.page}-video`;
                        const audioKey = `${page.page}-audio`;
                        const isCurrentPage = page.page === currentPage;

                        return (
                            <div
                                key={page.page}
                                aria-current={isCurrentPage ? 'true' : undefined}
                                className={`flex w-full max-w-full flex-col gap-3 overflow-hidden rounded-xl border p-3 text-left transition-colors md:grid md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-4 ${
                                    isCurrentPage
                                        ? 'border-primary/70 bg-primary/5 ring-1 ring-primary/15'
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
