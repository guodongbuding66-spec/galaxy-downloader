'use client';

import { startTransition, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import dynamic from 'next/dynamic';
import { usePathname, useSearchParams } from 'next/navigation';
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

import { toast } from '@/lib/deferred-toast';
import { DeferredAudioExtractDialog } from '@/components/deferred-audio-extract-dialog';
import { useTopBarActions } from '@/components/layout/top-bar-actions';
import type { AudioExtractTask } from '@/components/audio-tool/types';
import type { MediaPreviewRequest } from '@/components/downloader/media-preview';
import { buildResultPreviewForSelection } from '@/components/downloader/media-preview';
import {
    ArrowRight,
    ArrowUp,
    ClipboardPaste,
    Laptop2,
    Loader2,
    LockKeyhole,
    PackageCheck,
    ShieldCheck,
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
    eyebrow: string;
    inputLabel: string;
    local: string;
    private: string;
    free: string;
    flowTitle: string;
    helperTitle: string;
    helperDescription: string;
    steps: [string, string, string, string];
};

const WORKBENCH_COPY: Record<string, WorkbenchCopy> = {
    zh: {
        eyebrow: '本地媒体工作台',
        inputLabel: '媒体链接或分享文本',
        local: '本机处理',
        private: '媒体不上传',
        free: '本地合成免费',
        flowTitle: '一键成品流程',
        helperTitle: '更多工具与平台支持',
        helperDescription: '主流程完成后再查看历史、平台说明和辅助工具，避免打断下载任务。',
        steps: ['解析媒体', '获取所选画质', '本地合成音画 / 字幕 / 封面', '保存最终 MP4'],
    },
    'zh-tw': {
        eyebrow: '本機媒體工作台',
        inputLabel: '媒體連結或分享文字',
        local: '本機處理',
        private: '媒體不上傳',
        free: '本機合成免費',
        flowTitle: '一鍵成品流程',
        helperTitle: '更多工具與平台支援',
        helperDescription: '先完成主要下載流程，再查看歷史、平台說明與輔助工具。',
        steps: ['解析媒體', '取得所選畫質', '本機合成音訊 / 字幕 / 封面', '儲存最終 MP4'],
    },
    en: {
        eyebrow: 'Local media workbench',
        inputLabel: 'Media URL or shared text',
        local: 'Processed locally',
        private: 'Media stays on device',
        free: 'Free local assembly',
        flowTitle: 'One finished-file workflow',
        helperTitle: 'More tools and platform support',
        helperDescription: 'Finish the primary download first, then use history, platform guides and secondary tools when needed.',
        steps: ['Resolve media', 'Fetch selected quality', 'Assemble audio / subtitles / cover locally', 'Save final MP4'],
    },
    ja: {
        eyebrow: 'ローカルメディアワークベンチ',
        inputLabel: 'メディアURLまたは共有テキスト',
        local: 'ローカル処理',
        private: 'メディアをアップロードしない',
        free: 'ローカル合成は無料',
        flowTitle: '完成ファイルまでの流れ',
        helperTitle: 'その他のツールと対応プラットフォーム',
        helperDescription: 'まず主要なダウンロードを完了し、その後に履歴や補助ツールを利用できます。',
        steps: ['メディア解析', '選択画質を取得', '音声・字幕・カバーを端末で合成', '最終MP4を保存'],
    },
    es: {
        eyebrow: 'Mesa de medios local',
        inputLabel: 'URL del medio o texto compartido',
        local: 'Procesado local',
        private: 'El medio no se sube',
        free: 'Ensamblado local gratis',
        flowTitle: 'Flujo de un solo archivo final',
        helperTitle: 'Más herramientas y plataformas',
        helperDescription: 'Completa primero la descarga principal y consulta después el historial, las guías y las herramientas secundarias.',
        steps: ['Resolver medio', 'Obtener la calidad elegida', 'Ensamblar audio / subtítulos / portada localmente', 'Guardar MP4 final'],
    },
    ru: {
        eyebrow: 'Локальная медиамастерская',
        inputLabel: 'Ссылка на медиа или текст публикации',
        local: 'Обработка на устройстве',
        private: 'Медиа не загружается',
        free: 'Локальная сборка бесплатно',
        flowTitle: 'Один процесс — один готовый файл',
        helperTitle: 'Дополнительные инструменты и платформы',
        helperDescription: 'Сначала завершите основную загрузку, затем при необходимости используйте историю, справку и дополнительные инструменты.',
        steps: ['Разобрать медиа', 'Получить выбранное качество', 'Локально собрать аудио / субтитры / обложку', 'Сохранить итоговый MP4'],
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
    const dict = useDictionary()
    const { setActions: setTopBarActions } = useTopBarActions()
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

            <main id="main-content" className="flex-1 px-3 py-5 sm:px-5 sm:py-7 md:px-6 md:py-9">
                <div className="mx-auto w-full max-w-6xl space-y-8">
                    <section className="overflow-hidden rounded-3xl border bg-card workbench-shadow">
                        <div className="p-5 sm:p-7 md:p-9">
                            <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
                                <div className="max-w-3xl space-y-3">
                                    <div className="inline-flex items-center gap-2 rounded-full border bg-muted/55 px-3 py-1.5 text-xs font-medium text-muted-foreground">
                                        <Laptop2 className="h-3.5 w-3.5" aria-hidden="true" />
                                        {workbenchCopy.eyebrow}
                                    </div>
                                    <h1 className="text-3xl font-semibold tracking-[-0.035em] text-balance sm:text-4xl md:text-[2.7rem] md:leading-[1.08]">
                                        {dict.unified.pageTitle}
                                    </h1>
                                    <p className="max-w-2xl text-sm leading-6 text-muted-foreground text-pretty sm:text-[15px]">
                                        {dict.unified.pageDescription}
                                    </p>
                                </div>

                                <div className="flex flex-wrap gap-2 lg:max-w-xs lg:justify-end" aria-label={workbenchCopy.flowTitle}>
                                    <span className="inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground">
                                        <Laptop2 className="h-3.5 w-3.5" aria-hidden="true" />
                                        {workbenchCopy.local}
                                    </span>
                                    <span className="inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground">
                                        <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
                                        {workbenchCopy.private}
                                    </span>
                                    <span className="inline-flex items-center gap-1.5 rounded-full border bg-background px-3 py-1.5 text-xs font-medium text-muted-foreground">
                                        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                                        {workbenchCopy.free}
                                    </span>
                                </div>
                            </div>

                            <form onSubmit={handleSubmit} className="mt-7 space-y-4">
                                <div className="space-y-2.5">
                                    <label htmlFor="url" className="block text-sm font-medium">
                                        {workbenchCopy.inputLabel}
                                    </label>
                                    <div className="rounded-2xl border bg-background p-2 shadow-sm transition-[border-color,box-shadow] duration-150 focus-within:border-primary/45 focus-within:ring-4 focus-within:ring-primary/10">
                                        <Textarea
                                            id="url"
                                            ref={urlInputRef}
                                            value={url}
                                            onChange={(e) => setUrl(e.target.value)}
                                            placeholder={dict.unified.placeholder}
                                            required
                                            className="min-h-24 resize-none border-0 bg-transparent px-3 py-2 text-base leading-6 shadow-none focus-visible:ring-0 sm:text-sm"
                                        />
                                        <div className="flex flex-col gap-2 border-t px-1 pt-2 sm:flex-row sm:items-center sm:justify-end">
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                className="min-h-11 gap-2 px-4 active:scale-[0.96] transition-[transform,background-color] duration-150 sm:min-w-32"
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
                                                {dict.form.pasteButton}
                                            </Button>
                                            <Button
                                                type="submit"
                                                size="lg"
                                                className="min-h-11 gap-2 px-6 font-semibold active:scale-[0.96] transition-[transform,background-color] duration-150 sm:min-w-44"
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
                                    </div>
                                </div>

                                <div role="status" aria-live="polite" className="min-h-5">
                                    {error && (
                                        <p role="alert" className="text-sm font-medium text-destructive">
                                            {error}
                                        </p>
                                    )}
                                </div>

                                <div className="space-y-3">
                                    <div className="rounded-xl border border-amber-500/20 bg-amber-500/8 px-3 py-2.5 text-xs leading-5 text-amber-700 dark:text-amber-300 break-words">
                                        {dict.page.copyrightBilibiliRestriction}
                                    </div>
                                    {heroMeta}
                                </div>
                            </form>
                        </div>

                        <div className="border-t bg-muted/30 px-5 py-5 sm:px-7 md:px-9">
                            <div className="mb-3 flex items-center justify-between gap-3">
                                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                                    {workbenchCopy.flowTitle}
                                </p>
                            </div>
                            <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                                {workbenchCopy.steps.map((step, index) => (
                                    <li key={step} className="flex min-w-0 items-center gap-3 rounded-xl bg-background/80 px-3 py-3 ring-1 ring-border/70">
                                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted text-xs font-semibold tabular-nums text-foreground">
                                            {index + 1}
                                        </span>
                                        <span className="min-w-0 flex-1 text-xs font-medium leading-5 text-foreground/80 text-pretty">
                                            {step}
                                        </span>
                                        {index < workbenchCopy.steps.length - 1 && (
                                            <ArrowRight className="hidden h-3.5 w-3.5 shrink-0 text-muted-foreground/60 lg:block" aria-hidden="true" />
                                        )}
                                    </li>
                                ))}
                            </ol>
                        </div>
                    </section>

                    <div className="space-y-6">
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
                    </div>

                    {(leftRail || rightRail) && (
                        <section className="space-y-4" aria-labelledby="supporting-tools-title">
                            <div className="max-w-2xl space-y-1.5">
                                <h2 id="supporting-tools-title" className="text-lg font-semibold tracking-tight">
                                    {workbenchCopy.helperTitle}
                                </h2>
                                <p className="text-sm leading-6 text-muted-foreground text-pretty">
                                    {workbenchCopy.helperDescription}
                                </p>
                            </div>
                            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 [&>*]:min-w-0">
                                {leftRail}
                                {rightRail}
                            </div>
                        </section>
                    )}
                </div>
            </main>

            {footer}

            <Button
                type="button"
                size="icon"
                className={`fixed right-4 bottom-[calc(1rem+env(safe-area-inset-bottom))] z-30 h-10 w-10 rounded-full shadow-md transition-[opacity,transform] duration-200 ease-out active:scale-[0.96] ${
                    showBackToTop
                        ? 'pointer-events-auto opacity-100 translate-y-0 scale-100'
                        : 'pointer-events-none opacity-0 translate-y-2 scale-95'
                }`}
                aria-label={dict.common.backToTop}
                onClick={() => {
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
            >
                <ArrowUp className="h-4 w-4" aria-hidden="true" />
            </Button>
        </div>
    );
}
