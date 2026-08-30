import { useState } from 'react';

import type { AudioExtractTask } from '@/components/audio-tool/types';
import { DeferredHlsDownloadDialog } from '@/components/deferred-hls-download-dialog';
import type { HlsDownloadDialogRequest } from '@/components/hls-download-dialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { HlsVideoPlayer } from '@/components/hls-video-player';
import { useDictionary } from '@/i18n/client';
import { toast } from '@/lib/deferred-toast';
import { isHlsPlaylistUrl } from '@/lib/hls-playback';
import type { UnifiedParseResult } from '@/lib/types';

import { EmbeddedVideoList } from './EmbeddedVideoList';
import { ImageNoteGrid } from './ImageNoteGrid';
import {
    buildEmbeddedVideoPreview,
    buildMediaPreviewUrl,
    buildPagePreview,
    buildPrimaryResultPreview,
    buildResultPreviewForSelection,
    type MediaPreviewRequest,
} from './media-preview';
import { MultiPartList } from './MultiPartList';
import { ResultCardHeader } from './ResultCardHeader';
import { replaceTemplate, resolveCoverSrc } from './result-card-utils';
import { resolveResultDisplayImages } from './result-card-visibility';
import { SinglePartButtons } from './SinglePartButtons';

type ResultData = NonNullable<UnifiedParseResult['data']>;
type ActiveCollectionSource = 'result' | 'pages' | 'season';

function resolveSelectedPage(result: ResultData, selectedPage?: number) {
    if (!result.pages?.length) return undefined;
    return (
        result.pages.find((page) => page.page === selectedPage) ??
        result.pages.find((page) => page.page === result.currentPage) ??
        result.pages[0]
    );
}

function resolveSelectedVideo(result: ResultData, selectedItemId?: string) {
    if (!result.videos?.length) return undefined;
    return (
        result.videos.find((video) => video.id === selectedItemId) ??
        result.videos.find((video) => video.id === result.currentItemId) ??
        result.videos[0]
    );
}

function buildPageScopedResult(result: ResultData, page: NonNullable<ResultData['pages']>[number]): ResultData {
    return {
        ...result,
        title: page.part || result.title,
        duration: page.duration ?? result.duration,
        downloadVideoUrl: page.downloadVideoUrl ?? null,
        downloadAudioUrl: page.downloadAudioUrl ?? null,
        originDownloadVideoUrl: page.downloadVideoUrl ?? result.originDownloadVideoUrl ?? null,
        originDownloadAudioUrl: page.downloadAudioUrl ?? result.originDownloadAudioUrl ?? null,
        videoAudioMode: page.videoAudioMode,
        mediaActions: undefined,
        currentPage: page.page,
    };
}

function buildVideoScopedResult(result: ResultData, video: NonNullable<ResultData['videos']>[number]): ResultData {
    return {
        ...result,
        title: video.title || result.title,
        cover: video.cover ?? result.cover,
        duration: video.duration ?? result.duration,
        downloadVideoUrl: video.downloadVideoUrl ?? video.originDownloadVideoUrl ?? null,
        downloadAudioUrl: video.downloadAudioUrl ?? video.originDownloadAudioUrl ?? null,
        originDownloadVideoUrl: video.originDownloadVideoUrl ?? video.downloadVideoUrl ?? null,
        originDownloadAudioUrl: video.originDownloadAudioUrl ?? video.downloadAudioUrl ?? null,
        videoAudioMode: video.videoAudioMode,
        mediaActions: video.mediaActions,
        currentItemId: video.id,
    };
}

function buildSelectedPreview(
    sourceUrl: string,
    result: ResultData,
    source: ActiveCollectionSource,
    page: NonNullable<ResultData['pages']>[number] | undefined,
    video: NonNullable<ResultData['videos']>[number] | undefined,
    options: { autoplay?: boolean; preferAudio?: boolean } = {}
) {
    if (source === 'pages' && page) return buildPagePreview(sourceUrl, page, options);
    if (source === 'season' && video) return buildEmbeddedVideoPreview(sourceUrl, video, options);
    return buildPrimaryResultPreview(result, options);
}

interface VideoResultPanelProps {
    result: ResultData;
    onClose: () => void;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
    onClearPreview: () => void;
    activePreview?: MediaPreviewRequest | null;
}

