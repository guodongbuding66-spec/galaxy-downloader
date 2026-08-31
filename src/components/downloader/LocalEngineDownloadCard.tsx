'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
  CircleCheck,
  ExternalLink,
  FolderOpen,
  HardDriveDownload,
  Loader2,
  ShieldCheck,
  X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from '@/lib/deferred-toast';
import {
  cancelLocalEngineBridgeJob,
  getLocalEngineBridgeStatus,
  openLocalEngineDownloadFolder,
  submitLocalEngineBridgeJob,
  type LocalEngineBridgeJob,
  type LocalEngineBridgeStatus,
} from '@/lib/local-engine-bridge';
import {
  LOCAL_ENGINE_RELEASE_URL,
  launchLocalDesktopEngine,
  resolveLocalDesktopVideoQuality,
  type LocalDesktopVideoSelection,
  type LocalEngineBrowser,
} from '@/lib/local-engine';
import type { UnifiedParseResult } from '@/lib/types';

type ResultData = NonNullable<UnifiedParseResult['data']>;

export type LocalEngineDownloadPlan = {
  videoSelection?: LocalDesktopVideoSelection | null;
  audioQuality: string;
  includeAudio: boolean;
  includeSubtitle: boolean;
  subtitleLanguage?: string | null;
  includeCover: boolean;
};

