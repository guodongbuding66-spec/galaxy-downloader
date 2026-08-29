import { useState } from 'react';

import type { AudioExtractTask } from '@/components/audio-tool/types';
import { Card, CardContent } from '@/components/ui/card';
import { useDictionary } from '@/i18n/client';
import { toast } from '@/lib/deferred-toast';
import type { UnifiedParseResult } from '@/lib/types';

import { ImageNoteGrid } from './ImageNoteGrid';
import {
    buildMediaPreviewUrl,
    canPreviewEpisodeAudio,
    type MediaPreviewRequest,
} from './media-preview';
import { PodcastEpisodeList } from './PodcastEpisodeList';
import { ResultCardHeader } from './ResultCardHeader';
import { resolveCoverSrc } from './result-card-utils';
import { SinglePartButtons } from './SinglePartButtons';

type ResultData = NonNullable<UnifiedParseResult['data']>;

interface PodcastPickerPanelProps {
    result: ResultData;
    onClose: () => void;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
    onClearPreview: () => void;
    activePreview?: MediaPreviewRequest | null;
}

export function PodcastPickerPanel({
    result,
    onClose,
    onOpenExtractAudio,
    onRequestPreview,
    onClearPreview,
    activePreview,
}: PodcastPickerPanelProps) {
    const dict = useDictionary();
    const episodes = result.episodes ?? [];
    const initialEpisodeId = result.currentEpisodeId ?? result.currentItemId ?? episodes[0]?.id ?? '';
    const [selectedEpisodeId, setSelectedEpisodeId] = useState(initialEpisodeId);

    const selectedEpisode = episodes.find((e) => e.id === selectedEpisodeId) ?? episodes[0];
    const audioUrl = selectedEpisode
        ? (selectedEpisode.downloadAudioUrl || selectedEpisode.originDownloadAudioUrl || null)
        : null;

    const episodeAsResult: ResultData = selectedEpisode
        ? {
              ...result,
              title: selectedEpisode.title,
              cover: selectedEpisode.cover ?? result.cover,
              duration: selectedEpisode.duration,
              downloadAudioUrl: selectedEpisode.downloadAudioUrl ?? null,
              downloadVideoUrl: null,
              originDownloadVideoUrl: null,
              originDownloadAudioUrl: selectedEpisode.originDownloadAudioUrl ?? null,
              mediaActions: { video: 'hide', audio: audioUrl ? 'direct-download' : 'hide' },
          }
        : result;

    const shareSourceUrl = typeof result.url === 'string' ? result.url.trim() : '';
    const canSharePlayLink =
        shareSourceUrl.length > 0 && Boolean(selectedEpisode) && canPreviewEpisodeAudio(selectedEpisode!);

    const playerPreview: MediaPreviewRequest | null =
        shareSourceUrl && selectedEpisode && canPreviewEpisodeAudio(selectedEpisode)
            ? {
                  mediaType: 'audio',
                  sourceUrl: shareSourceUrl,
                  title: selectedEpisode.title,
                  item: selectedEpisode.id,
                  autoplay: false,
              }
            : null;

    const effectivePreview =
        playerPreview && activePreview?.mediaType === 'audio' &&
        activePreview?.sourceUrl === shareSourceUrl &&
        activePreview?.item === selectedEpisode?.id
            ? activePreview
            : playerPreview;

    const activePlayerUrl = effectivePreview ? buildMediaPreviewUrl(effectivePreview) : null;
    const autoPlayActive = effectivePreview === activePreview && (activePreview?.autoplay ?? false);

    const coverUrl = selectedEpisode?.cover ?? result.cover ?? '';
    const coverSrc = typeof coverUrl === 'string' && coverUrl.trim() ? resolveCoverSrc(coverUrl.trim()) : '';

    const handleSelectEpisode = (episodeId: string) => {
        setSelectedEpisodeId(episodeId);
        onClearPreview();
    };

    const handleCopySharePlayLink = async () => {
        if (!canSharePlayLink || !selectedEpisode) return;
        try {
            if (typeof window === 'undefined' || !navigator.clipboard?.writeText) {
                throw new Error('Clipboard API unavailable');
            }
            const pathnameSegments = window.location.pathname.split('/').filter((s) => s.length > 0);
            const localePrefix = pathnameSegments[0] ? `/${pathnameSegments[0]}` : '';
            const shareUrl = new URL(`${window.location.origin}${localePrefix}/play`);
            shareUrl.searchParams.set('play', shareSourceUrl);
            shareUrl.searchParams.set('autoplay', '1');
            shareUrl.searchParams.set('item', selectedEpisode.id);
            await navigator.clipboard.writeText(shareUrl.toString());
            toast.success(dict.result.sharePlayLinkCopied);
        } catch (error) {
            console.error('Failed to copy share-play link:', error);
            toast.error(dict.errors.clipboardFailed, { description: dict.errors.clipboardPermission });
        }
    };

    const displayTitle = selectedEpisode
        ? `${result.title} · ${selectedEpisode.title}`
        : result.title;
    const displayDuration = selectedEpisode?.duration ?? result.duration;

    return (
        <Card className="overflow-hidden">
            <ResultCardHeader
                title={displayTitle}
                duration={displayDuration}
                canSharePlayLink={canSharePlayLink}
                onCopyShareLink={() => void handleCopySharePlayLink()}
                onClose={onClose}
            />
            <CardContent className="p-4 sm:p-5">
                <div className="space-y-4">
                    {activePlayerUrl && effectivePreview ? (
                        <div className="overflow-hidden rounded-xl bg-black ring-1 ring-border/70">
                            <audio
                                key={activePlayerUrl}
                                src={activePlayerUrl}
                                controls
                                autoPlay={autoPlayActive}
                                preload="metadata"
                                className="w-full"
                            />
                        </div>
                    ) : coverSrc ? (
                        <ImageNoteGrid images={[coverSrc]} title={displayTitle} singleImageMode />
                    ) : null}

                    <SinglePartButtons
                        result={episodeAsResult}
                        previewItem={selectedEpisode?.id}
                        onOpenExtractAudio={onOpenExtractAudio}
                        onOpenHlsDownload={() => {}}
                        onRequestPreview={onRequestPreview}
                    />

                    {episodes.length > 0 && (
                        <div className="border-t pt-4">
                            <PodcastEpisodeList
                                key={`episodes-${result.url ?? ''}-${initialEpisodeId}`}
                                episodes={episodes}
                                currentEpisodeId={selectedEpisodeId}
                                autoScrollKey={`${result.url ?? ''}-${initialEpisodeId}`}
                                autoScrollEpisodeId={initialEpisodeId}
                                onSelectEpisode={handleSelectEpisode}
                            />
                        </div>
                    )}
                </div>
            </CardContent>
        </Card>
    );
}
