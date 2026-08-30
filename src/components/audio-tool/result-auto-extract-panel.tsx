'use client'

import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { useDictionary } from '@/i18n/client'

import type { AudioExtractTask, AudioToolStage } from './types'

interface ResultAutoExtractPanelProps {
    task: AudioExtractTask
    stage: AudioToolStage
    isBusy: boolean
    statusPanel: ReactNode
    onRetry: () => void
}

export function ResultAutoExtractPanel({
    task,
    stage,
    isBusy,
    statusPanel,
    onRetry,
}: ResultAutoExtractPanelProps) {
    const dict = useDictionary()

    return (
        <div className="space-y-4">
            <div className="rounded-xl border bg-muted/20 px-3 py-2.5 text-xs leading-5 text-muted-foreground break-all">
                {task.sourceUrl || task.videoUrl || task.audioUrl}
            </div>

            {stage === 'error' && (
                <Button
                    type="button"
                    variant="outline"
                    className="min-h-11 w-full"
                    onClick={onRetry}
                    disabled={isBusy}
                >
                    {dict.extractAudio.retry}
                </Button>
            )}

            {statusPanel}
        </div>
    )
}
