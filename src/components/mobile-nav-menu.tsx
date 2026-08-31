'use client'

import { useState } from 'react'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { Box, BriefcaseBusiness, ExternalLink, HardDriveDownload, Menu, Newspaper } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog'
import { DeferredChangelogDialog } from '@/components/deferred-changelog-dialog'
import { DeferredLanguageSwitcher } from '@/components/deferred-language-switcher'
import { ThemeSwitcher } from '@/components/theme-switcher'
import { useDictionary } from '@/i18n/client'
import { i18n } from '@/lib/i18n/config'
import { LOCAL_ENGINE_RELEASE_URL } from '@/lib/local-engine'

interface MobileNavMenuProps {
    defaultOpen?: boolean
}

const COPY: Record<string, { engine: string; other: string }> = {
    zh: { engine: '下载 Galaxy Local Engine', other: '其他工具' },
    'zh-tw': { engine: '下載 Galaxy Local Engine', other: '其他工具' },
    en: { engine: 'Download Galaxy Local Engine', other: 'More tools' },
    ja: { engine: 'Galaxy Local Engine をダウンロード', other: 'その他のツール' },
    es: { engine: 'Descargar Galaxy Local Engine', other: 'Más herramientas' },
    ru: { engine: 'Скачать Galaxy Local Engine', other: 'Другие инструменты' },
}

const RELATED_SITES = [
    {
        href: 'https://ai-foreign-trade-os.pages.dev/',
        label: 'AI 外贸工作台',
        icon: BriefcaseBusiness,
    },
    {
        href: 'https://container-load-planner.pages.dev/',
        label: '外贸装柜智算',
        icon: Box,
    },
    {
        href: 'https://isunor-industry-daily.pages.dev/',
        label: 'iSUNOR 决策级情报',
        icon: Newspaper,
    },
] as const

export function MobileNavMenu({
    defaultOpen = false,
}: MobileNavMenuProps) {
    const dict = useDictionary()
    const pathname = usePathname()
    const firstSegment = pathname.split('/').filter(Boolean)[0]
    const locale = i18n.locales.includes(firstSegment as (typeof i18n.locales)[number])
        ? firstSegment
        : i18n.defaultLocale
    const copy = COPY[locale] || COPY.en
    const [open, setOpen] = useState(defaultOpen)

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={dict.page.openMenuLabel}>
                    <Menu className="h-5 w-5" aria-hidden="true" />
                </Button>
            </DialogTrigger>
            <DialogContent
                showCloseButton={false}
                className="top-auto bottom-4 left-1/2 w-[calc(100%-2rem)] max-w-sm translate-x-[-50%] translate-y-0 rounded-xl p-4"
            >
                <DialogHeader className="sr-only">
                    <DialogTitle>{dict.page.openMenuLabel}</DialogTitle>
                </DialogHeader>

                <div className="space-y-3">
                    <Button className="w-full justify-start" asChild>
                        <a href={LOCAL_ENGINE_RELEASE_URL} onClick={() => setOpen(false)}>
                            <HardDriveDownload className="h-4 w-4" aria-hidden="true" />
                            <span>{copy.engine}</span>
                        </a>
                    </Button>

                    <div className="rounded-xl border border-border bg-muted/20 p-2">
                        <div className="px-2 pb-1.5 text-xs font-semibold text-muted-foreground">{copy.other}</div>
                        <div className="space-y-1">
                            {RELATED_SITES.map((site) => {
                                const Icon = site.icon
                                return (
                                    <Button key={site.href} variant="ghost" className="w-full justify-start gap-2" asChild>
                                        <a
                                            href={site.href}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={() => setOpen(false)}
                                        >
                                            <Icon className="h-4 w-4" aria-hidden="true" />
                                            <span className="min-w-0 flex-1 truncate text-left">{site.label}</span>
                                            <ExternalLink className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                                        </a>
                                    </Button>
                                )
                            })}
                        </div>
                    </div>

                    <div className="space-y-1 rounded-xl border border-border bg-muted/20 p-1">
                        <DeferredLanguageSwitcher fullWidth />
                        <ThemeSwitcher fullWidth />
                        <DeferredChangelogDialog triggerClassName="w-full justify-start" />
                    </div>

                    <Button variant="outline" className="w-full justify-start" asChild>
                        <a
                            href="https://github.com/guodongbuding66-spec/galaxy-downloader"
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={() => setOpen(false)}
                        >
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
                </div>
            </DialogContent>
        </Dialog>
    )
}
