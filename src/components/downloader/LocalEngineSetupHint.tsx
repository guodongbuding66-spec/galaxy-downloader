'use client'

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, HardDriveDownload, Play, RefreshCw } from 'lucide-react'
import { usePathname } from 'next/navigation'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { LOCAL_ENGINE_RELEASE_URL } from '@/lib/local-engine'
import { getLocalEngineBridgeStatus } from '@/lib/local-engine-bridge'
import { getLocalImageEngineVersion } from '@/lib/local-image-engine'

type Status = 'checking' | 'ready' | 'upgrade' | 'offline'

type Copy = {
  ready: string
  upgrade: string
  offline: string
  download: string
  open: string
  retry: string
}

const COPY: Record<string, Copy> = {
  zh: {
    ready: '本地引擎已连接 · 原图、大文件和批量打包优先在本机完成',
    upgrade: '本地引擎需要升级到 0.7.0+，才能启用原图和批量本机下载',
    offline: '首次使用请先下载并打开本地引擎，再粘贴链接解析',
    download: '下载引擎',
    open: '打开引擎',
    retry: '重新检测',
  },
  'zh-tw': {
    ready: '本機引擎已連線 · 原圖、大檔案與批次打包優先在本機完成',
    upgrade: '本機引擎需升級至 0.7.0+，才能啟用原圖與批次本機下載',
    offline: '首次使用請先下載並開啟本機引擎，再貼上連結解析',
    download: '下載引擎',
    open: '開啟引擎',
    retry: '重新檢測',
  },
  en: {
    ready: 'Local Engine connected · originals, large files and batch archives stay on this device',
    upgrade: 'Upgrade Local Engine to 0.7.0+ for direct original-image and batch downloads',
    offline: 'First use: download and open Local Engine before pasting a link',
    download: 'Download engine',
    open: 'Open engine',
    retry: 'Check again',
  },
  ja: {
    ready: 'Local Engine 接続済み · 原画像・大容量・一括保存はこのPCで処理します',
    upgrade: '原画像と一括ローカル保存には Local Engine 0.7.0+ が必要です',
    offline: '初回は Local Engine をダウンロードして起動してからリンクを貼り付けてください',
    download: 'エンジンを取得',
    open: 'エンジンを開く',
    retry: '再確認',
  },
  es: {
    ready: 'Local Engine conectado · originales, archivos grandes y lotes se procesan en este equipo',
    upgrade: 'Actualiza Local Engine a 0.7.0+ para originales y descargas por lotes locales',
    offline: 'Primer uso: descarga y abre Local Engine antes de pegar un enlace',
    download: 'Descargar motor',
    open: 'Abrir motor',
    retry: 'Comprobar',
  },
  ru: {
    ready: 'Local Engine подключён · оригиналы, большие файлы и архивы скачиваются на этом ПК',
    upgrade: 'Обновите Local Engine до 0.7.0+ для оригиналов и пакетной загрузки',
    offline: 'При первом запуске скачайте и откройте Local Engine, затем вставьте ссылку',
    download: 'Скачать',
    open: 'Открыть',
    retry: 'Проверить',
  },
}

function localeFromPath(pathname: string): string {
  return pathname.split('/').filter(Boolean)[0] || 'en'
}

export function LocalEngineSetupHint({ className }: { className?: string }) {
  const pathname = usePathname()
  const copy = COPY[localeFromPath(pathname)] || COPY.en
  const [status, setStatus] = useState<Status>('checking')
  const [version, setVersion] = useState<string | null>(null)

  const check = useCallback(async () => {
    const media = await getLocalEngineBridgeStatus()
    if (!media) {
      setVersion(null)
      setStatus('offline')
      return
    }
    setVersion(media.version)
    const imageVersion = await getLocalImageEngineVersion()
    setStatus(imageVersion ? 'ready' : 'upgrade')
  }, [])

  useEffect(() => {
    void check()
    const onFocus = () => void check()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [check])

  const launch = () => {
    window.location.href = 'galaxy-downloader://open'
    window.setTimeout(() => void check(), 1800)
  }

  const retry = () => {
    setStatus('checking')
    void check()
  }

  if (status === 'ready') {
    return (
      <div className={cn('flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground', className)}>
        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
        <span className="truncate">{copy.ready}{version ? ` · v${version}` : ''}</span>
      </div>
    )
  }

  const message = status === 'upgrade' ? copy.upgrade : copy.offline
  return (
    <div className={cn('flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-[11px]', className)}>
      <span className="text-muted-foreground">{message}</span>
      <div className="flex shrink-0 items-center gap-0.5">
        <Button size="xs" variant="ghost" className="h-7 px-2" asChild>
          <a href={LOCAL_ENGINE_RELEASE_URL}>
            <HardDriveDownload className="h-3.5 w-3.5" aria-hidden="true" />
            {copy.download}
          </a>
        </Button>
        {status !== 'upgrade' && (
          <Button size="xs" variant="ghost" className="h-7 px-2" type="button" onClick={launch}>
            <Play className="h-3.5 w-3.5" aria-hidden="true" />
            {copy.open}
          </Button>
        )}
        <Button
          size="icon"
          variant="ghost"
          className="h-7 w-7"
          type="button"
          onClick={retry}
          aria-label={copy.retry}
          title={copy.retry}
          disabled={status === 'checking'}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', status === 'checking' && 'animate-spin')} aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}
