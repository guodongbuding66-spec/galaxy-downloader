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
  LOCAL_ENGINE_GITHUB_URL,
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
  cookieHelp: string;
  noCookies: string;
  edge: string;
  chrome: string;
  firefox: string;
  launch: string;
  install: string;
  githubMirror: string;
  privacy: string;
  launchHint: string;
  connected: string;
  disconnected: string;
  bridgeRequired: string;
  sent: string;
  cancel: string;
  openFolder: string;
  guideTitle: string;
  guideSteps: string[];
  guideTip: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    title: 'Galaxy Local Engine 本机强力下载',
    intro: '适合 YouTube、B站、小红书、快手、Dailymotion 等存在反爬、登录或 IP 绑定限制的平台，直接调用本机 yt-dlp + FFmpeg。',
    planSync: '会沿用上方“当前成品方案”的画质、音质、字幕和封面设置。',
    cookieSource: '登录状态',
    cookieHelp: '默认不读取浏览器 Cookie。微信视频号需要登录时请选择 Edge、Chrome 或 Firefox；若 Edge/Chrome 正在占用日常 Cookie 数据库，本地引擎会自动打开 Galaxy 专用腾讯元宝登录窗口。首次登录后可在本机复用，不需要关闭日常浏览器。',
    noCookies: '不读取浏览器 Cookie（推荐默认）',
    edge: '使用 Edge 登录状态',
    chrome: '使用 Chrome 登录状态',
    firefox: '使用 Firefox 登录状态',
    launch: '按当前方案本机下载',
    install: '下载 Galaxy Local Engine（官网线路）',
    githubMirror: 'GitHub 备用下载',
    privacy: 'Cookie、视频下载和 FFmpeg 处理全部留在你的电脑，不上传 Galaxy 服务器。',
    launchHint: '尚未检测到兼容的本地引擎。请下载最新版、完整解压并运行 install.cmd；旧的 v0.3.x 会被网站视为不兼容。',
    connected: '本地引擎已连接',
    disconnected: '本地引擎未连接',
    bridgeRequired: '请安装最新版 Galaxy Local Engine（v0.4.0 或更高版本）。',
    sent: '任务已发送到 Galaxy Local Engine',
    cancel: '取消本机任务',
    openFolder: '打开下载文件夹',
    guideTitle: 'Galaxy Local Engine 使用步骤',
    guideSteps: [
      '优先点击“官网线路”下载最新 Windows ZIP；如果官网线路异常，可使用 GitHub 备用下载。',
      '完整解压 ZIP，不能直接在压缩包里运行。新版已内置 FFmpeg、ffprobe 和 yt-dlp.exe，安装时无需再访问 GitHub。',
      '把解压文件夹放在准备长期使用的位置，然后双击 install.cmd。当前解压文件夹就是安装目录，视频会保存到其中的 downloads 文件夹。',
      '保持 Galaxy Local Engine 运行并返回本页，等待显示“本地引擎已连接”；公开视频保持“不读取 Cookie”，确实需要登录时再选择浏览器登录状态。',
    ],
    guideTip: '如果以后把整个 Galaxy Local Engine 文件夹移动到其他磁盘或目录，只需在新位置重新运行一次 install.cmd 以刷新 Windows 协议路径。',
  },
  'zh-tw': {
    title: 'Galaxy Local Engine 本機強力下載',
    intro: '適合存在反爬、登入或 IP 綁定限制的平台，直接呼叫本機 yt-dlp + FFmpeg。',
    planSync: '會沿用上方「目前成品方案」的畫質、音訊、字幕與封面設定。',
    cookieSource: '登入狀態',
    cookieHelp: '預設不讀取瀏覽器 Cookie。只有影片確實需要登入或帳號權限時再選瀏覽器；Cookie 被占用時請先關閉對應瀏覽器。',
    noCookies: '不讀取瀏覽器 Cookie（建議預設）',
    edge: '使用 Edge 登入狀態',
    chrome: '使用 Chrome 登入狀態',
    firefox: '使用 Firefox 登入狀態',
    launch: '依目前方案本機下載',
    install: '下載 Galaxy Local Engine（官網線路）',
    githubMirror: 'GitHub 備用下載',
    privacy: 'Cookie、影片與 FFmpeg 處理全部保留在你的電腦。',
    launchHint: '尚未偵測到相容的本地引擎。請下載最新版、完整解壓並執行 install.cmd；舊 v0.3.x 不再相容。',
    connected: '本地引擎已連線',
    disconnected: '本地引擎未連線',
    bridgeRequired: '請安裝最新版 Galaxy Local Engine（v0.4.0 或更新版本）。',
    sent: '工作已傳送到 Galaxy Local Engine',
    cancel: '取消本機工作',
    openFolder: '開啟下載資料夾',
    guideTitle: 'Galaxy Local Engine 使用步驟',
    guideSteps: [
      '優先使用官網線路下載 Windows ZIP；需要時可改用 GitHub 備用線路。',
      '完整解壓 ZIP。FFmpeg、ffprobe 與 yt-dlp.exe 已內置，安裝時不需要再從 GitHub 下載。',
      '把解壓資料夾放到長期使用位置後執行 install.cmd；該資料夾就是安裝目錄，影片保存在 downloads。',
      '保持程式執行並返回本頁；公開影片維持不讀取 Cookie，需要登入時再選瀏覽器。',
    ],
    guideTip: '日後若移動整個資料夾，請在新位置重新執行一次 install.cmd。',
  },
  en: {
    title: 'Galaxy Local Engine',
    intro: 'Use local yt-dlp + FFmpeg for sites with anti-bot, login, or IP-bound media restrictions.',
    planSync: 'It uses the same video, audio, subtitle, and cover choices shown in the current output plan.',
    cookieSource: 'Login session',
    cookieHelp: 'Browser cookies are off by default. Select a browser only when the media actually requires login, age verification, or account access. Close that browser if its cookie database is locked.',
    noCookies: 'Do not read browser cookies (recommended)',
    edge: 'Use Edge login session',
    chrome: 'Use Chrome login session',
    firefox: 'Use Firefox login session',
    launch: 'Download current plan locally',
    install: 'Download Galaxy Local Engine (site)',
    githubMirror: 'GitHub mirror',
    privacy: 'Cookies, media downloads and FFmpeg processing stay on this computer.',
    launchHint: 'No compatible local engine was detected. Download the latest ZIP, extract it fully and run install.cmd. Legacy v0.3.x engines are no longer accepted by the website.',
    connected: 'Local engine connected',
    disconnected: 'Local engine not connected',
    bridgeRequired: 'Install Galaxy Local Engine v0.4.0 or newer.',
    sent: 'Job sent to Galaxy Local Engine',
    cancel: 'Cancel local job',
    openFolder: 'Open download folder',
    guideTitle: 'How to use Galaxy Local Engine',
    guideSteps: [
      'Prefer the Galaxy website download. Use the GitHub mirror only if needed.',
      'Extract the full ZIP. FFmpeg, ffprobe and yt-dlp.exe are already bundled, so first-time installation does not need GitHub access.',
      'Place the extracted folder where you want to keep it, then run install.cmd. That folder is the install folder and downloads are saved under its downloads directory.',
      'Keep Galaxy Local Engine running and return here. Leave cookies disabled for public media and choose a browser session only when login is actually required.',
    ],
    guideTip: 'If you move the whole folder later, run install.cmd once again from the new location to refresh the Windows protocol path.',
  },
  ja: {
    title: 'Galaxy Local Engine',
    intro: 'ログイン、Bot 対策、IP 制限があるサイトでは、この PC の yt-dlp + FFmpeg を使用します。',
    planSync: '上の出力プランと同じ画質・音質・字幕・カバー設定を使用します。',
    cookieSource: 'ログイン状態',
    cookieHelp: 'Cookie は既定で使用しません。ログインが必要な動画だけブラウザーを選択し、Cookie データベースが使用中ならそのブラウザーを終了してください。',
    noCookies: 'ブラウザー Cookie を使用しない（推奨）',
    edge: 'Edge のログイン状態を使用',
    chrome: 'Chrome のログイン状態を使用',
    firefox: 'Firefox のログイン状態を使用',
    launch: '現在のプランをローカル保存',
    install: 'Galaxy Local Engine をサイトからダウンロード',
    githubMirror: 'GitHub ミラー',
    privacy: 'Cookie、メディア、FFmpeg 処理はこの PC 内だけで行われます。',
    launchHint: '互換性のあるローカルエンジンを検出できません。最新版 ZIP を展開して install.cmd を実行してください。',
    connected: 'ローカルエンジン接続済み',
    disconnected: 'ローカルエンジン未接続',
    bridgeRequired: 'Galaxy Local Engine v0.4.0 以降をインストールしてください。',
    sent: 'ジョブをローカルエンジンへ送信しました',
    cancel: 'ローカルジョブをキャンセル',
    openFolder: 'ダウンロードフォルダーを開く',
    guideTitle: 'Galaxy Local Engine の使い方',
    guideSteps: ['まず公式サイト経由で ZIP をダウンロードします。必要な場合のみ GitHub ミラーを使用します。', 'ZIP を完全に展開します。FFmpeg と yt-dlp は同梱済みです。', '保存したい場所にフォルダーを置き install.cmd を実行します。downloads フォルダーに動画が保存されます。', '公開動画では Cookie を使わず、ログインが必要な場合だけブラウザーセッションを選択します。'],
    guideTip: 'フォルダーを移動した場合は、新しい場所で install.cmd をもう一度実行してください。',
  },
  es: {
    title: 'Galaxy Local Engine',
    intro: 'Usa yt-dlp + FFmpeg localmente para sitios con inicio de sesión, anti-bot o bloqueo por IP.',
    planSync: 'Usa las mismas opciones de vídeo, audio, subtítulos y portada del plan actual.',
    cookieSource: 'Sesión del navegador',
    cookieHelp: 'Las cookies están desactivadas por defecto. Selecciona un navegador solo cuando el contenido requiera inicio de sesión; ciérralo si su base de cookies está bloqueada.',
    noCookies: 'No usar cookies del navegador (recomendado)',
    edge: 'Usar sesión de Edge',
    chrome: 'Usar sesión de Chrome',
    firefox: 'Usar sesión de Firefox',
    launch: 'Descargar el plan actual localmente',
    install: 'Descargar Galaxy Local Engine (sitio)',
    githubMirror: 'Espejo de GitHub',
    privacy: 'Cookies, contenido y FFmpeg permanecen en este equipo.',
    launchHint: 'No se detectó un motor local compatible. Descarga el ZIP más reciente, extráelo y ejecuta install.cmd.',
    connected: 'Motor local conectado',
    disconnected: 'Motor local no conectado',
    bridgeRequired: 'Instala Galaxy Local Engine v0.4.0 o posterior.',
    sent: 'Tarea enviada a Galaxy Local Engine',
    cancel: 'Cancelar tarea local',
    openFolder: 'Abrir carpeta de descargas',
    guideTitle: 'Cómo usar Galaxy Local Engine',
    guideSteps: ['Usa primero la descarga del sitio y deja GitHub como alternativa.', 'Extrae todo el ZIP. FFmpeg y yt-dlp ya vienen incluidos.', 'Coloca la carpeta donde quieras conservarla y ejecuta install.cmd; los vídeos se guardan en downloads.', 'Para contenido público deja las cookies desactivadas y usa una sesión del navegador solo si hace falta iniciar sesión.'],
    guideTip: 'Si mueves la carpeta completa, ejecuta install.cmd de nuevo desde la nueva ubicación.',
  },
  ru: {
    title: 'Galaxy Local Engine',
    intro: 'Используйте локальные yt-dlp + FFmpeg для сайтов с авторизацией, антибот-защитой или IP-ограничениями.',
    planSync: 'Используются те же настройки видео, аудио, субтитров и обложки, что и в текущем плане.',
    cookieSource: 'Сеанс браузера',
    cookieHelp: 'Cookies браузера по умолчанию отключены. Выбирайте браузер только если контент требует входа; закройте его, если база cookies заблокирована.',
    noCookies: 'Не использовать cookies браузера (рекомендуется)',
    edge: 'Использовать сеанс Edge',
    chrome: 'Использовать сеанс Chrome',
    firefox: 'Использовать сеанс Firefox',
    launch: 'Скачать текущий план локально',
    install: 'Скачать Galaxy Local Engine с сайта',
    githubMirror: 'Зеркало GitHub',
    privacy: 'Cookies, медиа и FFmpeg остаются только на этом компьютере.',
    launchHint: 'Совместимый локальный движок не обнаружен. Скачайте последний ZIP, распакуйте его и запустите install.cmd.',
    connected: 'Локальный движок подключён',
    disconnected: 'Локальный движок не подключён',
    bridgeRequired: 'Установите Galaxy Local Engine v0.4.0 или новее.',
    sent: 'Задание отправлено в Galaxy Local Engine',
    cancel: 'Отменить локальную задачу',
    openFolder: 'Открыть папку загрузок',
    guideTitle: 'Как использовать Galaxy Local Engine',
    guideSteps: ['Сначала используйте загрузку с сайта, GitHub оставьте как резерв.', 'Полностью распакуйте ZIP. FFmpeg и yt-dlp уже включены.', 'Поместите папку в постоянное место и запустите install.cmd; файлы сохраняются в downloads.', 'Для публичного контента оставьте cookies выключенными и выбирайте браузер только когда нужен вход.'],
    guideTip: 'После перемещения всей папки снова запустите install.cmd из нового места.',
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
  const [browser, setBrowser] = useState<LocalEngineBrowser>('none');
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
    <section className="min-w-0 max-w-full overflow-hidden rounded-xl border border-primary/20 bg-primary/[0.035] shadow-sm">
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
            <span className="tabular-nums text-muted-foreground">{bridge ? `v${bridge.version}` : 'v0.4.0+'}</span>
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
            <SelectTrigger className="h-10 min-w-0 max-w-full bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{copy.noCookies}</SelectItem>
              <SelectItem value="edge">{copy.edge}</SelectItem>
              <SelectItem value="chrome">{copy.chrome}</SelectItem>
              <SelectItem value="firefox">{copy.firefox}</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-[11px] leading-4 text-muted-foreground">{copy.cookieHelp}</p>
        </div>

        <div className="grid gap-2">
          {bridge?.busy ? (
            <Button type="button" variant="destructive" className="min-h-11 w-full min-w-0 whitespace-normal text-center font-semibold leading-5" onClick={() => void handleCancel()}>
              <X className="h-4 w-4" aria-hidden="true" />
              {copy.cancel}
            </Button>
          ) : (
            <Button
              type="button"
              className="min-h-11 w-full min-w-0 whitespace-normal text-center font-semibold leading-5"
              onClick={() => void handleLaunch()}
              disabled={disabled || launching}
            >
              {launching ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <HardDriveDownload className="h-4 w-4" aria-hidden="true" />}
              {copy.launch}
            </Button>
          )}

          {bridge ? (
            <Button type="button" variant="outline" className="min-h-10 w-full min-w-0 whitespace-normal text-center leading-5" onClick={() => void handleOpenFolder()}>
              <FolderOpen className="h-4 w-4" aria-hidden="true" />
              {copy.openFolder}
            </Button>
          ) : (
            <div className="grid gap-2">
              <Button type="button" variant="outline" className="min-h-10 w-full min-w-0 whitespace-normal text-center leading-5" asChild>
                <a href={LOCAL_ENGINE_RELEASE_URL}>
                  <HardDriveDownload className="h-4 w-4" aria-hidden="true" />
                  {copy.install}
                </a>
              </Button>
              <Button type="button" variant="ghost" className="min-h-9 w-full min-w-0 whitespace-normal text-center text-xs leading-5" asChild>
                <a href={LOCAL_ENGINE_GITHUB_URL} target="_blank" rel="noreferrer">
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  {copy.githubMirror}
                </a>
              </Button>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-primary/15 bg-background/70 p-3">
          <div className="text-xs font-semibold text-foreground">{copy.guideTitle}</div>
          <ol className="mt-2 space-y-2">
            {copy.guideSteps.map((step, index) => (
              <li key={step} className="flex gap-2 text-[11px] leading-4 text-muted-foreground">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">
                  {index + 1}
                </span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
          <p className="mt-2 border-t pt-2 text-[11px] leading-4 text-muted-foreground">{copy.guideTip}</p>
        </div>

        <div className="flex items-start gap-2 border-t border-primary/10 pt-3 text-xs leading-5 text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span>{copy.privacy}</span>
        </div>
      </div>
    </section>
  );
}