type Copy = {
  title: string;
  intro: string;
  planSync: string;
  cookieSource: string;
  noCookies: string;
  edge: string;
  chrome: string;
  firefox: string;
  launch: string;
  install: string;
  privacy: string;
  launchHint: string;
  connected: string;
  disconnected: string;
  bridgeRequired: string;
  sent: string;
  cancel: string;
  openFolder: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    title: '本机 yt-dlp 强力下载',
    intro: '遇到 YouTube、B站、小红书、快手、Dailymotion 等反爬、登录或 IP 绑定限制时，直接调用你电脑上的 yt-dlp + FFmpeg。',
    planSync: '将使用上方“当前成品方案”的同一组画质、音质、字幕和封面设置。',
    cookieSource: '登录状态',
    noCookies: '不读取浏览器 Cookie',
    edge: '使用 Edge 登录状态',
    chrome: '使用 Chrome 登录状态',
    firefox: '使用 Firefox 登录状态',
    launch: '按当前方案本机下载',
    install: '安装 / 更新本地引擎',
    privacy: 'Cookie、视频和 FFmpeg 处理全部留在你的电脑，不上传 Galaxy 服务器。',
    launchHint: '尚未检测到本地引擎通信服务。请安装或更新 Galaxy Local Engine 后重试。',
    connected: '本地引擎已连接',
    disconnected: '本地引擎未连接',
    bridgeRequired: '需要 Galaxy Local Engine v0.3.0 或更高版本',
    sent: '任务已发送到 Galaxy Local Engine',
    cancel: '取消本机任务',
    openFolder: '打开下载文件夹',
  },
  'zh-tw': {
    title: '本機 yt-dlp 強力下載',
    intro: '遇到反爬、登入或 IP 綁定限制時，直接呼叫電腦上的 yt-dlp + FFmpeg。',
    planSync: '會沿用上方「目前成品方案」相同的畫質、音訊、字幕與封面設定。',
    cookieSource: '登入狀態',
    noCookies: '不讀取瀏覽器 Cookie',
    edge: '使用 Edge 登入狀態',
    chrome: '使用 Chrome 登入狀態',
    firefox: '使用 Firefox 登入狀態',
    launch: '依目前方案本機下載',
    install: '安裝 / 更新本地引擎',
    privacy: 'Cookie、影片與 FFmpeg 處理全部保留在你的電腦。',
    launchHint: '尚未偵測到本地引擎通訊服務，請安裝或更新後重試。',
    connected: '本地引擎已連線',
    disconnected: '本地引擎未連線',
    bridgeRequired: '需要 Galaxy Local Engine v0.3.0 或更新版本',
    sent: '工作已傳送到 Galaxy Local Engine',
    cancel: '取消本機工作',
    openFolder: '開啟下載資料夾',
  },
  en: {
    title: 'Local yt-dlp power download',
    intro: 'For anti-bot, login, or IP-bound platforms, run yt-dlp + FFmpeg directly on this computer.',
    planSync: 'Uses the same video, audio, subtitle, and cover choices shown in the current output plan above.',
    cookieSource: 'Login session',
    noCookies: 'Do not read browser cookies',
    edge: 'Use Edge login session',
    chrome: 'Use Chrome login session',
    firefox: 'Use Firefox login session',
    launch: 'Download current plan locally',
    install: 'Install / update local engine',
    privacy: 'Cookies, media and FFmpeg processing stay on this computer and are not uploaded to Galaxy servers.',
    launchHint: 'The local bridge was not detected. Install or update Galaxy Local Engine and try again.',
    connected: 'Local engine connected',
    disconnected: 'Local engine not connected',
    bridgeRequired: 'Galaxy Local Engine v0.3.0 or newer is required',
    sent: 'Job sent to Galaxy Local Engine',
    cancel: 'Cancel local job',
    openFolder: 'Open download folder',
  },
  ja: {
    title: 'ローカル yt-dlp 強力ダウンロード',
    intro: 'ログイン、Bot 対策、IP 制限があるサイトでは、この PC の yt-dlp + FFmpeg を直接使用します。',
    planSync: '上の出力プランと同じ画質・音質・字幕・カバー設定を使用します。',
    cookieSource: 'ログイン状態',
    noCookies: 'ブラウザー Cookie を使用しない',
    edge: 'Edge のログイン状態を使用',
    chrome: 'Chrome のログイン状態を使用',
    firefox: 'Firefox のログイン状態を使用',
    launch: '現在のプランをローカル保存',
    install: 'ローカルエンジンをインストール / 更新',
    privacy: 'Cookie、メディア、FFmpeg 処理はこの PC 内だけで行われます。',
    launchHint: 'ローカル通信サービスを検出できません。エンジンを更新して再試行してください。',
    connected: 'ローカルエンジン接続済み',
    disconnected: 'ローカルエンジン未接続',
    bridgeRequired: 'Galaxy Local Engine v0.3.0 以降が必要です',
    sent: 'ジョブをローカルエンジンへ送信しました',
    cancel: 'ローカルジョブをキャンセル',
    openFolder: 'ダウンロードフォルダーを開く',
  },
  es: {
    title: 'Descarga local avanzada con yt-dlp',
    intro: 'Para sitios con inicio de sesión, anti-bot o bloqueo por IP, usa yt-dlp + FFmpeg directamente en este equipo.',
    planSync: 'Usa las mismas opciones de vídeo, audio, subtítulos y portada del plan de salida actual.',
    cookieSource: 'Sesión del navegador',
    noCookies: 'No usar cookies del navegador',
    edge: 'Usar sesión de Edge',
    chrome: 'Usar sesión de Chrome',
    firefox: 'Usar sesión de Firefox',
    launch: 'Descargar el plan actual localmente',
    install: 'Instalar / actualizar motor local',
    privacy: 'Las cookies, el contenido y FFmpeg permanecen en este equipo.',
    launchHint: 'No se detectó el puente local. Instala o actualiza Galaxy Local Engine.',
    connected: 'Motor local conectado',
    disconnected: 'Motor local no conectado',
    bridgeRequired: 'Se requiere Galaxy Local Engine v0.3.0 o posterior',
    sent: 'Tarea enviada a Galaxy Local Engine',
    cancel: 'Cancelar tarea local',
    openFolder: 'Abrir carpeta de descargas',
  },
  ru: {
    title: 'Локальная загрузка через yt-dlp',
    intro: 'Для сайтов с авторизацией, антибот-защитой или привязкой к IP используйте yt-dlp + FFmpeg прямо на этом компьютере.',
    planSync: 'Используются те же настройки видео, аудио, субтитров и обложки, что указаны в текущем плане выше.',
    cookieSource: 'Сеанс браузера',
    noCookies: 'Не использовать cookies браузера',
    edge: 'Использовать сеанс Edge',
    chrome: 'Использовать сеанс Chrome',
    firefox: 'Использовать сеанс Firefox',
    launch: 'Скачать текущий план локально',
    install: 'Установить / обновить локальный движок',
    privacy: 'Cookies, медиа и обработка FFmpeg остаются только на этом компьютере.',
    launchHint: 'Локальный мост не обнаружен. Установите или обновите Galaxy Local Engine.',
    connected: 'Локальный движок подключён',
    disconnected: 'Локальный движок не подключён',
    bridgeRequired: 'Требуется Galaxy Local Engine v0.3.0 или новее',
    sent: 'Задание отправлено в Galaxy Local Engine',
    cancel: 'Отменить локальную задачу',
    openFolder: 'Открыть папку загрузок',
  },
};

