function decodeEntities(value: string): string {
    return value
        .replace(/&amp;/gi, '&')
        .replace(/&quot;/gi, '"')
        .replace(/&#39;|&apos;/gi, "'")
        .replace(/&lt;/gi, '<')
        .replace(/&gt;/gi, '>')
        .replace(/&nbsp;/gi, ' ')
        .replace(/&#(\d+);/g, (_, raw: string) => String.fromCodePoint(Number(raw) || 32))
        .replace(/&#x([0-9a-f]+);/gi, (_, raw: string) => String.fromCodePoint(Number.parseInt(raw, 16) || 32))
}

function attrs(tag: string): Record<string, string> {
    const output: Record<string, string> = {}
    const re = /([:\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g
    for (const match of tag.matchAll(re)) {
        output[match[1]!.toLowerCase()] = decodeEntities(match[2] ?? match[3] ?? match[4] ?? '')
    }
    return output
}

function absoluteUrl(raw: string | undefined, base: URL): string | null {
    if (!raw) return null
    const value = decodeEntities(raw).trim().replace(/\\\//g, '/')
    if (!value || /^(?:data|blob|javascript):/i.test(value)) return null
    try {
        const parsed = new URL(value, base)
        return /^https?:$/.test(parsed.protocol) ? parsed.toString() : null
    } catch {
        return null
    }
}

function plainText(value: string): string {
    return decodeEntities(value)
        .replace(/<br\s*\/?\s*>/gi, '\n')
        .replace(/<[^>]+>/g, ' ')
        .replace(/[\t\f\v ]+/g, ' ')
        .replace(/\s*\n\s*/g, '\n')
        .trim()
}

function escapeTableCell(value: string): string {
    return value.replace(/\|/g, '\\|').replace(/\s*\n\s*/g, '<br>')
}

function tableToMarkdown(tableHtml: string): string {
    const rows: string[][] = []
    for (const rowMatch of tableHtml.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
        const cells: string[] = []
        for (const cellMatch of rowMatch[1]!.matchAll(/<(?:th|td)\b[^>]*>([\s\S]*?)<\/(?:th|td)>/gi)) {
            cells.push(escapeTableCell(plainText(cellMatch[1] || '')))
        }
        if (cells.length) rows.push(cells)
    }
    if (!rows.length) return plainText(tableHtml)
    const width = Math.max(...rows.map((row) => row.length))
    const normalized = rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill('')])
    const lines = [
        `| ${normalized[0]!.join(' | ')} |`,
        `| ${Array(width).fill('---').join(' | ')} |`,
        ...normalized.slice(1).map((row) => `| ${row.join(' | ')} |`),
    ]
    return `\n\n${lines.join('\n')}\n\n`
}

function wechatArticleFragment(html: string): string {
    const marker = html.search(/\bid=["']js_content["']/i)
    if (marker < 0) return ''
    const start = html.lastIndexOf('<', marker)
    if (start < 0) return ''
    const tail = html.slice(start)
    const endCandidates = [
        tail.search(/\bid=["']js_toobar3["']/i),
        tail.search(/\bclass=["'][^"']*rich_media_tool/i),
        tail.search(/<script\b/i),
    ].filter((value) => value > 0)
    const end = endCandidates.length ? Math.min(...endCandidates) : Math.min(tail.length, 2_000_000)
    return tail.slice(0, end)
}

export function htmlFragmentToMarkdown(fragment: string, sourceUrl: string): string {
    if (!fragment.trim()) return ''
    let base: URL
    try {
        base = new URL(sourceUrl)
    } catch {
        return ''
    }

    let value = fragment
        .replace(/<(?:script|style|noscript)\b[^>]*>[\s\S]*?<\/(?:script|style|noscript)>/gi, '')
        .replace(/<table\b[^>]*>[\s\S]*?<\/table>/gi, (table) => tableToMarkdown(table))
        .replace(/<pre\b[^>]*>([\s\S]*?)<\/pre>/gi, (_, body: string) => `\n\n\`\`\`\n${decodeEntities(body).replace(/<[^>]+>/g, '').trim()}\n\`\`\`\n\n`)
        .replace(/<img\b[^>]*>/gi, (tag) => {
            const map = attrs(tag)
            const raw = map['data-src'] || map['data-original'] || map['data-lazy-src'] || map['data-actualsrc'] || map.src
            const url = absoluteUrl(raw, base)
            if (!url) return ''
            const alt = plainText(map.alt || map.title || 'image').replace(/[\[\]]/g, '') || 'image'
            return `\n\n![${alt}](${url})\n\n`
        })
        .replace(/<a\b[^>]*>[\s\S]*?<\/a>/gi, (tag) => {
            const open = tag.match(/^<a\b[^>]*>/i)?.[0] || ''
            const map = attrs(open)
            const text = plainText(tag.replace(/^<a\b[^>]*>/i, '').replace(/<\/a>$/i, '')) || map.title || map.href || 'link'
            const url = absoluteUrl(map.href, base)
            return url ? `[${text.replace(/[\[\]]/g, '')}](${url})` : text
        })
        .replace(/<h1\b[^>]*>([\s\S]*?)<\/h1>/gi, (_, body: string) => `\n\n# ${plainText(body)}\n\n`)
        .replace(/<h2\b[^>]*>([\s\S]*?)<\/h2>/gi, (_, body: string) => `\n\n## ${plainText(body)}\n\n`)
        .replace(/<h3\b[^>]*>([\s\S]*?)<\/h3>/gi, (_, body: string) => `\n\n### ${plainText(body)}\n\n`)
        .replace(/<h[4-6]\b[^>]*>([\s\S]*?)<\/h[4-6]>/gi, (_, body: string) => `\n\n#### ${plainText(body)}\n\n`)
        .replace(/<blockquote\b[^>]*>([\s\S]*?)<\/blockquote>/gi, (_, body: string) => {
            const text = plainText(body)
            return `\n\n${text.split('\n').map((line) => `> ${line}`).join('\n')}\n\n`
        })
        .replace(/<li\b[^>]*>([\s\S]*?)<\/li>/gi, (_, body: string) => `\n- ${plainText(body)}`)
        .replace(/<(?:strong|b)\b[^>]*>([\s\S]*?)<\/(?:strong|b)>/gi, (_, body: string) => `**${plainText(body)}**`)
        .replace(/<(?:em|i)\b[^>]*>([\s\S]*?)<\/(?:em|i)>/gi, (_, body: string) => `*${plainText(body)}*`)
        .replace(/<code\b[^>]*>([\s\S]*?)<\/code>/gi, (_, body: string) => `\`${plainText(body).replace(/`/g, '\\`')}\``)
        .replace(/<br\s*\/?\s*>/gi, '\n')
        .replace(/<\/(?:p|div|section|article|ul|ol)>/gi, '\n\n')
        .replace(/<(?:p|div|section|article|ul|ol)\b[^>]*>/gi, '')
        .replace(/<[^>]+>/g, '')

    value = decodeEntities(value)
        .replace(/\r/g, '')
        .replace(/[\t\f\v ]+\n/g, '\n')
        .replace(/\n[\t\f\v ]+/g, '\n')
        .replace(/\n{3,}/g, '\n\n')
        .trim()

    return value ? `${value}\n` : ''
}

export function extractDocumentMarkdown(sourceUrl: string, html: string, platform: string): string {
    if (platform !== 'wechat') return ''
    return htmlFragmentToMarkdown(wechatArticleFragment(html), sourceUrl)
}
