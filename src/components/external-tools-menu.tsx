'use client'

import { usePathname } from 'next/navigation'
import { Box, BriefcaseBusiness, ExternalLink, Newspaper } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog'
import { i18n } from '@/lib/i18n/config'

const EXTERNAL_TOOLS = [
    {
        href: 'https://ai-foreign-trade-os.pages.dev/',
        zhName: 'AI 外贸工作台',
        enName: 'AI Foreign Trade OS',
        zhDescription: '客户、CRM、报价、产品与外贸自动化工作台',
        enDescription: 'CRM, quoting, products and foreign-trade automation',
        icon: BriefcaseBusiness,
    },
    {
        href: 'https://container-load-planner.pages.dev/',
        zhName: '外贸装柜智算',
        enName: 'Container Load Planner',
        zhDescription: '现场易执行 / 极限理论双轨装柜计算与 3D 指导',
        enDescription: 'Practical and theoretical container loading with 3D guidance',
        icon: Box,
    },
    {
        href: 'https://isunor-industry-daily.pages.dev/',
        zhName: 'iSUNOR 决策级情报',
        enName: 'iSUNOR Industry Intelligence',
        zhDescription: '行业日报、竞品、贸易政策与业务机会情报',
        enDescription: 'Industry, competitor, trade-policy and opportunity intelligence',
        icon: Newspaper,
    },
] as const

const COPY: Record<string, { trigger: string; title: string; description: string }> = {
    zh: { trigger: '其他工具', title: '其他工具', description: '打开同一工作流中的其他业务工具。' },
    'zh-tw': { trigger: '其他工具', title: '其他工具', description: '開啟同一工作流程中的其他業務工具。' },
    en: { trigger: 'More tools', title: 'More tools', description: 'Open other tools in this workflow.' },
    ja: { trigger: 'その他のツール', title: 'その他のツール', description: '関連する業務ツールを開きます。' },
    es: { trigger: 'Más herramientas', title: 'Más herramientas', description: 'Abre las demás herramientas de este flujo.' },
    ru: { trigger: 'Другие инструменты', title: 'Другие инструменты', description: 'Откройте другие инструменты этого процесса.' },
}

export function ExternalToolsMenu({ triggerClassName = '' }: { triggerClassName?: string }) {
    const pathname = usePathname() || ''
    const firstSegment = pathname.split('/').filter(Boolean)[0]
    const locale = i18n.locales.includes(firstSegment as (typeof i18n.locales)[number])
        ? firstSegment
        : i18n.defaultLocale
    const copy = COPY[locale] || COPY.en
    const useChineseNames = locale === 'zh' || locale === 'zh-tw'

    return (
        <Dialog>
            <DialogTrigger asChild>
                <Button variant="ghost" size="xs" className={`gap-1.5 ${triggerClassName}`.trim()}>
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    <span>{copy.trigger}</span>
                </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
                <DialogHeader className="pr-7">
                    <DialogTitle>{copy.title}</DialogTitle>
                    <DialogDescription>{copy.description}</DialogDescription>
                </DialogHeader>

                <div className="divide-y border-y">
                    {EXTERNAL_TOOLS.map((tool) => {
                        const Icon = tool.icon
                        const name = useChineseNames ? tool.zhName : tool.enName
                        const description = useChineseNames ? tool.zhDescription : tool.enDescription
                        return (
                            <a
                                key={tool.href}
                                href={tool.href}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="group flex min-w-0 items-start gap-2.5 px-1 py-2.5 transition-colors duration-150 hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                            >
                                <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                <span className="min-w-0 flex-1">
                                    <span className="flex items-center justify-between gap-2 text-xs font-medium">
                                        <span>{name}</span>
                                        <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" aria-hidden="true" />
                                    </span>
                                    <span className="mt-0.5 block text-[11px] leading-4 text-muted-foreground">{description}</span>
                                </span>
                            </a>
                        )
                    })}
                </div>
            </DialogContent>
        </Dialog>
    )
}
