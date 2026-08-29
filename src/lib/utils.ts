import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

import { API_ENDPOINT_CANDIDATES, API_ENDPOINTS } from "@/lib/config"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

function rewriteSourceAwareDownloadToFirstParty(sourceUrl: string, baseUrl: string): string | null {
  const endpoints = API_ENDPOINT_CANDIDATES.unified.download
  if (endpoints.length < 2) return null

  try {
    const primary = new URL(endpoints[0], baseUrl)
    const firstParty = new URL(endpoints[endpoints.length - 1], baseUrl)
    const candidate = new URL(sourceUrl)

    if (
      candidate.origin !== primary.origin
      || candidate.pathname !== primary.pathname
      || !candidate.searchParams.has('url')
    ) {
      return null
    }

    // Preserve the original source URL and every quality/format selector while
    // switching only the backend host/path. This is especially important for
    // temporary CDN links that are valid only from the parser/downloader's
    // network identity.
    firstParty.search = candidate.search
    return firstParty.toString()
  } catch {
    return null
  }
}

/**
 * Route external media URLs through the public download proxy.
 *
 * Some upstream CDNs (notably YouTube/googlevideo) return short-lived URLs
 * that are bound to the parser server's network identity. Opening those URLs
 * directly in the end user's browser can therefore return HTTP 403 even
 * though parsing succeeded.
 *
 * When NEXT_PUBLIC_CONTAINER_API_BASE_URL is configured, source-aware
 * `/api/download?url=<original page>` links returned by the shared parser are
 * transparently rerouted to the first-party Container backend. This keeps
 * extraction and download on the same backend without changing every UI
 * caller. Plain CDN URLs still use the existing primary download proxy.
 */
export function getProxiedDownloadUrl(url: string): string {
  const sourceUrl = url.trim()
  if (!sourceUrl || !/^https?:\/\//i.test(sourceUrl)) {
    return sourceUrl
  }

  const proxyEndpoint = API_ENDPOINTS.unified.download

  try {
    const baseUrl = typeof window !== 'undefined' ? window.location.origin : 'http://localhost'
    const firstPartyRewrite = rewriteSourceAwareDownloadToFirstParty(sourceUrl, baseUrl)
    if (firstPartyRewrite) {
      return firstPartyRewrite
    }

    const proxyUrl = new URL(proxyEndpoint, baseUrl)
    const candidateUrl = new URL(sourceUrl)

    if (
      candidateUrl.origin === proxyUrl.origin
      && candidateUrl.pathname === proxyUrl.pathname
      && candidateUrl.searchParams.has('url')
    ) {
      return sourceUrl
    }

    // A URL already pointing at any configured download backend should never
    // be nested inside another /api/download request.
    for (const endpoint of API_ENDPOINT_CANDIDATES.unified.download) {
      const endpointUrl = new URL(endpoint, baseUrl)
      if (
        candidateUrl.origin === endpointUrl.origin
        && candidateUrl.pathname === endpointUrl.pathname
        && candidateUrl.searchParams.has('url')
      ) {
        return sourceUrl
      }
    }
  } catch {
    // Fall through and build a proxy URL below.
  }

  const separator = proxyEndpoint.includes('?') ? '&' : '?'
  return `${proxyEndpoint}${separator}${new URLSearchParams({ url: sourceUrl }).toString()}`
}

/**
 * 通用文件下载函数
 * @param url 下载链接
 * @param filename 可选的文件名
 */
export function downloadFile(url: string, filename?: string) {
  const a = document.createElement('a')
  a.href = getProxiedDownloadUrl(url)
  a.download = filename || ''
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/**
 * 格式化时长（秒 -> mm:ss）
 * @param seconds 秒数
 */
export function formatDuration(seconds: number): string {
  const totalSeconds = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(totalSeconds / 3600)
  const mins = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60

  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }

  return `${mins}:${secs.toString().padStart(2, '0')}`
}

/**
 * 清理文件名中的非法字符
 * @param filename 原始文件名
 * @param replacement 替换字符，默认为 '-'
 */
export function sanitizeFilename(filename: string, replacement: string = '-'): string {
  return filename.replace(/[<>:"/\\|?*]/g, replacement)
}

/**
 * 格式化字节为可读的文件大小
 * @param bytes 字节数
 * @param decimals 小数位数，默认为 1
 */
export function formatBytes(bytes: number, decimals: number = 1): string {
  if (bytes === 0) return '0 Bytes'

  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))

  return `${(bytes / Math.pow(k, i)).toFixed(decimals)} ${sizes[i]}`
}
