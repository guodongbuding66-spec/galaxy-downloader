'use client'

import type { ChangeEvent, DragEvent } from 'react'

import { FileX, Upload } from 'lucide-react'

import { Button, buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface FileDropzoneProps {
    acceptedFile: File | null
    title: string
    hint: string
    limitText: string
    emptyButtonLabel: string
    clearButtonLabel: string
    selectedLabel: string
    inputId: string
    accept: string
    isBusy: boolean
    onSelect: (event: ChangeEvent<HTMLInputElement>) => void
    onDrop: (event: DragEvent<HTMLDivElement>) => void
    onDragOver: (event: DragEvent<HTMLDivElement>) => void
    onClear: () => void
}

export function FileDropzone({
    acceptedFile,
    title,
    hint,
    limitText,
    emptyButtonLabel,
    clearButtonLabel,
    selectedLabel,
    inputId,
    accept,
    isBusy,
    onSelect,
    onDrop,
    onDragOver,
    onClear,
}: FileDropzoneProps) {
    return (
        <div
            className={cn(
                'space-y-4 rounded-xl border-2 border-dashed p-4 text-center transition-colors sm:p-5',
                acceptedFile ? 'border-muted bg-muted/20' : 'border-muted-foreground/30 hover:border-muted-foreground/50'
            )}
            onDrop={onDrop}
            onDragOver={onDragOver}
        >
            <div className="space-y-1.5">
                <div className="text-sm font-medium">{title}</div>
                <div className="text-xs leading-5 text-muted-foreground">{hint}</div>
                <div className="text-xs leading-5 text-muted-foreground/80">{limitText}</div>
            </div>

            <input
                id={inputId}
                type="file"
                accept={accept}
                onChange={onSelect}
                disabled={isBusy}
                className="sr-only"
            />

            {acceptedFile ? (
                <div className="space-y-3">
                    <p className="break-all text-sm font-medium leading-5">{selectedLabel}</p>
                    <div className="flex flex-wrap justify-center gap-2">
                        <label
                            htmlFor={inputId}
                            aria-disabled={isBusy}
                            className={cn(
                                buttonVariants({ variant: 'outline', size: 'sm' }),
                                'min-h-10 cursor-pointer px-4',
                                isBusy && 'pointer-events-none opacity-50'
                            )}
                        >
                            {emptyButtonLabel}
                        </label>
                        <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={onClear}
                            disabled={isBusy}
                            className="h-10 w-10"
                            aria-label={clearButtonLabel}
                            title={clearButtonLabel}
                        >
                            <FileX className="h-4 w-4" aria-hidden="true" />
                        </Button>
                    </div>
                </div>
            ) : (
                <div className="space-y-3 py-2">
                    <Upload className="mx-auto h-8 w-8 text-muted-foreground/60" aria-hidden="true" />
                    <label
                        htmlFor={inputId}
                        aria-disabled={isBusy}
                        className={cn(
                            buttonVariants({ variant: 'outline', size: 'sm' }),
                            'min-h-10 cursor-pointer px-4',
                            isBusy && 'pointer-events-none opacity-50'
                        )}
                    >
                        {emptyButtonLabel}
                    </label>
                </div>
            )}
        </div>
    )
}
