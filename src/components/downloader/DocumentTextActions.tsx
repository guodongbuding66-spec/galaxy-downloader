'use client'

import { useState } from 'react'
import { Copy, Download, FileText } from 'lucide-react'
import { usePathname } from 'next/navigation'

import { Button } from '@/components/ui/button'
import { toast } from '@/lib/deferred-toast'
import { sanitizeFilename } from '@/lib/utils'

const COPY: Record<string, { label: string; copy: string; download: string; copied: string }> = {
    zh: { label: '文案 / 正文', copy: '复制文案', download: '下载文本', copied: '已复制文案' },
    'zh-tw': { label: '文案 / 正文', copy: '複製文案', download: '下載文字', copied: '已複製文案' },
    en: { label: 'Post / article text', copy: 'Copy text', download: 'Download text', copied: 'Text copied' },
    ja: { label: '投稿 / 記事テキスト', copy: 'テキストをコピー', download: 'テキストを保存', copied: 'コピーしました' },
    es: { label: 'Texto de la publicación', copy: 'Copiar texto', download: 'Descargar texto', copied: 'Texto copiado' },
    ru: { label: 'Текст публикации', copy: 'Копировать текст', download: 'Скачать текст', copied: 'Текст скопирован' },
}

function triggerTextDownload(text: string, filename: string) {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    anchor.style.display = 'none'
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function DocumentTextActions({
    title,
    text,
    author,
    publishedAt,
    sourceUrl,
}: {
    title: string
    text?: string | null
    author?: string | null
    publishedAt?: string | null
    sourceUrl?: string | null
}) {
    const pathname = usePathname()
    const locale = pathname.split('/').filter(Boolean)[0] || 'en'
    const copy = COPY[locale] || COPY.en
    const [expanded, setExpanded] = useState(false)
    const cleanedText = text?.trim() || ''
    if (!cleanedText) return null

    const exportText = [
        title.trim(),
        author ? `Author: ${author}` : '',
        publishedAt ? `Published: ${publishedAt}` : '',
        sourceUrl ? `Source: ${sourceUrl}` : '',
        '',
        cleanedText,
    ].filter((line, index, all) => line || (index > 0 && all[index - 1])).join('\n')

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(cleanedText)
            toast.success(copy.copied)
        } catch {
            const textarea = document.createElement('textarea')
            textarea.value = cleanedText
            textarea.style.position = 'fixed'
            textarea.style.opacity = '0'
            document.body.appendChild(textarea)
            textarea.select()
            document.execCommand('copy')
            textarea.remove()
            toast.success(copy.copied)
        }
    }

    return (
        <div className="border-y py-2">
            <div className="flex items-center gap-2">
                <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                <button
                    type="button"
                    className="min-w-0 flex-1 text-left text-xs font-medium"
                    onClick={() => setExpanded((value) => !value)}
                    aria-expanded={expanded}
                >
                    {copy.label}
                </button>
                <Button type="button" variant="ghost" size="xs" onClick={() => void handleCopy()}>
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="hidden sm:inline">{copy.copy}</span>
                </Button>
                <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    onClick={() => triggerTextDownload(exportText, `${sanitizeFilename(title)}.txt`)}
                >
                    <Download className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="hidden sm:inline">{copy.download}</span>
                </Button>
            </div>
            <p className={`${expanded ? 'max-h-80 overflow-y-auto whitespace-pre-wrap' : 'line-clamp-3'} mt-2 text-xs leading-5 text-muted-foreground`}>
                {cleanedText}
            </p>
        </div>
    )
}
