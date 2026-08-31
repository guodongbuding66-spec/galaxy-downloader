'use client';

import { startTransition, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useSearchParams } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';

import { toast } from '@/lib/deferred-toast';
import { DeferredAudioExtractDialog } from '@/components/deferred-audio-extract-dialog';
import { useTopBarActions } from '@/components/layout/top-bar-actions';
import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import { buildResultPreviewForSelection } from '@/components/downloader/media-preview';
import {
    ArrowUp,
    ChevronDown,
    ClipboardPaste,
    Loader2,
    PackageCheck,
} from 'lucide-react';

import type { DownloadRecord } from './download-history';
import { useLocalStorageState } from '@/hooks/use-local-storage-state';
import { useInstallPrompt } from '@/hooks/use-install-prompt';
import type { UnifiedParseResult } from '@/lib/types';
import { Platform } from '@/lib/types';
import { DOWNLOAD_HISTORY_MAX_COUNT, DOWNLOAD_HISTORY_STORAGE_KEY } from '@/lib/constants';
import { useDictionary } from '@/i18n/client';
import { isApiRequestError, resolveApiErrorMessage } from '@/lib/api-errors';
import { getPlatformLabel, normalizePlatform } from '@/lib/platforms';
import { UnifiedParseReloadError, requestUnifiedParse } from '@/lib/unified-parse';

const UnifiedDownloaderLowerSections = dynamic(
    () => import('./unified-downloader-lower-sections').then((m) => m.UnifiedDownloaderLowerSections),
    { ssr: false }
);

interface UnifiedDownloaderProps {
    leftRail?: ReactNode;
    rightRail?: ReactNode;
    mobileAd?: ReactNode;
    mobileGuides?: ReactNode;
    heroMeta?: ReactNode;
    footer?: ReactNode;
}

interface ActivePreview extends MediaPreviewRequest {
    origin: 'share' | 'result' | 'user';
}

type WorkbenchCopy = {
    inputLabel: string;
    helperTitle: string;
    helperDescription: string;
};

const WORKBENCH_COPY: Record<string, WorkbenchCopy> = {
    zh: {
        inputLabel: '媒体链接或分享文本',
        helperTitle: '工具与平台说明',
        helperDescription: '历史记录、平台说明和辅助工具按需展开。',
    },
    'zh-tw': {
        inputLabel: '媒體連結或分享文字',
        helperTitle: '工具與平台說明',
        helperDescription: '歷史記錄、平台說明與輔助工具按需展開。',
    },
    en: {
        inputLabel: 'Media URL or shared text',
        helperTitle: 'Tools and platform notes',
        helperDescription: 'History, platform notes and secondary tools stay collapsed until needed.',
    },
    ja: {
        inputLabel: 'メディアURLまたは共有テキスト',
        helperTitle: 'ツールとプラットフォーム情報',
        helperDescription: '履歴や補助ツールは必要なときだけ展開できます。',
    },
    es: {
        inputLabel: 'URL del medio o texto compartido',
        helperTitle: 'Herramientas y notas de plataformas',
        helperDescription: 'El historial y las herramientas secundarias permanecen plegados hasta que los necesites.',
    },
    ru: {
        inputLabel: 'Ссылка на медиа или текст публикации',
        helperTitle: 'Инструменты и сведения о платформах',
        helperDescription: 'История и вспомогательные инструменты раскрываются только при необходимости.',
    },
};

function resolveWorkbenchCopy(pathname: string | null): WorkbenchCopy {
    const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
    return WORKBENCH_COPY[locale] || WORKBENCH_COPY.en;
}

