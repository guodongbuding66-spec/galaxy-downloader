'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { ExternalLink, Loader2 } from 'lucide-react'
import { HlsVideoPlayer } from '@/components/hls-video-player'
import { Button } from '@/components/ui/button'
import { PlatformBadge } from '@/components/platform-badge'
import { ViewportSideRailAd } from '@/components/ads/viewport-side-rail-ad'
import { buildMediaPreviewUrl, buildResultPreviewForSelection } from '@/components/downloader/media-preview'
import { useAppLocale, useDictionary } from '@/i18n/client'
import { isApiRequestError, resolveApiErrorMessage } from '@/lib/api-errors'
import { isHlsPlaylistUrl } from '@/lib/hls-playback'
import { UnifiedParseReloadError, requestUnifiedParse } from '@/lib/unified-parse'
import type { UnifiedParseResult } from '@/lib/types'
import { normalizePlatform } from '@/lib/platforms'

type ParsedResultData = NonNullable<UnifiedParseResult['data']>

export function PlayPageClient() {
    const dict = useDictionary()
    const locale = useAppLocale()
    const searchParams = useSearchParams()

    const sourceUrl = (searchParams.get('url') || searchParams.get('play') || '').trim()
    const autoplay = searchParams.get('autoplay') === '1'
    const requestedItem = searchParams.get('item')?.trim() || undefined
    const requestedMediaType = searchParams.get('type') === 'audio' ? 'audio' : 'video'

    const [loading, setLoading] = useState(false)
    const [error, setError] = useState('')
    const [parseResult, setParseResult] = useState<ParsedResultData | null>(null)

    useEffect(() => {
        let cancelled = false

        if (!sourceUrl) return

        const loadSharedResult = async () => {
            setLoading(true)
            setError('')
            setParseResult(null)

            try {
                const parsed = await requestUnifiedParse(sourceUrl)
                if (cancelled) return

                setParseResult({
                    ...parsed.data,
                    platform: normalizePlatform(parsed.data.platform),
                })
            } catch (err) {
                if (cancelled) return
                if (err instanceof UnifiedParseReloadError) return

                if (isApiRequestError(err)) {
                    console.error('Shared playback parse failed', {
                        code: err.code,
                        status: err.status,
                        requestId: err.requestId,
                        details: err.details,
                    })
                }

                setError(resolveApiErrorMessage(err, dict))
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        void loadSharedResult()
        return () => {
            cancelled = true
        }
    }, [dict, sourceUrl])

    const visibleParseResult = sourceUrl ? parseResult : null
    const displayError = sourceUrl ? error : dict.errors.emptyUrl
    const canonicalSourceUrl = (visibleParseResult?.url || sourceUrl).trim()
    const selectedPreview = useMemo(() => visibleParseResult
        ? buildResultPreviewForSelection(visibleParseResult, {
              item: requestedItem,
              mediaType: requestedMediaType,
              autoplay,
          })
        : null, [autoplay, requestedItem, requestedMediaType, visibleParseResult])
    const hlsPlaybackUrl = useMemo(() => {
        if (selectedPreview?.mediaType !== 'video' || selectedPreview.item) return null

        const originPlaylistUrl = visibleParseResult?.originDownloadVideoUrl?.trim()
        const workerPlaylistUrl = visibleParseResult?.downloadVideoUrl?.trim()
        const isHlsVideo = visibleParseResult?.mediaActions?.video === 'browser-hls-download'
            || isHlsPlaylistUrl(originPlaylistUrl)
        if (!workerPlaylistUrl || !isHlsVideo) return null
        return workerPlaylistUrl
    }, [selectedPreview, visibleParseResult])
    const playbackUrl = useMemo(() => {
        if (hlsPlaybackUrl) return hlsPlaybackUrl
        if (!selectedPreview) return null
        return buildMediaPreviewUrl(selectedPreview)
    }, [hlsPlaybackUrl, selectedPreview])

    const canPlay = Boolean(selectedPreview)
    const displayTitle = selectedPreview?.title || visibleParseResult?.title || ''
    const showPlayerSurface = loading || Boolean(visibleParseResult)

    return (
        <main id="main-content" className="flex min-h-screen flex-col bg-background">
            <div className="flex-1 px-0 pb-5 pt-2 sm:px-4 sm:pt-4 md:px-5">
                <div className="mx-auto w-full max-w-7xl">
                    {showPlayerSurface ? (
                        <section className="overflow-hidden bg-black sm:rounded-md sm:border">
                            {loading ? (
                                <div className="flex aspect-video max-h-[74dvh] items-center justify-center text-sm text-white/65 md:max-h-[72vh] lg:max-h-[68vh]">
                                    <div className="flex items-center gap-2">
                                        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                                        <span>{dict.form.downloading}</span>
                                    </div>
                                </div>
                            ) : (canPlay && playbackUrl) ? (
                                selectedPreview?.mediaType === 'audio' ? (
                                    <div className="flex min-h-28 items-center px-3 sm:px-5">
                                        <audio
                                            src={playbackUrl}
                                            controls
                                            autoPlay={autoplay}
                                            preload="metadata"
                                            className="block w-full"
                                        />
                                    </div>
                                ) : hlsPlaybackUrl ? (
                                    <HlsVideoPlayer
                                        src={playbackUrl}
                                        controls
                                        autoPlay={autoplay}
                                        playsInline
                                        preload="metadata"
                                        className="block min-h-[320px] w-full max-h-[74dvh] bg-black md:max-h-[72vh] lg:max-h-[68vh]"
                                    />
                                ) : (
                                    <video
                                        src={playbackUrl}
                                        controls
                                        autoPlay={autoplay}
                                        playsInline
                                        preload="metadata"
                                        className="block min-h-[320px] w-full max-h-[74dvh] bg-black md:max-h-[72vh] lg:max-h-[68vh]"
                                    />
                                )
                            ) : (
                                <div className="flex aspect-video max-h-[74dvh] items-center justify-center bg-black px-5 text-center text-sm leading-6 text-white/65 md:max-h-[72vh] lg:max-h-[68vh]">
                                    {dict.result.sharePlayUnavailable}
                                </div>
                            )}
                        </section>
                    ) : null}

                    <section className="px-3 py-3 sm:px-0 sm:py-4">
                        {!loading && displayError ? (
                            <div className="border-y py-4 sm:rounded-md sm:border sm:px-4">
                                <p role="alert" className="text-sm leading-6 text-destructive">{displayError}</p>
                                <Button asChild size="sm" variant="outline" className="mt-3">
                                    <Link href={`/${locale}`}>{dict.common.home}</Link>
                                </Button>
                            </div>
                        ) : null}

                        {!loading && !displayError && visibleParseResult ? (
                            <div className="min-w-0 border-b pb-3">
                                <h1 className="max-w-4xl text-pretty text-base font-semibold leading-6 tracking-[-0.015em] sm:text-lg" title={displayTitle}>
                                    {displayTitle}
                                </h1>
                                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                    <PlatformBadge platform={visibleParseResult.platform} />
                                    {canonicalSourceUrl ? (
                                        <Button asChild size="xs" variant="ghost" className="text-muted-foreground">
                                            <a href={canonicalSourceUrl} target="_blank" rel="noopener noreferrer">
                                                <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                                                <span>{dict.history.viewSource}</span>
                                            </a>
                                        </Button>
                                    ) : null}
                                </div>
                            </div>
                        ) : null}

                        {!loading && !displayError && visibleParseResult ? (
                            <div className="pt-3">
                                <ViewportSideRailAd slot="5740014745" showOn="mobile" />
                                <ViewportSideRailAd slot="6380909506" showOn="desktop" />
                            </div>
                        ) : null}
                    </section>
                </div>
            </div>
        </main>
    )
}
