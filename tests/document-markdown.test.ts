import { describe, expect, it } from 'vitest'

import { extractDocumentMarkdown, htmlFragmentToMarkdown } from '@/lib/document-markdown'

describe('document Markdown extraction', () => {
    it('keeps WeChat article structure and media order', () => {
        const html = `
          <html><body>
            <div id="js_content">
              <h2>安装步骤</h2>
              <p>第一段，<strong>重点内容</strong>。</p>
              <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/demo/photo1/0" alt="步骤图">
              <blockquote>注意安装方向。</blockquote>
              <p>访问 <a href="https://example.com/guide">完整指南</a>。</p>
              <table>
                <tr><th>规格</th><th>数值</th></tr>
                <tr><td>宽度</td><td>120 cm</td></tr>
              </table>
              <pre>npm run build</pre>
            </div>
            <div id="js_toobar3">toolbar</div>
          </body></html>`

        const markdown = extractDocumentMarkdown('https://mp.weixin.qq.com/s/demo', html, 'wechat')
        expect(markdown).toContain('## 安装步骤')
        expect(markdown).toContain('**重点内容**')
        expect(markdown).toContain('![步骤图](https://mmbiz.qpic.cn/mmbiz_jpg/demo/photo1/0)')
        expect(markdown).toContain('> 注意安装方向。')
        expect(markdown).toContain('[完整指南](https://example.com/guide)')
        expect(markdown).toContain('| 规格 | 数值 |')
        expect(markdown).toContain('| 宽度 | 120 cm |')
        expect(markdown).toContain('```\nnpm run build\n```')

        expect(markdown.indexOf('第一段')).toBeLessThan(markdown.indexOf('![步骤图]'))
        expect(markdown.indexOf('![步骤图]')).toBeLessThan(markdown.indexOf('注意安装方向'))
        expect(markdown).not.toContain('toolbar')
    })

    it('resolves relative image and link URLs', () => {
        const markdown = htmlFragmentToMarkdown(
            '<p>Read <a href="/help">help</a></p><img src="/image.jpg">',
            'https://example.com/article/1',
        )
        expect(markdown).toContain('[help](https://example.com/help)')
        expect(markdown).toContain('![image](https://example.com/image.jpg)')
    })

    it('does not create structured Markdown for unrelated platforms', () => {
        expect(extractDocumentMarkdown('https://example.com', '<article>Hello</article>', 'generic')).toBe('')
    })
})
