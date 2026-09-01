'use client';

import type { ReactNode, RefObject } from 'react';
import dynamic from 'next/dynamic';
import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import type { UnifiedParseResult } from '@/lib/types';
import { ResultCard } from '@/components/downloader/ResultCard';
import type { RecentParseRecord } from './download-history';

const DownloadHistory = dynamic(
    () => import('./download-history').then((m) => m.DownloadHistory),
    { ssr: false }
);

interface UnifiedDownloaderLowerSectionsProps {
    parseResult: UnifiedParseResult['data'] | null;
    onCloseParseResult: () => void;
    onOpenExtractAudio: (task: AudioExtractTask) => void;
    onRequestPreview: (request: MediaPreviewRequest) => void;
    onClearPreview: () => void;
    activePreview?: MediaPreviewRequest | null;
    mobileAd?: ReactNode;
    mobileGuides?: ReactNode;
    downloadHistory: RecentParseRecord[];
    clearHistory: () => void;
    onRedownload: (url: string) => void;
    historyRef: RefObject<HTMLDivElement | null>;
    historyHydrated: boolean;
}

export function UnifiedDownloaderLowerSections({
    parseResult,
    onCloseParseResult,
    onOpenExtractAudio,
    onRequestPreview,
    onClearPreview,
    activePreview,
    mobileAd,
    mobileGuides,
    downloadHistory,
    clearHistory,
    onRedownload,
    historyRef,
    historyHydrated,
}: UnifiedDownloaderLowerSectionsProps) {
    // These records are created when parsing succeeds. Keep the prop/storage
    // shape stable for compatibility, but never treat them as proof that a file
    // was downloaded; Local Engine download archive owns that responsibility.
    const hasRecentParses = downloadHistory.length > 0;

    return (
        <div className="space-y-3">
            {parseResult && (
                <section aria-live="polite">
                    <ResultCard
                        result={parseResult}
                        onClose={onCloseParseResult}
                        onOpenExtractAudio={onOpenExtractAudio}
                        onRequestPreview={onRequestPreview}
                        onClearPreview={onClearPreview}
                        activePreview={activePreview}
                    />
                </section>
            )}

            {mobileAd && (
                <div className="lg:hidden min-h-[250px] overflow-hidden rounded-lg">
                    {mobileAd}
                </div>
            )}

            <section ref={historyRef} className="scroll-mt-20">
                {hasRecentParses ? (
                    <DownloadHistory
                        downloadHistory={downloadHistory}
                        clearHistory={clearHistory}
                        onRedownload={onRedownload}
                    />
                ) : !historyHydrated ? (
                    <div className="min-h-[48px]" aria-hidden />
                ) : null}
            </section>

            {mobileGuides && <div className="flex flex-col gap-3 lg:hidden">{mobileGuides}</div>}
        </div>
    );
}
