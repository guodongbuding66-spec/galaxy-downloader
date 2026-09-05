'use client'

import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, HardDriveDownload, Play, RefreshCw } from 'lucide-react'
import { usePathname } from 'next/navigation'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { LOCAL_ENGINE_RELEASE_URL, LOCAL_ENGINE_REQUIRED_VERSION } from '@/lib/local-engine'
import { getLocalEngineBridgeStatus } from '@/lib/local-engine-bridge'
import { probeLocalEngineVersion } from '@/lib/local-engine-version-probe'
import { getLocalImageEngineVersion } from '@/lib/local-image-engine'

type Status = 'checking' | 'ready' | 'upgrade' | 'repair' | 'offline'

type Copy = {
  ready: string
  upgrade: string
  repair: string
  offline: string
  download: string
  open: string
  retry: string
}

const COPY: Record<string, Copy> = {
  zh: {
    ready: '本地引擎已连接 · 原图、大文件和批量打包优先在本机完成',
    upgrade: '检测到旧版本地引擎（当前 v{current}），请升级到 v{required}+',
    repair: '本地引擎已连接，但图片下载服务未就绪；请重新安装最新版或重启引擎',
    offline: '首次使用请先下载并打开本地引擎，再粘贴链接解析',
    download: '下载引擎',
    open: '打开引擎',
    retry: '重新检测',
  },
  'zh-tw': {
    ready: '本機引擎已連線 · 原圖、大檔案與批次打包優先在本機完成',
    upgrade: '偵測到舊版本機引擎（目前 v{current}），請升級至 v{required}+',
    repair: '本機引擎已連線，但圖片下載服務尚未就緒；請重新安裝最新版或重新啟動引擎',
    offline: '首次使用請先下載並開啟本機引擎，再貼上連結解析',
    download: '下載引擎',
    open: '開啟引擎',
    retry: '重新檢測',
  },
  en: {
    ready: 'Local Engine connected · originals, large files and batch archives stay on this device',
    upgrade: 'An older Local Engine is installed (v{current}); upgrade to v{required}+',
    repair: 'Local Engine is connected, but the image download service is not ready. Reinstall the latest version or restart the engine.',
    offline: 'First use: download and open Local Engine before pasting a link',
    download: 'Download engine',
    open: 'Open engine',
    retry: 'Check again',
  },
  ja: {
    ready: 'Local Engine 接続済み · 原画像・大容量・一括保存はこのPCで処理します',
    upgrade: '古い Local Engine（v{current}）を検出しました。v{required}+ に更新してください',
    repair: 'Local Engine は接続済みですが、画像ダウンロードサービスが準備できていません。最新版を再インストールするか再起動してください。',
    offline: '初回は Local Engine をダウンロードして起動してからリンクを貼り付けてください',
    download: 'エンジンを取得',
    open: 'エンジンを開く',
    retry: '再確認',
  },
  es: {
    ready: 'Local Engine conectado · originales, archivos grandes y lotes se procesan en este equipo',
    upgrade: 'Se detectó una versión antigua de Local Engine (v{current}); actualiza a v{required}+',
    repair: 'Local Engine está conectado, pero el servicio de imágenes no está listo. Reinstala la versión más reciente o reinicia el motor.',
    offline: 'Primer uso: descarga y abre Local Engine antes de pegar un enlace',
    download: 'Descargar motor',
    open: 'Abrir motor',
    retry: 'Comprobar',
  },
  ru: {
    ready: 'Local Engine подключён · оригиналы, большие файлы и архивы скачиваются на этом ПК',
    upgrade: 'Обнаружена старая версия Local Engine (v{current}); обновите до v{required}+',
    repair: 'Local Engine подключён, но служба загрузки изображений не готова. Переустановите последнюю версию или перезапустите движок.',
    offline: 'При первом запуске скачайте и откройте Local Engine, затем вставьте ссылку',
    download: 'Скачать',
    open: 'Открыть',
    retry: 'Проверить',
  },
}

function localeFromPath(pathname: string): string {
  return pathname.split('/').filter(Boolean)[0] || 'en'
}

function formatUpgradeMessage(template: string, current: string | null): string {
  return template
    .replace('{current}', current || '?')
    .replace('{required}', LOCAL_ENGINE_REQUIRED_VERSION)
}

export function LocalEngineSetupHint({ className }: { className?: string }) {
  const pathname = usePathname()
  const copy = COPY[localeFromPath(pathname)] || COPY.en
  const [status, setStatus] = useState<Status>('checking')
  const [version, setVersion] = useState<string | null>(null)

  const check = useCallback(async () => {
    const media = await getLocalEngineBridgeStatus()
    if (!media) {
      const probe = await probeLocalEngineVersion()
      if (probe && !probe.compatible) {
        setVersion(probe.version)
        setStatus('upgrade')
        return
      }
      setVersion(null)
      setStatus('offline')
      return
    }

    setVersion(media.version)
    const imageVersion = await getLocalImageEngineVersion()
    setStatus(imageVersion ? 'ready' : 'repair')
  }, [])

  useEffect(() => {
    const initialCheckTimer = window.setTimeout(() => {
      void check()
    }, 0)
    const onFocus = () => void check()
    window.addEventListener('focus', onFocus)
    return () => {
      window.clearTimeout(initialCheckTimer)
      window.removeEventListener('focus', onFocus)
    }
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

  const message = status === 'upgrade'
    ? formatUpgradeMessage(copy.upgrade, version)
    : status === 'repair'
      ? copy.repair
      : copy.offline

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
        {status === 'offline' && (
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
