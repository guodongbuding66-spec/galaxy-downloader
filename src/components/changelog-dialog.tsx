'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog'
import { ScrollText } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import changelogData from '@/lib/changelog.json'
import latestChangelogData from '@/lib/changelog-latest.json'
import workbenchChangelogData from '@/lib/changelog-workbench.json'
import { useAppLocale, useDictionary } from '@/i18n/client'
import { cn } from '@/lib/utils'

interface ChangelogDialogProps {
    triggerClassName?: string
    triggerIconOnly?: boolean
    defaultOpen?: boolean
    onTriggerClick?: () => void
}

export function ChangelogDialog({
    triggerClassName,
    triggerIconOnly = false,
    defaultOpen = false,
    onTriggerClick,
}: ChangelogDialogProps) {
    const locale = useAppLocale()
    const dict = useDictionary()
    const [open, setOpen] = useState(defaultOpen)

    const getChanges = (changes: Record<string, string[]>) => {
        return changes[locale] || changes['en'] || []
    }

    const title = dict.changelog.title
    const versions = [
        ...workbenchChangelogData.versions,
        ...latestChangelogData.versions,
        ...changelogData.versions,
    ]

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button
                    variant="ghost"
                    size={triggerIconOnly ? 'icon' : 'sm'}
                    className={cn('min-h-10 text-sm', triggerIconOnly && 'h-10 w-10', triggerClassName)}
                    onClick={onTriggerClick}
                    aria-label={title}
                >
                    <ScrollText className={cn('h-4 w-4', !triggerIconOnly && 'me-1')} aria-hidden="true" />
                    {triggerIconOnly ? <span className="sr-only">{title}</span> : title}
                </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[calc(100dvh-1rem)] max-w-[calc(100vw-1rem)] rounded-xl p-4 sm:max-h-[85dvh] sm:max-w-md sm:p-6">
                <DialogHeader className="pe-8">
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <ScrollArea className="max-h-[calc(100dvh-6rem)] pe-2 sm:max-h-[70dvh]">
                    <div className="space-y-6">
                        {versions.map((version) => (
                            <section key={version.version} className="border-b border-border pb-4 last:border-b-0 last:pb-0">
                                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                                    <span className="font-semibold">v{version.version}</span>
                                    <time className="text-sm text-muted-foreground">{version.date}</time>
                                </div>
                                <ul className="space-y-2 ps-1">
                                    {getChanges(version.changes).map((change, index) => (
                                        <li key={index} className="flex items-start gap-2 text-sm leading-5 text-muted-foreground">
                                            <span className="shrink-0 text-primary" aria-hidden="true">•</span>
                                            <span className="break-words">{change}</span>
                                        </li>
                                    ))}
                                </ul>
                            </section>
                        ))}
                    </div>
                </ScrollArea>
            </DialogContent>
        </Dialog>
    )
}
