import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  canDirectDownload,
  candidateQualityLabel,
  classifyMediaUrl,
  mergeCandidates,
  normalizeCandidate,
  publicCandidate,
  requiresGalaxyHandoff,
  scoreCandidate,
  suggestedFilename,
} from './media-core.js'

const here = path.dirname(fileURLToPath(import.meta.url))
const manifest = JSON.parse(fs.readFileSync(path.join(here, 'manifest.json'), 'utf8'))
const backgroundSource = fs.readFileSync(path.join(here, 'background.js'), 'utf8')
const browserSource = fs.readFileSync(path.join(here, 'candidate-browser.js'), 'utf8')

assert.equal(manifest.manifest_version, 3)
assert.deepEqual([...manifest.permissions].sort(), ['downloads', 'webRequest'])
assert(!manifest.permissions.includes('cookies'))
assert(!manifest.permissions.includes('storage'))
assert(!manifest.permissions.includes('nativeMessaging'))
assert(!manifest.permissions.includes('clipboardRead'))
assert.equal(manifest.background.service_worker, 'background.js')
assert.equal(manifest.content_scripts.length, 2)
assert.equal(manifest.content_scripts[0].world, 'MAIN')
assert.deepEqual(manifest.content_scripts[0].js, ['page-probe.js'])
assert.equal(manifest.content_scripts[1].world, 'ISOLATED')
assert(manifest.content_scripts[1].js.includes('content.js'))
assert(manifest.content_scripts[1].js.includes('dynamic-scan.js'))
assert(manifest.content_scripts[1].js.includes('element-actions.js'))
assert(manifest.content_scripts[1].js.includes('candidate-browser.js'))
assert(!manifest.content_scripts[0].js.includes('element-actions.js'))
assert(!manifest.content_scripts[0].js.includes('candidate-browser.js'))

assert.equal(classifyMediaUrl('https://cdn.example/video.mp4'), 'video')
assert.equal(classifyMediaUrl('https://cdn.example/master.m3u8'), 'hls')
assert.equal(classifyMediaUrl('https://cdn.example/manifest', 'application/dash+xml'), 'dash')
assert.equal(classifyMediaUrl('https://cdn.example/file', 'image/webp'), 'image')

assert.equal(normalizeCandidate({ url: 'blob:https://site.example/abc', mediaKind: 'video' }), null)
assert.equal(normalizeCandidate({ url: 'data:video/mp4;base64,AAAA', mediaKind: 'video' }), null)
assert.equal(normalizeCandidate({ url: 'javascript:alert(1)', mediaKind: 'video' }), null)

const source = normalizeCandidate({
  url: 'https://cdn.example/source/original-video.mp4?token=opaque',
  pageUrl: 'https://site.example/watch',
  source: 'dom-current-src',
  mediaKind: 'video',
  width: 1920,
  height: 1080,
})
assert(source)
assert.equal(source.mediaKind, 'video')
assert.equal(source.pageUrl, 'https://site.example/watch')
assert.equal(candidateQualityLabel(source), '1080p · 1920×1080')

const preview = normalizeCandidate({
  url: 'https://cdn.example/preview/watermarked-video.mp4',
  source: 'web-request',
  mediaKind: 'video',
  width: 640,
  height: 360,
})
assert(preview)
assert(scoreCandidate(source) > scoreCandidate(preview))

const merged = mergeCandidates([preview], [source, source])
assert.equal(merged.length, 2)
assert.equal(merged[0].url, source.url)

assert.equal(canDirectDownload(source), true)
const hls = normalizeCandidate({ url: 'https://cdn.example/master.m3u8', source: 'performance', mediaKind: 'hls' })
assert(hls)
assert.equal(canDirectDownload(hls), false)
assert.equal(requiresGalaxyHandoff(hls), true)
assert.equal(candidateQualityLabel(hls), '自适应流')

const publicSource = publicCandidate(source, '7')
assert.equal(publicSource.id, '7')
assert.equal(publicSource.qualityLabel, '1080p · 1920×1080')
assert.equal(typeof publicSource.rankScore, 'number')
assert(!Object.hasOwn(publicSource, 'url'))
assert(!JSON.stringify(publicSource).includes('token=opaque'))

assert.equal(suggestedFilename(source).endsWith('.mp4'), true)

assert(backgroundSource.includes('MAX_BATCH_DOWNLOADS = 20'))
assert(backgroundSource.includes('galaxy:download-candidates'))
assert(backgroundSource.includes('canDirectDownload(candidate)'))
assert(backgroundSource.includes('galaxy:toggle-candidate-browser'))
assert(browserSource.includes('["stream", "流媒体"]'))
assert(browserSource.includes('selectedIds'))
assert(browserSource.includes('galaxy:download-candidates'))
assert(browserSource.includes('candidate.qualityLabel'))
assert(!browserSource.includes('candidate.url'))

console.log('Galaxy MV3 media core tests passed')
