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

const COPY: Record<string, { engine: string; other: string; settings: string }> = {
    zh: { engine: '下载 Galaxy Local Engine', other: '其他工具', settings: '设置' },
    'zh-tw': { engine: '下載 Galaxy Local Engine', other: '其他工具', settings: '設定' },
    en: { engine: 'Download Galaxy Local Engine', other: 'More tools', settings: 'Settings' },
    ja: { engine: 'Galaxy Local Engine をダウンロード', other: 'その他のツール', settings: '設定' },
    es: { engine: 'Descargar Galaxy Local Engine', other: 'Más herramientas', settings: 'Ajustes' },
    ru: { engine: 'Скачать Galaxy Local Engine', other: 'Другие инструменты', settings: 'Настройки' },
}

const RELATED_SITES = [
    { href: 'https://ai-foreign-trade-os.pages.dev/', label: 'AI 外贸工作台', icon: BriefcaseBusiness },
    { href: 'https://container-load-planner.pages.dev/', label: '外贸装柜智算', icon: Box },
    { href: 'https://isunor-industry-daily.pages.dev/', label: 'iSUNOR 决策级情报', icon: Newspaper },
] as const

export function MobileNavMenu({ defaultOpen = false }: MobileNavMenuProps) {
    const dict = useDictionary()
    const pathname = usePathname() || ''
    const firstSegment = pathname.split('/').filter(Boolean)[0]
    const locale = i18n.locales.includes(firstSegment as (typeof i18n.locales)[number])
        ? firstSegment
        : i18n.defaultLocale
    const copy = COPY[locale] || COPY.en
    const [open, setOpen] = useState(defaultOpen)

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8" aria-label={dict.page.openMenuLabel}>
                    <Menu className="h-4 w-4" aria-hidden="true" />
                </Button>
            </DialogTrigger>
            <DialogContent
                showCloseButton={false}
                className="bottom-3 left-1/2 top-auto w-[calc(100%-1.5rem)] max-w-sm -translate-x-1/2 translate-y-0 gap-2 rounded-md p-3"
            >
                <DialogHeader className="sr-only">
                    <DialogTitle>{dict.page.openMenuLabel}</DialogTitle>
                </DialogHeader>

                <Button size="sm" className="h-9 w-full justify-start" asChild>
                    <a href={LOCAL_ENGINE_RELEASE_URL} onClick={() => setOpen(false)}>
                        <HardDriveDownload className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>{copy.engine}</span>
                    </a>
                </Button>

                <section className="border-t pt-2">
                    <div className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{copy.other}</div>
                    <div className="divide-y">
                        {RELATED_SITES.map((site) => {
                            const Icon = site.icon
                            return (
                                <a
                                    key={site.href}
                                    href={site.href}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={() => setOpen(false)}
                                    className="flex h-9 items-center gap-2 px-1 text-xs transition-colors duration-150 hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                                >
                                    <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                                    <span className="min-w-0 flex-1 truncate text-left">{site.label}</span>
                                    <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                                </a>
                            )
                        })}
                    </div>
                </section>

                <section className="border-t pt-2">
                    <div className="px-1 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{copy.settings}</div>
                    <div className="space-y-0.5">
                        <DeferredLanguageSwitcher fullWidth />
                        <ThemeSwitcher fullWidth />
                        <DeferredChangelogDialog triggerClassName="w-full justify-start" />
                    </div>
                </section>

                <Button variant="ghost" size="sm" className="h-9 w-full justify-start border-t rounded-none pt-2" asChild>
                    <a
                        href="https://github.com/guodongbuding66-spec/galaxy-downloader"
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={() => setOpen(false)}
                    >
                        <Image
                            src="/platform-icons/github.svg"
                            alt=""
                            width={14}
                            height={14}
                            aria-hidden="true"
                            className="dark:invert"
                        />
                        <span>GitHub</span>
                    </a>
                </Button>
            </DialogContent>
        </Dialog>
    )
}
