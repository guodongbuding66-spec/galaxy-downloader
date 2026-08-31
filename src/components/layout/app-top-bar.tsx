'use client'

import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { Download, HardDriveDownload, History, Home, MessageSquare, Music } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DeferredLanguageSwitcher } from '@/components/deferred-language-switcher'
import { DeferredChangelogDialog } from '@/components/deferred-changelog-dialog'
import { ExternalToolsMenu } from '@/components/external-tools-menu'
import { ThemeSwitcher } from '@/components/theme-switcher'
import { DeferredMobileNavMenu } from '@/components/deferred-mobile-nav-menu'
import { useDictionary } from '@/i18n/client'
import { i18n } from '@/lib/i18n/config'
import { LOCAL_ENGINE_RELEASE_URL } from '@/lib/local-engine'
import { useTopBarActions } from './top-bar-actions'

interface AppTopBarProps {
    showHistoryShortcut?: boolean
    onHistoryClick?: () => void
    showAudioTool?: boolean
    onAudioToolClick?: () => void
    showHomeButton?: boolean
    homeHref?: string
}

const NAV_COPY: Record<string, { skip: string; tools: string; engine: string }> = {
    zh: { skip: '跳到主要内容', tools: '工具', engine: '本地引擎' },
    'zh-tw': { skip: '跳到主要內容', tools: '工具', engine: '本機引擎' },
    en: { skip: 'Skip to main content', tools: 'Tools', engine: 'Local Engine' },
    ja: { skip: 'メインコンテンツへ移動', tools: 'ツール', engine: 'Local Engine' },
    es: { skip: 'Saltar al contenido principal', tools: 'Herramientas', engine: 'Local Engine' },
    ru: { skip: 'Перейти к основному содержимому', tools: 'Инструменты', engine: 'Local Engine' },
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
    const navCopy = NAV_COPY[locale] || NAV_COPY.en
    const feedbackHref = `/${locale}/feedback`
    const resolvedHomeHref = homeHref === '/' ? `/${locale}` : homeHref
    const shouldShowHomeButton = showHomeButton || (pathname !== `/${locale}` && pathname !== `/${locale}/`)
    const effectiveShowHistoryShortcut = showHistoryShortcut || actions.showHistoryShortcut
    const effectiveHistoryClick = onHistoryClick ?? actions.onHistoryClick
    const effectiveShowAudioTool = showAudioTool || actions.showAudioTool
    const effectiveAudioToolClick = onAudioToolClick ?? actions.onAudioToolClick

    return (
        <header
            className="sticky top-0 z-40 border-b bg-background/96 supports-[backdrop-filter]:backdrop-blur-sm"
            style={{ paddingTop: 'env(safe-area-inset-top)' }}
        >
            <a
                href="#main-content"
                className="sr-only fixed left-3 top-3 z-[60] rounded-md border bg-background px-2.5 py-1.5 text-xs font-medium focus:not-sr-only"
            >
                {navCopy.skip}
            </a>

            <div className="mx-auto flex h-11 w-full max-w-[1380px] items-center gap-1.5 px-3 sm:px-4 md:px-5">
                <Link
                    href={resolvedHomeHref}
                    className="ui-pressable flex min-w-0 shrink-0 items-center gap-2 rounded-md px-1.5 py-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    aria-label={dict.metadata.siteName}
                >
                    <Download className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span className="hidden truncate text-sm font-semibold tracking-[-0.015em] sm:block">Galaxy Downloader</span>
                </Link>

                <div className="mx-1 hidden h-4 w-px bg-border md:block" aria-hidden="true" />

                <nav className="hidden min-w-0 flex-1 items-center gap-0.5 md:flex" aria-label={navCopy.tools}>
                    {shouldShowHomeButton && (
                        <Button variant="ghost" size="xs" asChild>
                            <Link href={resolvedHomeHref}>
                                <Home className="h-3.5 w-3.5" aria-hidden="true" />
                                <span>{dict.common.home}</span>
                            </Link>
                        </Button>
                    )}
                    {effectiveShowHistoryShortcut && effectiveHistoryClick && (
                        <Button variant="ghost" size="xs" onClick={effectiveHistoryClick}>
                            <History className="h-3.5 w-3.5" aria-hidden="true" />
                            <span>{dict.history.title}</span>
                        </Button>
                    )}
                    {effectiveShowAudioTool && effectiveAudioToolClick && (
                        <Button variant="ghost" size="xs" onClick={effectiveAudioToolClick}>
                            <Music className="h-3.5 w-3.5" aria-hidden="true" />
                            <span>{dict.audioTool.triggerButton}</span>
                        </Button>
                    )}
                    <ExternalToolsMenu />
                </nav>

                <div className="ml-auto flex shrink-0 items-center gap-0.5">
                    <Button variant="ghost" size="xs" className="hidden lg:inline-flex" asChild>
                        <a href={LOCAL_ENGINE_RELEASE_URL}>
                            <HardDriveDownload className="h-3.5 w-3.5" aria-hidden="true" />
                            <span>{navCopy.engine}</span>
                        </a>
                    </Button>

                    {effectiveShowHistoryShortcut && effectiveHistoryClick && (
                        <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={effectiveHistoryClick} aria-label={dict.history.title}>
                            <History className="h-3.5 w-3.5" aria-hidden="true" />
                        </Button>
                    )}
                    {effectiveShowAudioTool && effectiveAudioToolClick && (
                        <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={effectiveAudioToolClick} aria-label={dict.audioTool.triggerButton}>
                            <Music className="h-3.5 w-3.5" aria-hidden="true" />
                        </Button>
                    )}
                    <Button variant="ghost" size="icon" className="h-8 w-8 lg:hidden" asChild>
                        <a href={LOCAL_ENGINE_RELEASE_URL} aria-label={navCopy.engine} title={navCopy.engine}>
                            <HardDriveDownload className="h-3.5 w-3.5" aria-hidden="true" />
                        </a>
                    </Button>

                    <Button variant="ghost" size="icon" className="h-8 w-8" asChild>
                        <Link href={feedbackHref} aria-label={dict.feedback.triggerButton} title={dict.feedback.triggerButton}>
                            <MessageSquare className="h-3.5 w-3.5" aria-hidden="true" />
                        </Link>
                    </Button>

                    <Button variant="ghost" size="icon" className="hidden h-8 w-8 lg:inline-flex" asChild>
                        <a href="https://github.com/guodongbuding66-spec/galaxy-downloader" target="_blank" rel="noopener noreferrer" aria-label="GitHub" title="GitHub">
                            <Image
                                src="/platform-icons/github.svg"
                                alt=""
                                width={15}
                                height={15}
                                aria-hidden="true"
                                className="dark:invert"
                            />
                        </a>
                    </Button>

                    <div className="hidden items-center gap-0.5 md:flex">
                        <ThemeSwitcher />
                        <DeferredChangelogDialog triggerIconOnly triggerClassName="h-8 w-8" />
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