import { describe, expect, it } from 'vitest'

import { buildDocumentArchiveMarkdown, localizeMarkdownImages } from '@/lib/document-archive'

describe('document archive Markdown', () => {
    it('rewrites structured Markdown images to downloaded ZIP files in place', () => {
        const source = [
            '第一段。',
            '',
            '![步骤图](https://mmbiz.qpic.cn/photo/0)',
            '',
            '第二段。',
        ].join('\n')
        const markdown = buildDocumentArchiveMarkdown(
            '测试文章',
            {
                markdownContent: source,
                author: 'Galaxy',
                sourceUrl: 'https://mp.weixin.qq.com/s/demo',
            },
            [{ sourceUrl: 'https://mmbiz.qpic.cn/photo/0', filename: '测试文章-1.jpg' }],
        )

        expect(markdown).toContain('# 测试文章')
        expect(markdown).toContain('![步骤图](./测试文章-1.jpg)')
        expect(markdown).not.toContain('https://mmbiz.qpic.cn/photo/0')
        expect(markdown.indexOf('第一段')).toBeLessThan(markdown.indexOf('![步骤图]'))
        expect(markdown.indexOf('![步骤图]')).toBeLessThan(markdown.indexOf('第二段'))
    })

    it('keeps fallback gallery archives when structured Markdown is unavailable', () => {
        const markdown = buildDocumentArchiveMarkdown(
            'Gallery',
            { description: 'Caption' },
            [
                { sourceUrl: 'https://cdn.example/a.jpg', filename: 'Gallery-1.jpg' },
                { sourceUrl: 'https://cdn.example/b.jpg', filename: 'Gallery-2.jpg' },
            ],
        )
        expect(markdown).toContain('Caption')
        expect(markdown).toContain('![1](./Gallery-1.jpg)')
        expect(markdown).toContain('![2](./Gallery-2.jpg)')
    })

    it('only rewrites matching image URLs', () => {
        const markdown = localizeMarkdownImages(
            '![a](https://cdn.example/a.jpg)\n![b](https://cdn.example/b.jpg)',
            [{ sourceUrl: 'https://cdn.example/a.jpg', filename: 'a.jpg' }],
        )
        expect(markdown).toContain('![a](./a.jpg)')
        expect(markdown).toContain('![b](https://cdn.example/b.jpg)')
    })
})
