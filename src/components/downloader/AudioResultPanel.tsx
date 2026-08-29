import type { AudioExtractTask } from '@/components/audio-tool/types';
import { Card, CardContent } from '@/components/ui/card';
import { useDictionary } from '@/i18n/client';
import { toast } from '@/lib/deferred-toast';
import type { UnifiedParseResult } from '@/lib/types';

import { ImageNoteGrid } from './ImageNoteGrid';
import {
    buildMediaPreviewUrl,
    buildPrimaryResultPreview,
    canSharePlayResult,
    type MediaPreviewRequest,
} from './media-preview';
import { ResultCardHeader } from './ResultCardHeader';
import { resolveCoverSrc } from './result-card-utils';
import { SinglePartButtons } from './SinglePartButtons';

type ResultData = NonNullable<UnifiedParseResult['data']>;

interface AudioResultPanelProps {
    result: ResultData;
    onClose: () => void;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
    activePreview?: MediaPreviewRequest | null;
}

export function AudioResultPanel({
    result,
    onClose,
    onOpenExtractAudio,
    onRequestPreview,
    activePreview,
}: AudioResultPanelProps) {
    const dict = useDictionary();
    const shareSourceUrl = typeof result.url === 'string' ? result.url.trim() : '';
    const canSharePlayLink = shareSourceUrl.length > 0 && canSharePlayResult(result);
    const primaryPreview = buildPrimaryResultPreview(result, { autoplay: false, preferAudio: true });
    const isActivePreviewForResult = Boolean(
        activePreview
        && primaryPreview
        && activePreview.mediaType === primaryPreview.mediaType
        && activePreview.sourceUrl === primaryPreview.sourceUrl
        && activePreview.item === primaryPreview.item
    );
    const playerPreview = isActivePreviewForResult && primaryPreview
        ? {
              ...primaryPreview,
              autoplay: activePreview?.autoplay ?? primaryPreview.autoplay,
              origin: activePreview?.origin ?? primaryPreview.origin,
          }
        : null;
    const playerUrl = playerPreview ? buildMediaPreviewUrl(playerPreview) : null;
    const coverUrl = typeof result.cover === 'string' ? result.cover.trim() : '';
    const coverSrc = coverUrl ? resolveCoverSrc(coverUrl) : '';

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
            await navigator.clipboard.writeText(shareUrl.toString());
            toast.success(dict.result.sharePlayLinkCopied);
        } catch (error) {
            console.error('Failed to copy share-play link:', error);
            toast.error(dict.errors.clipboardFailed, { description: dict.errors.clipboardPermission });
        }
    };

    return (
        <Card className="overflow-hidden">
            <ResultCardHeader
                title={result.title}
                duration={result.duration}
                canSharePlayLink={canSharePlayLink}
                onCopyShareLink={() => void handleCopySharePlayLink()}
                onClose={onClose}
            />
            <CardContent className="p-4 sm:p-5">
                <div className="space-y-4">
                    {playerPreview && playerUrl ? (
                        <div className="overflow-hidden rounded-xl bg-black ring-1 ring-border/70">
                            <audio
                                key={playerUrl}
                                src={playerUrl}
                                controls
                                autoPlay={playerPreview.autoplay}
                                preload="metadata"
                                className="w-full"
                            />
                        </div>
                    ) : coverSrc ? (
                        <ImageNoteGrid images={[coverSrc]} title={result.title} singleImageMode />
                    ) : null}
                    <SinglePartButtons
                        result={result}
                        onOpenExtractAudio={onOpenExtractAudio}
                        onOpenHlsDownload={() => {}}
                        onRequestPreview={onRequestPreview}
                    />
                </div>
            </CardContent>
        </Card>
    );
}
