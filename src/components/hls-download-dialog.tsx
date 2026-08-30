'use client'

import { useCallback, useState } from 'react'

import { HlsBrowserDownloadPanel } from '@/components/hls-browser-download-panel'
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { useDictionary } from '@/i18n/client'

export interface HlsDownloadDialogRequest {
    sourceUrl: string
    resolvedPlaylistUrl?: string
    title?: string
}

interface HlsDownloadDialogProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    request: HlsDownloadDialogRequest | null
}

export function HlsDownloadDialog({
    open,
    onOpenChange,
    request,
}: HlsDownloadDialogProps) {
    const dict = useDictionary()
    const [isBusy, setIsBusy] = useState(false)
    const [confirmCloseOpen, setConfirmCloseOpen] = useState(false)
    const [cancelDownload, setCancelDownload] = useState<(() => void) | null>(null)

    const closeAndCancel = useCallback(() => {
        cancelDownload?.()
        onOpenChange(false)
    }, [cancelDownload, onOpenChange])

    const handleOpenChange = useCallback((nextOpen: boolean) => {
        if (!nextOpen && isBusy) {
            setConfirmCloseOpen(true)
            return
        }

        if (!nextOpen) {
            closeAndCancel()
            return
        }

        onOpenChange(true)
    }, [closeAndCancel, isBusy, onOpenChange])

    const handleConfirmClose = useCallback(() => {
        setConfirmCloseOpen(false)
        closeAndCancel()
    }, [closeAndCancel])

    if (!request) {
        return null
    }

    return (
        <>
            <Dialog open={open} onOpenChange={handleOpenChange}>
                <DialogContent
                    className="flex max-h-[calc(100dvh-1rem)] max-w-[calc(100vw-1rem)] flex-col overflow-hidden rounded-xl p-4 sm:max-h-[90dvh] sm:max-w-2xl sm:p-6"
                    onInteractOutside={(event) => {
                        event.preventDefault()
                    }}
                >
                    <DialogHeader className="pe-8">
                        <DialogTitle>{dict.result.browserDownloadVideo}</DialogTitle>
                        <DialogDescription className="leading-5">{dict.hlsDownload.description}</DialogDescription>
                    </DialogHeader>

                    <div
                        className="min-h-0 flex-1 overflow-y-auto pe-1"
                        style={{ paddingBottom: 'max(env(safe-area-inset-bottom), 0px)' }}
                    >
                        <HlsBrowserDownloadPanel
                            initialSourceUrl={request.sourceUrl}
                            initialResolvedPlaylistUrl={request.resolvedPlaylistUrl}
                            initialTitle={request.title}
                            onBusyChange={setIsBusy}
                            onCancelReady={setCancelDownload}
                        />
                    </div>
                </DialogContent>
            </Dialog>

            <AlertDialog open={confirmCloseOpen} onOpenChange={setConfirmCloseOpen}>
                <AlertDialogContent className="max-w-[calc(100vw-1rem)] rounded-xl sm:max-w-md">
                    <AlertDialogHeader>
                        <AlertDialogTitle>{dict.hlsDownload.confirmCloseTitle}</AlertDialogTitle>
                        <AlertDialogDescription className="leading-5">{dict.hlsDownload.confirmCloseDescription}</AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel className="min-h-10">{dict.errors.cancel}</AlertDialogCancel>
                        <AlertDialogAction className="min-h-10" onClick={handleConfirmClose}>
                            {dict.hlsDownload.confirmCloseAction}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    )
}
