'use client'

import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { Download, History, Home, MessageSquare, Music } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DeferredLanguageSwitcher } from '@/components/deferred-language-switcher'
import { DeferredChangelogDialog } from '@/components/deferred-changelog-dialog'
import { ThemeSwitcher } from '@/components/theme-switcher'
import { DeferredMobileNavMenu } from '@/components/deferred-mobile-nav-menu'
import { useDictionary } from '@/i18n/client'
import { i18n } from '@/lib/i18n/config'
import { useTopBarActions } from './top-bar-actions'

interface AppTopBarProps {
    showHistoryShortcut?: boolean
    onHistoryClick?: () => void
    showAudioTool?: boolean
    onAudioToolClick?: () => void
    showHomeButton?: boolean
    homeHref?: string
}

const SKIP_COPY: Record<string, string> = {
    zh: '跳到主要内容',
    'zh-tw': '跳到主要內容',
    en: 'Skip to main content',
    ja: 'メインコンテンツへ移動',
    es: 'Saltar al contenido principal',
    ru: 'Перейти к основному содержимому',
}

export function AppTopBar({
    showHistoryShortcut = false,
    onHistoryClick,
    showAudioTool = false,
    onAudioToolClick,
    showHomeButton = false,
    homeHref = '/',
}: AppTopBarProps) {
    const dict = useDictionary()
    const { actions } = useTopBarActions()
    const pathname = usePathname()
    const firstSegment = pathname.split('/').filter(Boolean)[0]
    const locale = i18n.locales.includes(firstSegment as (typeof i18n.locales)[number])
        ? firstSegment
        : i18n.defaultLocale
    const feedbackHref = `/${locale}/feedback`
    const resolvedHomeHref = homeHref === '/' ? `/${locale}` : homeHref
    const shouldShowHomeButton = showHomeButton || (pathname !== `/${locale}` && pathname !== `/${locale}/`)
    const effectiveShowHistoryShortcut = showHistoryShortcut || actions.showHistoryShortcut
    const effectiveHistoryClick = onHistoryClick ?? actions.onHistoryClick
    const effectiveShowAudioTool = showAudioTool || actions.showAudioTool
    const effectiveAudioToolClick = onAudioToolClick ?? actions.onAudioToolClick

    return (
        <header
            className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur-xl supports-[backdrop-filter]:bg-background/75"
            style={{ paddingTop: 'env(safe-area-inset-top)' }}
        >
            <a
                href="#main-content"
                className="sr-only fixed left-3 top-3 z-[60] rounded-lg bg-background px-3 py-2 text-sm font-medium shadow-lg ring-2 ring-ring focus:not-sr-only"
            >
                {SKIP_COPY[locale] || SKIP_COPY.en}
            </a>

            <div className="mx-auto flex min-h-14 w-full max-w-6xl items-center gap-2 px-3 sm:px-5 md:px-6">
                <Link
                    href={resolvedHomeHref}
                    className="group flex min-w-0 shrink-0 items-center gap-2 rounded-lg py-1.5 pr-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={dict.metadata.siteName}
                >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm transition-transform duration-150 group-active:scale-[0.96]">
                        <Download className="h-4 w-4" aria-hidden="true" />
                    </span>
                    <span className="hidden min-w-0 sm:block">
                        <span className="block truncate text-sm font-semibold tracking-tight">Galaxy Downloader</span>
                        <span className="hidden text-[11px] leading-4 text-muted-foreground lg:block">Local media workbench</span>
                    </span>
                </Link>

                <nav className="ml-1 hidden min-w-0 flex-1 items-center gap-1 md:flex" aria-label="Tools">
                    {shouldShowHomeButton && (
                        <Button variant="ghost" size="sm" className="gap-1.5 active:scale-[0.96] transition-transform duration-150" asChild>
                            <Link href={resolvedHomeHref}>
                                <Home className="h-4 w-4" aria-hidden="true" />
                                <span>{dict.common.home}</span>
                            </Link>
                        </Button>
                    )}
                    {effectiveShowHistoryShortcut && effectiveHistoryClick && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="gap-1.5 active:scale-[0.96] transition-[transform,background-color] duration-150"
                            onClick={effectiveHistoryClick}
                        >
                            <History className="h-4 w-4" aria-hidden="true" />
                            <span>{dict.history.title}</span>
                        </Button>
                    )}
                    {effectiveShowAudioTool && effectiveAudioToolClick && (
                        <Button
                            variant="ghost"
                            size="sm"
                            className="gap-1.5 active:scale-[0.96] transition-[transform,background-color] duration-150"
                            onClick={effectiveAudioToolClick}
                        >
                            <Music className="h-4 w-4" aria-hidden="true" />
                            <span>{dict.audioTool.triggerButton}</span>
                        </Button>
                    )}
                </nav>

                <div className="ml-auto flex shrink-0 items-center gap-1">
                    {effectiveShowHistoryShortcut && effectiveHistoryClick && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-10 w-10 active:scale-[0.96] transition-[transform,background-color] duration-150 md:hidden"
                            onClick={effectiveHistoryClick}
                            aria-label={dict.history.title}
                        >
                            <History className="h-4 w-4" aria-hidden="true" />
                        </Button>
                    )}
                    {effectiveShowAudioTool && effectiveAudioToolClick && (
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-10 w-10 active:scale-[0.96] transition-[transform,background-color] duration-150 md:hidden"
                            onClick={effectiveAudioToolClick}
                            aria-label={dict.audioTool.triggerButton}
                        >
                            <Music className="h-4 w-4" aria-hidden="true" />
                        </Button>
                    )}

                    <Button variant="ghost" size="icon" className="h-10 w-10 active:scale-[0.96] transition-[transform,background-color] duration-150 sm:hidden" asChild>
                        <Link href={feedbackHref} aria-label={dict.feedback.triggerButton}>
                            <MessageSquare className="h-4 w-4" aria-hidden="true" />
                        </Link>
                    </Button>

                    <Button variant="ghost" size="sm" className="hidden gap-1.5 active:scale-[0.96] transition-[transform,background-color] duration-150 sm:inline-flex" asChild>
                        <Link href={feedbackHref}>
                            <MessageSquare className="h-4 w-4" aria-hidden="true" />
                            <span>{dict.feedback.triggerButton}</span>
                        </Link>
                    </Button>

                    <Button variant="ghost" size="sm" className="hidden gap-1.5 active:scale-[0.96] transition-[transform,background-color] duration-150 lg:inline-flex" asChild>
                        <a href="https://github.com/guodongbuding66-spec/galaxy-downloader" target="_blank" rel="noopener noreferrer">
                            <Image
                                src="/platform-icons/github.svg"
                                alt=""
                                width={16}
                                height={16}
                                aria-hidden="true"
                                className="dark:invert"
                            />
                            <span>GitHub</span>
                        </a>
                    </Button>

                    <div className="hidden items-center gap-1 md:flex">
                        <ThemeSwitcher />
                        <DeferredChangelogDialog triggerIconOnly triggerClassName="h-10 w-10" />
                        <DeferredLanguageSwitcher iconOnly />
                    </div>
                    <div className="md:hidden">
                        <DeferredMobileNavMenu />
                    </div>
                </div>
            </div>
        </header>
    )
}