export function VideoResultPanel({
    result,
    onClose,
    onOpenExtractAudio,
    onRequestPreview,
    onClearPreview,
    activePreview,
}: VideoResultPanelProps) {
    const dict = useDictionary();
    const hasMultiplePages = Boolean(result.isMultiPart && result.pages && result.pages.length > 1);
    const activeListKey = `${result.platform}-${result.url ?? ''}-${result.pages?.length ?? 0}-${result.videos?.length ?? 0}`;
    const defaultBiliList = hasMultiplePages ? 'pages' : 'season';
    const [activeBiliListState, setActiveBiliListState] = useState<{ key: string; value: 'pages' | 'season' }>({
        key: activeListKey,
        value: defaultBiliList,
    });
    const [selectionState, setSelectionState] = useState<{
        key: string;
        currentPage?: number;
        currentItemId?: string;
    }>({
        key: activeListKey,
        currentPage: result.currentPage,
        currentItemId: result.currentItemId,
    });
    const [hlsDownloadRequest, setHlsDownloadRequest] = useState<HlsDownloadDialogRequest | null>(null);

    const activeBiliList = activeBiliListState.key === activeListKey ? activeBiliListState.value : defaultBiliList;
    const setActiveBiliList = (value: 'pages' | 'season') => {
        setActiveBiliListState({ key: activeListKey, value });
    };

    const displayImages = resolveResultDisplayImages({
        noteType: result.noteType,
        images: result.images,
        coverUrl: result.cover,
    });
    const isMultiPart = hasMultiplePages;
    const isImageNote = result.noteType === 'image' && displayImages.length > 0;
    const hasEmbeddedVideos = !!result.videos?.length;
    const hasSeasonAlternative = (result.videos?.length || 0) > 1;
    const hasBilibiliSourceSwitch =
        (result.platform === 'bili' || result.platform === 'bilibili') &&
        Boolean(isMultiPart) &&
        hasSeasonAlternative;
    const pageTabLabel = replaceTemplate(dict.result.totalParts, '{count}', String(result.pages?.length || 0));
    const seasonTabLabel = replaceTemplate(dict.result.videoCount, '{count}', String(result.videos?.length || 0));
    const showMultiPartList = Boolean(isMultiPart) && (!hasBilibiliSourceSwitch || activeBiliList === 'pages');
    const showSeasonList = hasEmbeddedVideos && (!isMultiPart || (hasBilibiliSourceSwitch && activeBiliList === 'season'));
    const hasSupplementalImages = !isImageNote && displayImages.length > 0;
    const coverUrl = typeof result.cover === 'string' ? result.cover.trim() : '';
    const shareSourceUrl = typeof result.url === 'string' ? result.url.trim() : '';
    const selectedPageNumber = selectionState.key === activeListKey ? selectionState.currentPage : result.currentPage;
    const selectedItemId = selectionState.key === activeListKey ? selectionState.currentItemId : result.currentItemId;
    const currentPage = resolveSelectedPage(result, selectedPageNumber);
    const currentVideo = resolveSelectedVideo(result, selectedItemId);
    const activeCollectionSource: ActiveCollectionSource = showSeasonList
        ? 'season'
        : showMultiPartList
            ? 'pages'
            : hasEmbeddedVideos
                ? 'season'
                : isMultiPart
                    ? 'pages'
                    : 'result';
    const previewItem =
        activeCollectionSource === 'pages'
            ? currentPage
                ? String(currentPage.page)
                : undefined
            : activeCollectionSource === 'season'
                ? currentVideo?.id
                : undefined;
    const effectiveResult =
        activeCollectionSource === 'pages' && currentPage
            ? buildPageScopedResult(result, currentPage)
            : activeCollectionSource === 'season' && currentVideo
                ? buildVideoScopedResult(result, currentVideo)
                : result;
    const activePreviewMatchesSelection = Boolean(
        activePreview
        && activePreview.sourceUrl === shareSourceUrl
        && activePreview.item === previewItem
    );
    const previewPreference = activePreviewMatchesSelection && activePreview?.mediaType === 'audio';
    const primaryPreview = buildSelectedPreview(
        shareSourceUrl,
        effectiveResult,
        activeCollectionSource,
        currentPage,
        currentVideo,
        { autoplay: false, preferAudio: previewPreference }
    );
    const canSharePlayLink = shareSourceUrl.length > 0 && Boolean(primaryPreview);
    const selectedCoverUrl =
        activeCollectionSource === 'season' && currentVideo?.cover ? currentVideo.cover.trim() : coverUrl;
    const coverSrc = selectedCoverUrl.length > 0 ? resolveCoverSrc(selectedCoverUrl) : '';
    const isActivePreviewForSelection = Boolean(
        activePreview
        && primaryPreview
        && activePreview.mediaType === primaryPreview.mediaType
        && activePreview.sourceUrl === primaryPreview.sourceUrl
        && activePreview.item === primaryPreview.item
    );
    const playerPreview = isActivePreviewForSelection && primaryPreview
        ? {
              ...primaryPreview,
              autoplay: activePreview?.autoplay ?? primaryPreview.autoplay,
              origin: activePreview?.origin ?? primaryPreview.origin,
          }
        : null;
    const hlsPlaybackUrl =
        playerPreview?.mediaType === 'video'
        && (
            effectiveResult.mediaActions?.video === 'browser-hls-download'
            || isHlsPlaylistUrl(effectiveResult.originDownloadVideoUrl)
        )
            ? effectiveResult.downloadVideoUrl
            : null;
    const playerUrl = hlsPlaybackUrl || (playerPreview ? buildMediaPreviewUrl(playerPreview) : null);
    const handleSelectPage = (pageNumber: number, mediaType: 'video' | 'audio') => {
        const page = result.pages?.find((item) => item.page === pageNumber);
        if (!page) return;
        setSelectionState((previous) => ({
            key: activeListKey,
            currentPage: pageNumber,
            currentItemId: previous.key === activeListKey ? previous.currentItemId : result.currentItemId,
        }));
        const preview = buildResultPreviewForSelection(result, {
            item: String(pageNumber),
            mediaType,
            autoplay: true,
        });
        if (preview) {
            onRequestPreview({ ...preview, origin: 'user' });
            return;
        }
        onClearPreview();
    };

    const handleSelectVideo = (itemId: string, mediaType: 'video' | 'audio') => {
        const video = result.videos?.find((item) => item.id === itemId);
        if (!video) return;
        setSelectionState((previous) => ({
            key: activeListKey,
            currentPage: previous.key === activeListKey ? previous.currentPage : result.currentPage,
            currentItemId: itemId,
        }));
        const preview = buildResultPreviewForSelection(result, {
            item: itemId,
            mediaType,
            autoplay: true,
        });
        if (preview) {
            onRequestPreview({ ...preview, origin: 'user' });
            return;
        }
        onClearPreview();
    };

    const handleCopySharePlayLink = async () => {
        if (!canSharePlayLink) return;
        try {
            if (typeof window === 'undefined' || !navigator.clipboard?.writeText) {
                throw new Error('Clipboard API unavailable');
            }
            const pathnameSegments = window.location.pathname.split('/').filter((s) => s.length > 0);
            const localePrefix = pathnameSegments[0] ? `/${pathnameSegments[0]}` : '';
            const shareUrl = new URL(`${window.location.origin}${localePrefix}/play`);
            shareUrl.searchParams.set('play', shareSourceUrl);
            shareUrl.searchParams.set('autoplay', '1');
            shareUrl.searchParams.set('type', primaryPreview!.mediaType);
            if (primaryPreview!.item) {
                shareUrl.searchParams.set('item', primaryPreview!.item);
            }
            await navigator.clipboard.writeText(shareUrl.toString());
            toast.success(dict.result.sharePlayLinkCopied);
        } catch (error) {
            console.error('Failed to copy share-play link:', error);
            toast.error(dict.errors.clipboardFailed, { description: dict.errors.clipboardPermission });
        }
    };

    const displayTitle =
        effectiveResult.title && effectiveResult.title !== result.title
            ? `${result.title} · ${effectiveResult.title}`
            : effectiveResult.title || result.title;
    const displayDuration = effectiveResult.duration ?? result.duration;

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
                    {playerPreview && playerUrl ? (
                        <div className="overflow-hidden rounded-xl bg-black shadow-sm ring-1 ring-border/60">
                            {playerPreview.mediaType === 'audio' ? (
                                <audio
                                    key={playerUrl}
                                    src={playerUrl}
                                    controls
                                    autoPlay={playerPreview.autoplay}
                                    preload="metadata"
                                    className="w-full"
                                />
                            ) : hlsPlaybackUrl ? (
                                <HlsVideoPlayer
                                    key={playerUrl}
                                    src={playerUrl}
                                    autoPlay={playerPreview.autoplay}
                                    muted={playerPreview.origin === 'share' && playerPreview.autoplay}
                                    playsInline
                                    preload="metadata"
                                    poster={coverSrc || undefined}
                                    className="min-h-[220px] max-h-[56vh] w-full bg-black sm:min-h-[240px]"
                                />
                            ) : (
                                <video
                                    key={playerUrl}
                                    src={playerUrl}
                                    controls
                                    autoPlay={playerPreview.autoplay}
                                    muted={playerPreview.origin === 'share' && playerPreview.autoplay}
                                    playsInline
                                    preload="metadata"
                                    poster={coverSrc || undefined}
                                    className="min-h-[220px] max-h-[56vh] w-full bg-black sm:min-h-[240px]"
                                />
                            )}
                        </div>
                    ) : !isImageNote && coverSrc ? (
                        <ImageNoteGrid images={[coverSrc]} title={displayTitle} singleImageMode />
                    ) : null}
                    {isImageNote ? (
                        <ImageNoteGrid images={displayImages} title={displayTitle} />
                    ) : (
                        <>
                            <SinglePartButtons
                                result={effectiveResult}
                                previewItem={previewItem}
                                onOpenExtractAudio={onOpenExtractAudio}
                                onOpenHlsDownload={setHlsDownloadRequest}
                                onRequestPreview={onRequestPreview}
                            />
                            {(showMultiPartList || showSeasonList || hasBilibiliSourceSwitch) && (
                                <div className="space-y-3 rounded-xl bg-muted/15 p-3 ring-1 ring-border/70 sm:p-4">
                                    {hasBilibiliSourceSwitch && (
                                        <div className="grid grid-cols-2 gap-2 sm:flex sm:items-center" role="group">
                                            <Button
                                                variant={activeBiliList === 'pages' ? 'default' : 'outline'}
                                                size="sm"
                                                className="min-h-10 text-xs"
                                                aria-pressed={activeBiliList === 'pages'}
                                                onClick={() => setActiveBiliList('pages')}
                                            >
                                                {pageTabLabel}
                                            </Button>
                                            <Button
                                                variant={activeBiliList === 'season' ? 'default' : 'outline'}
                                                size="sm"
                                                className="min-h-10 text-xs"
                                                aria-pressed={activeBiliList === 'season'}
                                                onClick={() => setActiveBiliList('season')}
                                            >
                                                {seasonTabLabel}
                                            </Button>
                                        </div>
                                    )}
                                    {showMultiPartList ? (
                                        <MultiPartList
                                            key={`pages-${result.url ?? ''}-${result.pages?.length ?? 0}`}
                                            pages={result.pages!}
                                            currentPage={currentPage?.page}
                                            onSelectPage={handleSelectPage}
                                        />
                                    ) : showSeasonList ? (
                                        <EmbeddedVideoList
                                            key={`videos-${result.url ?? ''}-${result.videos?.length ?? 0}`}
                                            videos={result.videos!}
                                            currentItemId={currentVideo?.id}
                                            autoScrollKey={activeListKey}
                                            autoScrollItemId={result.currentItemId}
                                            onSelectItem={handleSelectVideo}
                                        />
                                    ) : null}
                                </div>
                            )}
                            {hasSupplementalImages && (
                                <ImageNoteGrid images={displayImages} title={displayTitle} />
                            )}
                        </>
                    )}
                </div>
                <DeferredHlsDownloadDialog
                    open={Boolean(hlsDownloadRequest)}
                    onOpenChange={(open) => {
                        if (!open) setHlsDownloadRequest(null);
                    }}
                    request={hlsDownloadRequest}
                />
            </CardContent>
        </Card>
    );
}
