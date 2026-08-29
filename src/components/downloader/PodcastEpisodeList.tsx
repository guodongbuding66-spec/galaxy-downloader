import { useEffect, useMemo, useRef, useState } from 'react';
import { Headphones, Search } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useDictionary } from '@/i18n/client';
import type { PodcastEpisodeInfo } from '@/lib/types';
import { formatDuration } from '@/lib/utils';

import { AudioDownloadIcon } from './CustomIcons';
import { MediaActionIconButton } from './MediaActionIconButton';
import { replaceTemplate } from './result-card-utils';
import { LOAD_MORE_BATCH, useChunkedMobileList } from './use-chunked-mobile-list';
import { useTemporaryDownloadKeys } from './use-temporary-download-keys';

const DEFAULT_VISIBLE_EPISODES = 100;

export function PodcastEpisodeList({
    episodes,
    currentEpisodeId,
    autoScrollKey,
    autoScrollEpisodeId,
    onSelectEpisode,
}: {
    episodes: PodcastEpisodeInfo[];
    currentEpisodeId?: string;
    autoScrollKey?: string;
    autoScrollEpisodeId?: string;
    onSelectEpisode?: (episodeId: string) => void;
}) {
    const dict = useDictionary();
    const { loadingKeys, triggerDownload } = useTemporaryDownloadKeys();
    const [searchQuery, setSearchQuery] = useState('');
    const containerRef = useRef<HTMLDivElement | null>(null);
    const itemRefs = useRef(new Map<string, HTMLDivElement>());
    const lastAutoScrolledKeyRef = useRef<string | null>(null);
    const normalizedQuery = searchQuery.trim().toLowerCase();
    const filteredEpisodes = normalizedQuery
        ? episodes.filter((episode) => episode.title.toLowerCase().includes(normalizedQuery))
        : episodes;
    const autoScrollIndex = useMemo(
        () => filteredEpisodes.findIndex((episode) => episode.id === autoScrollEpisodeId),
        [autoScrollEpisodeId, filteredEpisodes]
    );
    const {
        canCollapseMobile,
        collapse,
        isMobile,
        loadMore,
        minimumVisibleCount,
        remainingCount,
        setMobileVisibleCount,
        visibleItems: visibleEpisodes,
    } = useChunkedMobileList(
        filteredEpisodes,
        autoScrollIndex >= 0 ? Math.max(DEFAULT_VISIBLE_EPISODES, autoScrollIndex + 1) : DEFAULT_VISIBLE_EPISODES
    );

    useEffect(() => {
        if (autoScrollIndex < 0) return;
        setMobileVisibleCount((previous) => Math.max(previous, autoScrollIndex + 1));
    }, [autoScrollIndex, setMobileVisibleCount]);

    useEffect(() => {
        if (!autoScrollKey || !autoScrollEpisodeId || lastAutoScrolledKeyRef.current === autoScrollKey) return;
        const element = itemRefs.current.get(autoScrollEpisodeId);
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
    }, [autoScrollEpisodeId, autoScrollKey, visibleEpisodes.length]);

    return (
        <div className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-sm font-medium text-foreground/75">
                    {replaceTemplate(dict.result.videoCount, '{count}', String(filteredEpisodes.length))}
                </span>
                <div className="relative w-full sm:w-64">
                    <Search className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                    <Input
                        value={searchQuery}
                        onChange={(event) => {
                            setSearchQuery(event.target.value);
                            setMobileVisibleCount(minimumVisibleCount);
                        }}
                        placeholder={dict.result.collectionSearchPlaceholder}
                        aria-label={dict.result.collectionSearchPlaceholder}
                        className="min-h-11 w-full ps-9 text-base sm:text-sm"
                    />
                </div>
            </div>

            <div
                ref={containerRef}
                className="max-h-[min(58vh,32rem)] overflow-y-auto overscroll-contain pe-1 md:max-h-[min(62vh,38rem)]"
            >
                <div className="space-y-2 pe-2">
                    {filteredEpisodes.length === 0 && (
                        <p className="rounded-xl border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
                            {dict.result.collectionNoSearchResults}
                        </p>
                    )}

                    {visibleEpisodes.map((episode, index) => {
                        const audioUrl = episode.downloadAudioUrl || episode.originDownloadAudioUrl || null;
                        const downloadKey = `${episode.id}-audio`;
                        const isCurrentItem = Boolean(currentEpisodeId) && episode.id === currentEpisodeId;

                        return (
                            <div
                                key={episode.id}
                                ref={(element) => {
                                    if (element) {
                                        itemRefs.current.set(episode.id, element);
                                    } else {
                                        itemRefs.current.delete(episode.id);
                                    }
                                }}
                                aria-current={isCurrentItem ? 'true' : undefined}
                                className={`flex w-full max-w-full flex-col gap-3 overflow-hidden rounded-xl border bg-background p-3 text-start transition-colors duration-150 md:grid md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-3 ${
                                    isCurrentItem
                                        ? 'border-primary/50 bg-primary/5'
                                        : 'border-border hover:bg-muted/30'
                                }`}
                            >
                                <div className="flex min-w-0 w-full items-start gap-3 overflow-hidden">
                                    <span className="flex h-7 min-w-7 shrink-0 items-center justify-center rounded-lg bg-muted px-1.5 text-xs font-semibold tabular-nums text-foreground/70">
                                        {index + 1}
                                    </span>
                                    <div className="min-w-0 flex-1 space-y-1">
                                        <div className="line-clamp-2 text-sm font-medium leading-5 break-words" title={episode.title}>
                                            {episode.title}
                                        </div>
                                        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                            {episode.duration != null && (
                                                <span className="tabular-nums">{formatDuration(episode.duration)}</span>
                                            )}
                                            {episode.releaseDate && (
                                                <span>{episode.releaseDate}</span>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 md:w-44 md:grid-cols-1">
                                    <MediaActionIconButton
                                        label={`${dict.result.playAudio}: ${episode.title}`}
                                        text={dict.result.playAudio}
                                        icon={Headphones}
                                        variant="secondary"
                                        disabled={isCurrentItem}
                                        className="min-h-10 w-full"
                                        onClick={() => onSelectEpisode?.(episode.id)}
                                    />
                                    {audioUrl && (
                                        <MediaActionIconButton
                                            label={`${dict.result.downloadAudio}: ${episode.title}`}
                                            text={dict.result.downloadAudio}
                                            icon={AudioDownloadIcon}
                                            variant="outline"
                                            disabled={loadingKeys.has(downloadKey)}
                                            loading={loadingKeys.has(downloadKey)}
                                            className="min-h-10 w-full"
                                            onClick={() => triggerDownload(audioUrl, downloadKey)}
                                        />
                                    )}
                                </div>
                            </div>
                        );
                    })}

                    {isMobile && (remainingCount > 0 || canCollapseMobile) && (
                        <div className="rounded-xl border border-border/70 p-2">
                            {remainingCount > 0 ? (
                                <Button
                                    type="button"
                                    variant="outline"
                                    className="min-h-10 w-full text-sm"
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
                                    className="min-h-10 w-full text-sm"
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
