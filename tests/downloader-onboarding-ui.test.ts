import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8')
}

describe('downloader Local Engine onboarding UI', () => {
  it('puts the Local Engine prerequisite in the main page description', () => {
    const downloader = source('src/app/[locale]/unified-downloader.tsx')
    expect(downloader).toContain('首次使用请先下载并打开 Galaxy Local Engine，再粘贴链接解析')
  })

  it('shows an explicit clear-link action next to parse instead of only an icon in the input', () => {
    const downloader = source('src/app/[locale]/unified-downloader.tsx')
    expect(downloader).toContain("clearInput: '清空链接'")
    expect(downloader).toContain('{workbenchCopy.clearInput}')
    expect(downloader).toContain("variant=\"outline\"")
  })

  it('uses a four-step guide whose first step installs and opens Local Engine', () => {
    const quickStart = source('src/components/downloader/QuickStartCard.tsx')
    expect(quickStart).toContain("title: '四步轻松下载'")
    expect(quickStart).toContain("engineTitle: '下载安装并打开本地引擎'")
    expect(quickStart).toContain('href="galaxy-downloader://open"')
    expect(quickStart).toContain("open: '打开引擎'")
  })
})
