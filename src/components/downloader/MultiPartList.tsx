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
        <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">
                {replaceTemplate(dict.result.totalParts, '{count}', String(pages.length))}
            </div>
            <div className="max-h-[min(56vh,26rem)] overflow-y-auto overscroll-contain border-y md:max-h-[min(60vh,32rem)]">
                <div className="divide-y">
                    {visiblePages.map((page) => {
                        const displayTitle = page.part?.trim() || `P${page.page}`;
                        const videoKey = `${page.page}-video`;
                        const audioKey = `${page.page}-audio`;
                        const isCurrentPage = page.page === currentPage;

                        return (
                            <div
                                key={page.page}
                                aria-current={isCurrentPage ? 'true' : undefined}
                                className={`grid min-h-10 w-full min-w-0 gap-1.5 px-1.5 py-1.5 text-left transition-colors md:grid-cols-[minmax(0,1fr)_auto] md:items-center ${
                                    isCurrentPage ? 'bg-muted font-medium' : 'hover:bg-muted/50'
                                }`}
                                style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 48px' }}
                            >
                                <div className="flex min-w-0 items-center gap-2">
                                    <span className={`w-8 shrink-0 text-[11px] tabular-nums ${isCurrentPage ? 'text-foreground' : 'text-muted-foreground'}`}>
                                        P{page.page}
                                    </span>
                                    <span className="min-w-0 flex-1 truncate text-xs" title={displayTitle}>
                                        {displayTitle}
                                    </span>
                                    {page.duration != null && (
                                        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                                            {formatDuration(page.duration)}
                                        </span>
                                    )}
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
