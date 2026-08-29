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
                    className={cn('text-sm', triggerClassName)}
                    onClick={onTriggerClick}
                    aria-label={title}
                >
                    <ScrollText className={cn('h-4 w-4', !triggerIconOnly && 'mr-1')} />
                    {triggerIconOnly ? <span className="sr-only">{title}</span> : title}
                </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                <ScrollArea className="max-h-[60vh] pr-2">
                    <div className="space-y-6">
                        {versions.map((version) => (
                            <div key={version.version} className="border-b border-border pb-4 last:border-b-0 last:pb-0">
                                <div className="flex items-center justify-between mb-3">
                                    <span className="font-semibold">v{version.version}</span>
                                    <span className="text-sm text-muted-foreground">{version.date}</span>
                                </div>
                                <ul className="space-y-2 pl-1">
                                    {getChanges(version.changes).map((change, index) => (
                                        <li key={index} className="text-sm text-muted-foreground flex items-start gap-2">
                                            <span className="text-primary shrink-0">•</span>
                                            <span>{change}</span>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
            </DialogContent>
        </Dialog>
    )
}
