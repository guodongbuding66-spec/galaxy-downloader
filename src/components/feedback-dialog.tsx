'use client'

import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from '@/components/ui/dialog'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { MessageSquare, Loader2, CheckCircle2 } from 'lucide-react'
import { toast } from '@/lib/deferred-toast'
import { useDictionary } from '@/i18n/client'
import type { FeedbackType } from '@/lib/feedback-config'
import { collectFeedbackClientMetadata, submitFeedback, validateContent, validateEmail } from '@/lib/feedback'
import { FEEDBACK_CONFIG } from '@/lib/feedback-config'
import { cn } from '@/lib/utils'
import { isApiRequestError, resolveApiErrorMessageWithFallback } from '@/lib/api-errors'

interface FeedbackDialogProps {
    triggerClassName?: string
    triggerIconOnly?: boolean
    triggerLabel?: string
    defaultOpen?: boolean
    onTriggerClick?: () => void
}

export function FeedbackDialog({
    triggerClassName,
    triggerIconOnly = false,
    triggerLabel: triggerLabelOverride,
    defaultOpen = false,
    onTriggerClick,
}: FeedbackDialogProps) {
    const dict = useDictionary()
    const feedback = dict.feedback
    const triggerLabel = triggerLabelOverride ?? feedback.triggerButton
    const [open, setOpen] = useState(defaultOpen)
    const [feedbackType, setFeedbackType] = useState<FeedbackType>('bug')
    const [content, setContent] = useState('')
    const [email, setEmail] = useState('')
    const [isSubmitting, setIsSubmitting] = useState(false)
    const [submitStatus, setSubmitStatus] = useState<'idle' | 'success' | 'error'>('idle')

    const contentLength = content.length
    const maxLength = FEEDBACK_CONFIG.validation.contentMaxLength

    const contentError = content ? validateContent(content) : null
    const emailError = email ? !validateEmail(email) : null
    const canSubmit = !contentError && !emailError && content.trim().length >= FEEDBACK_CONFIG.validation.contentMinLength
    const contentTooShortMessage = feedback.contentTooShort.replace('{min}', String(FEEDBACK_CONFIG.validation.contentMinLength))
    const contentCounterText = feedback.contentCounter
        .replace('{current}', String(contentLength))
        .replace('{max}', String(maxLength))

    const getPlaceholder = () => {
        return feedback.contentPlaceholder[feedbackType] || feedback.contentPlaceholder.other || ''
    }

    const resetForm = () => {
        setFeedbackType('bug')
        setContent('')
        setEmail('')
        setSubmitStatus('idle')
    }

    useEffect(() => {
        if (!open) {
            const timer = setTimeout(resetForm, 200)
            return () => clearTimeout(timer)
        }
    }, [open])

    const handleSubmit = async () => {
        if (!canSubmit) return

        setIsSubmitting(true)

        try {
            await submitFeedback({
                type: feedbackType,
                content: content.trim(),
                contact: email.trim(),
                metadata: collectFeedbackClientMetadata(),
            })

            setSubmitStatus('success')
            toast.success(feedback.toastSuccess)

            setTimeout(() => {
                setOpen(false)
            }, 3000)
        } catch (error) {
            if (isApiRequestError(error)) {
                console.error('Feedback submit failed', {
                    code: error.code,
                    status: error.status,
                    requestId: error.requestId,
                    details: error.details,
                })
            } else {
                console.error('Submit error:', error)
            }

            const errorMessage = resolveApiErrorMessageWithFallback(error, dict, feedback.errorMessage)
            setSubmitStatus('error')
            toast.error(feedback.toastError, {
                description: errorMessage,
            })
        } finally {
            setIsSubmitting(false)
        }
    }

    const renderSuccess = () => (
        <div className="space-y-4 py-8 text-center" role="status" aria-live="polite">
            <div className="flex justify-center">
                <CheckCircle2 className="h-16 w-16 text-green-500" aria-hidden="true" />
            </div>
            <div className="space-y-2">
                <h3 className="text-lg font-semibold">
                    {feedback.successTitle}
                </h3>
                <p className="text-sm leading-5 text-muted-foreground">
                    {feedback.successMessage}
                </p>
                {email && (
                    <p className="text-xs leading-5 text-muted-foreground">
                        {feedback.successNote}
                    </p>
                )}
            </div>
            <Button onClick={() => setOpen(false)} className="mt-4 min-h-11 w-full sm:w-auto">
                {feedback.closeButton}
            </Button>
        </div>
    )

    const renderForm = () => (
        <div className="space-y-5">
            <div className="space-y-2">
                <Label htmlFor="feedback-type">
                    {feedback.typeLabel} <span className="text-red-500" aria-hidden="true">*</span>
                </Label>
                <Select value={feedbackType} onValueChange={(value) => setFeedbackType(value as FeedbackType)}>
                    <SelectTrigger id="feedback-type" className="h-11 sm:h-10">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="bug">
                            {feedback.types.bug}
                        </SelectItem>
                        <SelectItem value="feature">
                            {feedback.types.feature}
                        </SelectItem>
                        <SelectItem value="other">
                            {feedback.types.other}
                        </SelectItem>
                    </SelectContent>
                </Select>
            </div>

            <div className="space-y-2">
                <Label htmlFor="feedback-content">
                    {feedback.contentLabel} <span className="text-red-500" aria-hidden="true">*</span>
                </Label>
                <Textarea
                    id="feedback-content"
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    placeholder={getPlaceholder()}
                    rows={5}
                    className="min-h-32 resize-none text-base sm:text-sm"
                    maxLength={maxLength}
                    aria-invalid={Boolean(contentError)}
                    aria-describedby="feedback-content-meta"
                />
                <div id="feedback-content-meta" className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span className={contentError ? 'text-red-500' : 'text-muted-foreground'}>
                        {contentError === 'contentRequired' && feedback.contentRequired}
                        {contentError === 'contentTooShort' && contentTooShortMessage}
                    </span>
                    <span className={contentLength > maxLength * 0.9 ? 'text-yellow-500' : 'text-muted-foreground'}>
                        {contentCounterText}
                    </span>
                </div>
            </div>

            <div className="space-y-2">
                <Label htmlFor="feedback-email">
                    {feedback.emailLabel}
                </Label>
                <Input
                    id="feedback-email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder={feedback.emailPlaceholder}
                    className="h-11 text-base sm:h-10 sm:text-sm"
                    aria-invalid={Boolean(emailError)}
                    aria-describedby="feedback-email-help"
                />
                <div id="feedback-email-help">
                    {emailError && (
                        <p className="text-xs leading-5 text-red-500">
                            {feedback.emailInvalid}
                        </p>
                    )}
                    {!email && !emailError && (
                        <p className="text-xs leading-5 text-muted-foreground">
                            {feedback.emailRequired}
                        </p>
                    )}
                </div>
            </div>

            <p className="text-xs leading-5 text-muted-foreground">
                {feedback.diagnosticInfoHint}
            </p>

            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
                <Button
                    variant="ghost"
                    className="min-h-11 sm:min-h-10"
                    onClick={() => setOpen(false)}
                    disabled={isSubmitting}
                >
                    {feedback.cancelButton}
                </Button>
                <Button
                    className="min-h-11 sm:min-h-10"
                    onClick={handleSubmit}
                    disabled={!canSubmit || isSubmitting}
                >
                    {isSubmitting ? (
                        <>
                            <Loader2 className="me-2 h-4 w-4 animate-spin" aria-hidden="true" />
                            {feedback.submittingButton}
                        </>
                    ) : (
                        feedback.submitButton
                    )}
                </Button>
            </div>
        </div>
    )

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button
                    variant="ghost"
                    size={triggerIconOnly ? 'icon' : 'sm'}
                    className={cn('min-h-10 text-sm', triggerIconOnly && 'h-10 w-10', triggerClassName)}
                    onClick={onTriggerClick}
                    aria-label={triggerLabel}
                >
                    <MessageSquare className={cn('h-4 w-4', !triggerIconOnly && 'me-1')} aria-hidden="true" />
                    {triggerIconOnly ? (
                        <span className="sr-only">{triggerLabel}</span>
                    ) : (
                        triggerLabel
                    )}
                </Button>
            </DialogTrigger>
            <DialogContent
                className="max-h-[calc(100dvh-1rem)] max-w-[calc(100vw-1rem)] overflow-y-auto rounded-xl p-4 sm:max-h-[90dvh] sm:max-w-lg sm:p-6"
                onInteractOutside={(event) => event.preventDefault()}
            >
                <DialogHeader className="pe-8">
                    <DialogTitle>
                        {feedback.title}
                    </DialogTitle>
                </DialogHeader>
                {submitStatus === 'success' ? renderSuccess() : renderForm()}
            </DialogContent>
        </Dialog>
    )
}
