'use client'

import { useState } from 'react'
import dynamic from 'next/dynamic'
import { ScrollText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useDictionary } from '@/i18n/client'

const ChangelogDialog = dynamic(
    () => import('@/components/changelog-dialog').then((m) => m.ChangelogDialog),
    { ssr: false }
)

interface DeferredChangelogDialogProps {
    triggerClassName?: string
    triggerIconOnly?: boolean
}

export function DeferredChangelogDialog({
    triggerClassName,
    triggerIconOnly = false,
}: DeferredChangelogDialogProps) {
    const dict = useDictionary()
    const [mounted, setMounted] = useState(false)
    const title = dict.changelog.title

    if (mounted) {
        return (
            <ChangelogDialog
                triggerClassName={triggerClassName}
                triggerIconOnly={triggerIconOnly}
                defaultOpen
            />
        )
    }

    return (
        <Button
            variant="ghost"
            size={triggerIconOnly ? 'icon' : 'sm'}
            className={cn('min-h-10 text-sm', triggerIconOnly && 'h-10 w-10', triggerClassName)}
            onClick={() => setMounted(true)}
            aria-label={title}
        >
            <ScrollText className={cn('h-4 w-4', !triggerIconOnly && 'me-1')} aria-hidden="true" />
            {triggerIconOnly ? <span className="sr-only">{title}</span> : title}
        </Button>
    )
}
