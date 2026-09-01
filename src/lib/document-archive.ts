export interface DocumentArchiveMetadata {
    description?: string | null
    markdownContent?: string | null
    author?: string | null
    publishedAt?: string | null
    sourceUrl?: string | null
}

export interface ArchiveImageFile {
    sourceUrl: string
    filename: string
}

function replaceAllLiteral(value: string, search: string, replacement: string): string {
    if (!search) return value
    return value.split(search).join(replacement)
}

export function localizeMarkdownImages(markdown: string, images: ArchiveImageFile[]): string {
    let localized = markdown
    for (const image of images) {
        const relative = `./${image.filename}`
        localized = replaceAllLiteral(localized, image.sourceUrl, relative)
        try {
            const decoded = decodeURIComponent(image.sourceUrl)
            if (decoded !== image.sourceUrl) localized = replaceAllLiteral(localized, decoded, relative)
        } catch {
            // Keep the exact source URL replacement when percent encoding is malformed.
        }
    }
    return localized
}

function metadataLines(title: string, metadata: DocumentArchiveMetadata): string[] {
    return [
        `# ${title.trim()}`,
        '',
        metadata.author ? `- Author: ${metadata.author}` : '',
        metadata.publishedAt ? `- Published: ${metadata.publishedAt}` : '',
        metadata.sourceUrl ? `- Source: ${metadata.sourceUrl}` : '',
        '',
    ]
}

function compactBlankLines(lines: string[]): string[] {
    const output: string[] = []
    for (const line of lines) {
        if (!line && output[output.length - 1] === '') continue
        output.push(line)
    }
    while (output[output.length - 1] === '') output.pop()
    return output
}

export function buildDocumentArchiveMarkdown(
    title: string,
    metadata: DocumentArchiveMetadata,
    images: ArchiveImageFile[],
): string {
    const structured = metadata.markdownContent?.trim()
    if (structured) {
        const localized = localizeMarkdownImages(structured, images)
        return `${compactBlankLines([
            ...metadataLines(title, metadata),
            localized,
        ]).join('\n').trim()}\n`
    }

    const fallbackImages = images.flatMap((image, index) => [
        `![${index + 1}](./${image.filename})`,
        '',
    ])
    return `${compactBlankLines([
        ...metadataLines(title, metadata),
        metadata.description?.trim() || '',
        '',
        ...fallbackImages,
    ]).join('\n').trim()}\n`
}