export function UnifiedDownloader({
    leftRail,
    rightRail,
    mobileAd,
    heroMeta,
    footer,
}: UnifiedDownloaderProps) {
    const dict = useDictionary();
    const { setActions: setTopBarActions } = useTopBarActions();
    const pathname = usePathname();
    const workbenchCopy = resolveWorkbenchCopy(pathname);
    const searchParams = useSearchParams();
    const [url, setUrl] = useState('');
    const [loading, setLoading] = useState(false);
    const [isCoolingDown, setIsCoolingDown] = useState(false);
    const [error, setError] = useState('');
    const lastParseTimeRef = useRef<number>(0);
    const [audioToolMounted, setAudioToolMounted] = useState(false);
    const [audioToolOpen, setAudioToolOpen] = useState(false);
    const [audioToolEntry, setAudioToolEntry] = useState<'toolbar' | 'result'>('toolbar');
    const [audioToolTask, setAudioToolTask] = useState<AudioExtractTask | null>(null);
    const [parseResult, setParseResult] = useState<UnifiedParseResult['data'] | null>(null);
    const [activePreview, setActivePreview] = useState<ActivePreview | null>(null);
    const [showBackToTop, setShowBackToTop] = useState(false);
    const historyRef = useRef<HTMLDivElement>(null);
    const urlInputRef = useRef<HTMLTextAreaElement>(null);
    const handledShareTaskRef = useRef<string | null>(null);

    const [downloadHistory, setDownloadHistory, historyHydrated] = useLocalStorageState<DownloadRecord[]>(DOWNLOAD_HISTORY_STORAGE_KEY, {
        defaultValue: []
    });
    const { canPrompt, promptInstall, dismiss } = useInstallPrompt();
    const hasPromptedInstall = useRef(false);
    const addToHistory = useCallback((record: DownloadRecord) => {
        const normalizedUrl = record.url.trim();
        setDownloadHistory(prev => [
            record,
            ...(prev || []).filter((item) => item.url.trim() !== normalizedUrl)
        ].slice(0, DOWNLOAD_HISTORY_MAX_COUNT));
    }, [setDownloadHistory]);

    const clearDownloadHistory = () => {
        setDownloadHistory([]);
    };

    const openToolbarAudioTool = useCallback(() => {
        setAudioToolMounted(true);
        setAudioToolEntry('toolbar');
        setAudioToolTask(null);
        setAudioToolOpen(true);
    }, []);

    const openResultAudioExtract = (task: AudioExtractTask) => {
        setAudioToolMounted(true);
        setAudioToolEntry('result');
        setAudioToolTask(task);
        setAudioToolOpen(true);
    };

    const handleUnifiedParse = useCallback(async (videoUrl: string) => {
        void import('./unified-downloader-lower-sections');

        const apiResult = await requestUnifiedParse(videoUrl);
        const normalizedData = {
            ...apiResult.data,
            platform: normalizePlatform(apiResult.data.platform),
        };
        const platformCode = normalizedData.platform;
        const platformLabel = getPlatformLabel(platformCode, dict);
        const displayTitle = normalizedData.title || normalizedData.desc || dict.history.unknownTitle;
        const nextRecord: DownloadRecord = {
            url: normalizedData.url || videoUrl,
            title: displayTitle,
            timestamp: Date.now(),
            platform: platformCode as Platform
        };

        startTransition(() => {
            setParseResult(normalizedData);
            addToHistory(nextRecord);
        });

        toast.success(dict.toast.douyinParseSuccess, {
            description: `${platformLabel}: ${displayTitle}`,
        });

        if (canPrompt && !hasPromptedInstall.current) {
            hasPromptedInstall.current = true;
            toast(dict.toast.installTitle, {
                description: dict.toast.installDescription,
                duration: 10000,
                action: {
                    label: dict.toast.installAction,
                    onClick: promptInstall,
                },
                onDismiss: dismiss,
            });
        }
        return normalizedData;
    }, [addToHistory, canPrompt, dict, dismiss, promptInstall]);

    const closeParseResult = () => {
        setParseResult(null);
        setActivePreview(null);
    };

    const openResultPreview = useCallback((request: MediaPreviewRequest) => {
        setActivePreview({
            ...request,
            autoplay: request.autoplay ?? false,
            origin: request.origin ?? 'result',
        });
    }, [setActivePreview]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!url.trim()) {
            setError(dict.errors.emptyUrl);
            return;
        }

        const now = Date.now();
        if (now - lastParseTimeRef.current < 3000) {
            return;
        }
        lastParseTimeRef.current = now;
        setIsCoolingDown(true);
        setTimeout(() => setIsCoolingDown(false), 3000);

        setLoading(true);
        setError('');
        setParseResult(null);
        setActivePreview(null);

        try {
            await handleUnifiedParse(url.trim());
            setUrl('');
        } catch (err) {
            if (err instanceof UnifiedParseReloadError) {
                setLoading(false);
                return;
            }

            if (isApiRequestError(err)) {
                console.error('Unified parse request failed', {
                    code: err.code,
                    status: err.status,
                    requestId: err.requestId,
                    details: err.details,
                });
            }

            const errorMessage = resolveApiErrorMessage(err, dict);
            setError(errorMessage);
            toast.error(dict.errors.downloadFailed, {
                description: errorMessage
            });
        }

        setLoading(false);
    };

    const handleRedownload = (url: string) => {
        setUrl(url);
        setParseResult(null);
        setActivePreview(null);
        toast(dict.toast.linkFilledForRedownload, {
            description: dict.toast.clickToRedownloadDesc,
        });
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const sharedPlaySourceUrl = searchParams.get('play')?.trim() ?? '';
    const sharedAutoplayRequested = searchParams.get('autoplay') === '1';
    const sharedPlayItem = searchParams.get('item')?.trim() || undefined;
    const sharedPlayType = searchParams.get('type') === 'audio'
        ? 'audio'
        : searchParams.get('type') === 'video'
            ? 'video'
            : undefined;
    const hasDownloadHistory = downloadHistory.length > 0;
    const showHistoryShortcut = historyHydrated && hasDownloadHistory;
    const scrollToHistory = useCallback(() => {
        if (historyRef.current) {
            const top = historyRef.current.getBoundingClientRect().top + window.scrollY - 64;
            window.scrollTo({ top, behavior: 'smooth' });
        }
    }, []);

    useEffect(() => {
        setTopBarActions({
            showHistoryShortcut,
            onHistoryClick: scrollToHistory,
            showAudioTool: true,
            onAudioToolClick: openToolbarAudioTool,
        });

        return () => {
            setTopBarActions({});
        };
    }, [
        openToolbarAudioTool,
        scrollToHistory,
        setTopBarActions,
        showHistoryShortcut,
    ]);

    useEffect(() => {
        if (!sharedPlaySourceUrl) {
            return;
        }

        const taskKey = [
            sharedPlaySourceUrl,
            sharedPlayItem ?? '',
            sharedPlayType ?? '',
            sharedAutoplayRequested ? '1' : '0',
        ].join('::');
        if (handledShareTaskRef.current === taskKey) {
            return;
        }
        handledShareTaskRef.current = taskKey;

        let cancelled = false;

        const runSharedPlayback = async () => {
            setLoading(true);
            setError('');
            setParseResult(null);
            setUrl(sharedPlaySourceUrl);
            setActivePreview(null);

            try {
                const parsed = await handleUnifiedParse(sharedPlaySourceUrl);
                if (cancelled) {
                    return;
                }

                const sharePreview = buildResultPreviewForSelection(parsed, {
                    item: sharedPlayItem,
                    mediaType: sharedPlayType,
                    autoplay: sharedAutoplayRequested,
                });

                setActivePreview(sharePreview ? {
                    ...sharePreview,
                    origin: 'share',
                } : null);
            } catch (err) {
                if (cancelled) {
                    return;
                }

                if (err instanceof UnifiedParseReloadError) {
                    return;
                }

                if (isApiRequestError(err)) {
                    console.error('Shared playback parse failed', {
                        code: err.code,
                        status: err.status,
                        requestId: err.requestId,
                        details: err.details,
                    });
                }

                const errorMessage = resolveApiErrorMessage(err, dict);
                setError(errorMessage);
                toast.error(dict.errors.downloadFailed, {
                    description: errorMessage,
                });
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        void runSharedPlayback();

        return () => {
            cancelled = true;
        };
    }, [
        dict,
        handleUnifiedParse,
        sharedAutoplayRequested,
        sharedPlayItem,
        sharedPlaySourceUrl,
        sharedPlayType,
    ]);

    useEffect(() => {
        let idleId: number | null = null;
        let timerId: ReturnType<typeof setTimeout> | null = null;

        const preloadInteractiveChunks = () => {
            void import('./unified-downloader-lower-sections');
        };

        if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
            idleId = window.requestIdleCallback(() => {
                preloadInteractiveChunks();
            }, { timeout: 3000 });
        } else {
            timerId = setTimeout(() => {
                preloadInteractiveChunks();
            }, 1200);
        }

        return () => {
            if (idleId !== null && 'cancelIdleCallback' in window) {
                window.cancelIdleCallback(idleId);
            }
            if (timerId !== null) {
                clearTimeout(timerId);
            }
        };
    }, []);

    useEffect(() => {
        let ticking = false;

        const updateVisibility = () => {
            const shouldShow = window.scrollY > 800;
            setShowBackToTop((prev) => (prev === shouldShow ? prev : shouldShow));
            ticking = false;
        };

        const handleScroll = () => {
            if (ticking) {
                return;
            }
            ticking = true;
            window.requestAnimationFrame(updateVisibility);
        };

        handleScroll();
        window.addEventListener('scroll', handleScroll, { passive: true });

        return () => {
            window.removeEventListener('scroll', handleScroll);
        };
    }, []);

    return (
        <div className="min-h-screen flex flex-col bg-background">
            <DeferredAudioExtractDialog
                mounted={audioToolMounted}
                open={audioToolOpen}
                onOpenChange={(nextOpen) => {
                    setAudioToolOpen(nextOpen);
                    if (!nextOpen) {
                        setAudioToolTask(null);
                        setAudioToolEntry('toolbar');
                    }
                }}
                entry={audioToolEntry}
                autoExtractTask={audioToolTask}
            />

            <main id="main-content" className="flex-1 px-3 py-3 sm:px-4 md:px-5">
                <div className="mx-auto w-full max-w-[1380px] space-y-3">
                    <section className="border-b pb-3 sm:pb-4">
                        <div className="flex min-w-0 flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3">
                            <h1 className="shrink-0 text-lg font-semibold tracking-[-0.02em] sm:text-xl">
                                {dict.unified.pageTitle}
                            </h1>
                            <p className="min-w-0 max-w-3xl text-xs leading-5 text-muted-foreground sm:text-sm">
                                {dict.unified.pageDescription}
                            </p>
                        </div>

                        <form onSubmit={handleSubmit} className="mt-3">
                            <label htmlFor="url" className="sr-only">
                                {workbenchCopy.inputLabel}
                            </label>
                            <div className="grid gap-2 lg:grid-cols-[minmax(0,1fr)_148px]">
                                <div className="relative rounded-lg border bg-card transition-[border-color] duration-150 focus-within:border-foreground/40">
                                    <Textarea
                                        id="url"
                                        ref={urlInputRef}
                                        value={url}
                                        onChange={(e) => setUrl(e.target.value)}
                                        placeholder={dict.unified.placeholder}
                                        required
                                        className="min-h-[52px] resize-none border-0 bg-transparent py-2.5 pe-11 ps-3 text-sm leading-5 shadow-none focus-visible:ring-0"
                                    />
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="icon"
                                        className="absolute end-1.5 top-1.5 h-8 w-8 rounded-md text-muted-foreground hover:text-foreground"
                                        aria-label={dict.form.pasteButton}
                                        title={dict.form.pasteButton}
                                        onClick={async () => {
                                            try {
                                                const text = await navigator.clipboard.readText();
                                                setUrl(text);
                                                toast.success(dict.toast.linkFilled);
                                            } catch (err) {
                                                console.error('Failed to read clipboard:', err);
                                                toast.error(dict.errors.clipboardFailed, {
                                                    description: dict.errors.clipboardPermission,
                                                });
                                            }
                                        }}
                                    >
                                        <ClipboardPaste className="h-4 w-4" aria-hidden="true" />
                                    </Button>
                                </div>
                                <Button
                                    type="submit"
                                    size="lg"
                                    className="h-[52px] gap-2 rounded-lg"
                                    disabled={loading || isCoolingDown || !url.trim()}
                                >
                                    {loading ? (
                                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                    ) : (
                                        <PackageCheck className="h-4 w-4" aria-hidden="true" />
                                    )}
                                    {loading ? dict.form.downloading : dict.form.downloadButton}
                                </Button>
                            </div>

                            <div className="mt-2 flex min-h-5 flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                                <div className="min-w-0 text-[11px] leading-4">
                                    {error ? (
                                        <p role="alert" className="font-medium text-destructive">
                                            {error}
                                        </p>
                                    ) : (
                                        <p className="text-muted-foreground">
                                            {dict.page.copyrightBilibiliRestriction}
                                        </p>
                                    )}
                                </div>
                                {heroMeta ? (
                                    <div className="shrink-0 text-[10px] leading-4 text-muted-foreground">
                                        {heroMeta}
                                    </div>
                                ) : null}
                            </div>
                        </form>
                    </section>

                    <UnifiedDownloaderLowerSections
                        parseResult={parseResult}
                        onCloseParseResult={closeParseResult}
                        onOpenExtractAudio={openResultAudioExtract}
                        onRequestPreview={openResultPreview}
                        onClearPreview={() => setActivePreview(null)}
                        activePreview={activePreview}
                        mobileAd={mobileAd}
                        downloadHistory={downloadHistory}
                        clearHistory={clearDownloadHistory}
                        onRedownload={handleRedownload}
                        historyRef={historyRef}
                        historyHydrated={historyHydrated}
                    />

                    {(leftRail || rightRail) && (
                        <details className="group border-t pt-1">
                            <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-md px-1 py-2 text-sm outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
                                <div className="min-w-0">
                                    <span className="font-medium">{workbenchCopy.helperTitle}</span>
                                    <span className="ms-2 hidden text-xs font-normal text-muted-foreground md:inline">
                                        {workbenchCopy.helperDescription}
                                    </span>
                                </div>
                                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
                            </summary>
                            <div className="grid gap-3 pb-2 pt-2 md:grid-cols-2 xl:grid-cols-3 [&>*]:min-w-0">
                                {leftRail}
                                {rightRail}
                            </div>
                        </details>
                    )}
                </div>
            </main>

            {footer}

            <Button
                type="button"
                variant="outline"
                size="icon"
                className={`fixed right-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-30 h-8 w-8 rounded-md bg-card transition-[opacity,transform] duration-150 ${
                    showBackToTop
                        ? 'pointer-events-auto opacity-100 translate-y-0'
                        : 'pointer-events-none opacity-0 translate-y-2'
                }`}
                aria-label={dict.common.backToTop}
                onClick={() => {
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
            >
                <ArrowUp className="h-3.5 w-3.5" aria-hidden="true" />
            </Button>
        </div>
    );
}