function copyFor(pathname: string | null): Copy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
  return COPY[locale] || COPY.en;
}

function scopedSourceUrl(result: ResultData): string {
  const source = typeof result.url === 'string' ? result.url.trim() : '';
  if (!source) return '';
  if ((result.platform === 'bili' || result.platform === 'bilibili') && result.currentPage) {
    try {
      const url = new URL(source);
      url.searchParams.set('p', String(result.currentPage));
      return url.toString();
    } catch {
      return source;
    }
  }
  return source;
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function LocalEngineDownloadCard({
  result,
  plan,
  disabled = false,
}: {
  result: ResultData;
  plan: LocalEngineDownloadPlan;
  disabled?: boolean;
}) {
  const pathname = usePathname();
  const copy = copyFor(pathname);
  const sourceUrl = scopedSourceUrl(result);
  const [browser, setBrowser] = useState<LocalEngineBrowser>(() => {
    if (typeof navigator === 'undefined') return 'none';
    return /Windows/i.test(navigator.userAgent) ? 'edge' : 'none';
  });
  const [bridge, setBridge] = useState<LocalEngineBridgeStatus | null>(null);
  const [launching, setLaunching] = useState(false);

  const supported = useMemo(
    () => sourceUrl.startsWith('http://') || sourceUrl.startsWith('https://'),
    [sourceUrl],
  );

  const refreshBridge = useCallback(async () => {
    const next = await getLocalEngineBridgeStatus();
    setBridge(next);
    return next;
  }, []);

  useEffect(() => {
    if (!supported) return;
    let active = true;
    const refresh = async () => {
      const next = await getLocalEngineBridgeStatus();
      if (active) setBridge(next);
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [supported]);

  if (!supported) return null;

  const localJob: LocalEngineBridgeJob = {
    sourceUrl,
    videoQuality: resolveLocalDesktopVideoQuality(plan.videoSelection),
    audioQuality: plan.audioQuality || 'best',
    includeAudio: plan.includeAudio,
    includeSubtitle: plan.includeSubtitle,
    subtitleLanguage: plan.includeSubtitle ? plan.subtitleLanguage || null : null,
    includeCover: plan.includeCover,
    browser,
    playlist: false,
  };

  const handleLaunch = async () => {
    if (disabled || launching) return;
    setLaunching(true);
    try {
      if (bridge) {
        await submitLocalEngineBridgeJob(localJob);
        toast.success(copy.sent);
        await refreshBridge();
        return;
      }

      // Backward-compatible bootstrap: the custom protocol starts the app.
      // v0.3.0+ then exposes the localhost bridge so the page can track it.
      launchLocalDesktopEngine({
        sourceUrl,
        videoQuality: localJob.videoQuality,
        audioQuality: localJob.audioQuality,
        includeAudio: localJob.includeAudio,
        includeSubtitle: localJob.includeSubtitle,
        subtitleLanguage: localJob.subtitleLanguage,
        includeCover: localJob.includeCover,
        browser,
        playlist: false,
      });

      for (let attempt = 0; attempt < 10; attempt += 1) {
        await sleep(attempt === 0 ? 500 : 700);
        const next = await refreshBridge();
        if (next) {
          toast.success(copy.sent);
          return;
        }
      }
      toast.message(copy.launchHint);
    } catch (error) {
      toast.error(copy.title, {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setLaunching(false);
    }
  };

  const handleCancel = async () => {
    try {
      await cancelLocalEngineBridgeJob();
      await refreshBridge();
    } catch (error) {
      toast.error(copy.cancel, { description: error instanceof Error ? error.message : String(error) });
    }
  };

  const handleOpenFolder = async () => {
    try {
      await openLocalEngineDownloadFolder();
    } catch (error) {
      toast.error(copy.openFolder, { description: error instanceof Error ? error.message : String(error) });
    }
  };

  return (
    <section className="overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.035] shadow-sm">
      <div className="space-y-3 p-3.5">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/15">
            <HardDriveDownload className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold tracking-tight">{copy.title}</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground text-pretty">{copy.intro}</p>
            <p className="mt-1.5 text-xs font-medium leading-5 text-foreground/80 text-pretty">{copy.planSync}</p>
          </div>
        </div>

        <div className="rounded-lg border bg-background/80 p-3">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2 font-medium">
              {bridge ? (
                <CircleCheck className="h-4 w-4 text-emerald-600" aria-hidden="true" />
              ) : (
                <span className="h-2.5 w-2.5 rounded-full bg-muted-foreground/40" />
              )}
              {bridge ? copy.connected : copy.disconnected}
            </span>
            <span className="tabular-nums text-muted-foreground">{bridge ? `v${bridge.version}` : 'v0.3.0+'}</span>
          </div>
          {bridge ? (
            <div className="mt-2 space-y-2">
              <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                <span className="truncate">{bridge.status}</span>
                <span className="tabular-nums">{Math.round(bridge.progress)}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-[width] duration-300" style={{ width: `${bridge.progress}%` }} />
              </div>
              {bridge.detail ? <p className="line-clamp-2 text-[11px] leading-4 text-muted-foreground">{bridge.detail}</p> : null}
              {bridge.busy ? (
                <div className="grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                  <span className="truncate">{bridge.speed}</span>
                  <span className="truncate text-center">ETA {bridge.eta}</span>
                  <span className="truncate text-right">{bridge.downloaded}</span>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="mt-1.5 text-[11px] leading-4 text-muted-foreground">{copy.bridgeRequired}</p>
          )}
        </div>

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">{copy.cookieSource}</label>
          <Select
            value={browser}
            onValueChange={(value) => setBrowser(value as LocalEngineBrowser)}
            disabled={disabled || bridge?.busy}
          >
            <SelectTrigger className="h-10 bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{copy.noCookies}</SelectItem>
              <SelectItem value="edge">{copy.edge}</SelectItem>
              <SelectItem value="chrome">{copy.chrome}</SelectItem>
              <SelectItem value="firefox">{copy.firefox}</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid gap-2">
          {bridge?.busy ? (
            <Button type="button" variant="destructive" className="min-h-11 w-full font-semibold" onClick={() => void handleCancel()}>
              <X className="h-4 w-4" aria-hidden="true" />
              {copy.cancel}
            </Button>
          ) : (
            <Button
              type="button"
              className="min-h-11 w-full font-semibold"
              onClick={() => void handleLaunch()}
              disabled={disabled || launching}
            >
              {launching ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <HardDriveDownload className="h-4 w-4" aria-hidden="true" />}
              {copy.launch}
            </Button>
          )}

          {bridge ? (
            <Button type="button" variant="outline" className="min-h-10 w-full" onClick={() => void handleOpenFolder()}>
              <FolderOpen className="h-4 w-4" aria-hidden="true" />
              {copy.openFolder}
            </Button>
          ) : (
            <Button type="button" variant="outline" className="min-h-10 w-full" asChild>
              <a href={LOCAL_ENGINE_RELEASE_URL} target="_blank" rel="noreferrer">
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                {copy.install}
              </a>
            </Button>
          )}
        </div>

        <div className="flex items-start gap-2 border-t border-primary/10 pt-3 text-xs leading-5 text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span>{copy.privacy}</span>
        </div>
      </div>
    </section>
  );
}
