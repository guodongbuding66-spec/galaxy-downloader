'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
  Check,
  ChevronDown,
  ExternalLink,
  FolderOpen,
  HardDriveDownload,
  Loader2,
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
  cancelLocalEngineQueuedJob,
  getLocalEngineBridgeStatus,
  LocalEngineBridgeSubmissionError,
  openLocalEngineDownloadFolder,
  submitLocalEngineBridgeJob,
  type LocalEngineBridgeJob,
  type LocalEngineBridgeStatus,
} from '@/lib/local-engine-bridge';
import {
  LOCAL_ENGINE_GITHUB_URL,
  LOCAL_ENGINE_RELEASE_URL,
  LOCAL_ENGINE_REQUIRED_VERSION,
  launchLocalDesktopEngine,
  resolveLocalDesktopVideoQuality,
  type LocalDesktopVideoSelection,
  type LocalEngineBrowser,
  type LocalEngineCollectionMode,
} from '@/lib/local-engine';
import type { SubtitleTrack, UnifiedParseResult } from '@/lib/types';

import {
  LocalEngineAdvancedControls,
  type LocalEngineAdvancedOptions,
} from './LocalEngineAdvancedControls';

type ResultData = NonNullable<UnifiedParseResult['data']>;

type AdvancedBridgeStatus = LocalEngineBridgeStatus & {
  aria2Ready?: boolean;
  advancedMedia?: boolean;
};

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
  connected: string;
  disconnected: string;
  cookieSource: string;
  noCookies: string;
  edge: string;
  chrome: string;
  firefox: string;
  collection: string;
  single: string;
  all: string;
  selected: string;
  selectedCount: string;
  selectAll: string;
  clear: string;
  skipDownloaded: string;
  skipDownloadedHint: string;
  launch: string;
  queueAction: string;
  queueStatus: string;
  currentQueue: string;
  idleQueue: string;
  queueFull: string;
  queueJobs: string;
  cancel: string;
  cancelQueued: string;
  queuedCancelled: string;
  openFolder: string;
  install: string;
  githubMirror: string;
  privacy: string;
  sent: string;
  queued: string;
  launchHint: string;
  setup: string;
  setupHint: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    title: '本机下载',
    connected: '已连接',
    disconnected: '未连接',
    cookieSource: '登录状态',
    noCookies: '不读取 Cookie（默认）',
    edge: 'Edge 登录状态',
    chrome: 'Chrome 登录状态',
    firefox: 'Firefox 登录状态',
    collection: '合集范围',
    single: '当前一项',
    all: '整个合集',
    selected: '选择部分',
    selectedCount: '已选 {count} 项',
    selectAll: '全选',
    clear: '清空',
    skipDownloaded: '跳过已下载内容',
    skipDownloadedHint: '开启后，本地引擎会记录成功下载的媒体 ID；再次下载同一内容时自动跳过。默认关闭。',
    launch: '下载最终成品',
    queueAction: '加入下载队列',
    queueStatus: '队列 {count}/{capacity}',
    currentQueue: '当前任务 · 等待 {count} 项',
    idleQueue: '当前空闲 · 等待 {count} 项',
    queueFull: '下载队列已满',
    queueJobs: '等待队列',
    cancel: '取消当前任务',
    cancelQueued: '取消排队任务',
    queuedCancelled: '已从下载队列移除',
    openFolder: '打开文件夹',
    install: '安装本地引擎',
    githubMirror: 'GitHub 备用线路',
    privacy: '默认只保存最终视频；Cookie、可选下载记录与 FFmpeg 处理留在本机。',
    sent: '任务已发送到 Galaxy Local Engine',
    queued: '任务已加入 Galaxy Local Engine 下载队列',
    launchHint: '需要 Galaxy Local Engine v{version}+。请下载对应版本、完整解压并运行 install.cmd。',
    setup: '安装说明',
    setupHint: '完整解压 ZIP → 放到长期使用目录 → 运行 install.cmd → 保持本地引擎运行。',
  },
  'zh-tw': {
    title: '本機下載', connected: '已連線', disconnected: '未連線', cookieSource: '登入狀態', noCookies: '不讀取 Cookie（預設）', edge: 'Edge 登入狀態', chrome: 'Chrome 登入狀態', firefox: 'Firefox 登入狀態', collection: '合輯範圍', single: '目前一項', all: '整個合輯', selected: '選擇部分', selectedCount: '已選 {count} 項', selectAll: '全選', clear: '清空', skipDownloaded: '略過已下載內容', skipDownloadedHint: '開啟後，本機引擎會記錄成功下載的媒體 ID；再次下載相同內容時自動略過。預設關閉。', launch: '下載最終成品', queueAction: '加入下載佇列', queueStatus: '佇列 {count}/{capacity}', currentQueue: '目前工作 · 等待 {count} 項', idleQueue: '目前閒置 · 等待 {count} 項', queueFull: '下載佇列已滿', queueJobs: '等待佇列', cancel: '取消目前工作', cancelQueued: '取消排隊工作', queuedCancelled: '已從下載佇列移除', openFolder: '開啟資料夾', install: '安裝本機引擎', githubMirror: 'GitHub 備用線路', privacy: '預設只保存最終影片；Cookie、可選下載記錄與 FFmpeg 處理留在本機。', sent: '工作已傳送到 Galaxy Local Engine', queued: '工作已加入 Galaxy Local Engine 下載佇列', launchHint: '需要 Galaxy Local Engine v{version}+。請下載對應版本、完整解壓並執行 install.cmd。', setup: '安裝說明', setupHint: '完整解壓 ZIP → 放到長期使用目錄 → 執行 install.cmd → 保持本機引擎運行。',
  },
  en: {
    title: 'Local download', connected: 'Connected', disconnected: 'Offline', cookieSource: 'Login session', noCookies: 'No cookies (default)', edge: 'Edge session', chrome: 'Chrome session', firefox: 'Firefox session', collection: 'Collection range', single: 'Current item', all: 'Entire collection', selected: 'Choose items', selectedCount: '{count} selected', selectAll: 'Select all', clear: 'Clear', skipDownloaded: 'Skip previously downloaded', skipDownloadedHint: 'When enabled, the local engine records successfully downloaded media IDs and skips them next time. Off by default.', launch: 'Download finished file', queueAction: 'Add to download queue', queueStatus: 'Queue {count}/{capacity}', currentQueue: 'Current job · {count} waiting', idleQueue: 'Idle · {count} waiting', queueFull: 'Download queue is full', queueJobs: 'Waiting queue', cancel: 'Cancel current job', cancelQueued: 'Cancel queued job', queuedCancelled: 'Removed from the download queue', openFolder: 'Open folder', install: 'Install local engine', githubMirror: 'GitHub mirror', privacy: 'Only the finished video is saved by default. Cookies, the optional archive and FFmpeg stay on this device.', sent: 'Job sent to Galaxy Local Engine', queued: 'Job added to the Galaxy Local Engine download queue', launchHint: 'Galaxy Local Engine v{version}+ is required. Download the matching ZIP, extract it fully, and run install.cmd.', setup: 'Setup', setupHint: 'Extract ZIP → move it to a permanent folder → run install.cmd → keep the engine running.',
  },
  ja: {
    title: 'ローカル保存', connected: '接続済み', disconnected: '未接続', cookieSource: 'ログイン状態', noCookies: 'Cookie を使わない（既定）', edge: 'Edge セッション', chrome: 'Chrome セッション', firefox: 'Firefox セッション', collection: 'コレクション範囲', single: '現在の1件', all: 'すべて', selected: '選択', selectedCount: '{count} 件選択', selectAll: 'すべて選択', clear: 'クリア', skipDownloaded: 'ダウンロード済みをスキップ', skipDownloadedHint: '有効にすると、成功したメディア ID を端末内に記録し、次回は同じ内容をスキップします。既定はオフです。', launch: '完成ファイルを保存', queueAction: 'ダウンロード待ちに追加', queueStatus: '待ち {count}/{capacity}', currentQueue: '現在の処理 · 待ち {count} 件', idleQueue: '待機中 · 待ち {count} 件', queueFull: 'ダウンロード待ちが上限です', queueJobs: '待機中', cancel: '現在の処理をキャンセル', cancelQueued: '待機ジョブを取消', queuedCancelled: 'ダウンロード待ちから削除しました', openFolder: 'フォルダーを開く', install: 'ローカルエンジンを導入', githubMirror: 'GitHub ミラー', privacy: '既定では完成動画だけを保存します。Cookie、任意の履歴、FFmpeg 処理は端末内に留まります。', sent: 'ジョブを送信しました', queued: 'ジョブをダウンロード待ちに追加しました', launchHint: 'Galaxy Local Engine v{version}+ が必要です。対応 ZIP を完全に展開し install.cmd を実行してください。', setup: 'セットアップ', setupHint: 'ZIP を展開 → 保存場所へ移動 → install.cmd → エンジンを起動したまま使用。',
  },
  es: {
    title: 'Descarga local', connected: 'Conectado', disconnected: 'Sin conexión', cookieSource: 'Sesión', noCookies: 'Sin cookies (predeterminado)', edge: 'Sesión de Edge', chrome: 'Sesión de Chrome', firefox: 'Sesión Firefox', collection: 'Rango de colección', single: 'Elemento actual', all: 'Toda la colección', selected: 'Elegir elementos', selectedCount: '{count} seleccionados', selectAll: 'Seleccionar todo', clear: 'Limpiar', skipDownloaded: 'Omitir lo ya descargado', skipDownloadedHint: 'Al activarlo, el motor local guarda los ID descargados correctamente y los omite la próxima vez. Desactivado por defecto.', launch: 'Descargar archivo final', queueAction: 'Añadir a la cola', queueStatus: 'Cola {count}/{capacity}', currentQueue: 'Tarea actual · {count} en espera', idleQueue: 'Inactivo · {count} en espera', queueFull: 'La cola está llena', queueJobs: 'Cola de espera', cancel: 'Cancelar tarea actual', cancelQueued: 'Cancelar tarea en cola', queuedCancelled: 'Eliminada de la cola de descargas', openFolder: 'Abrir carpeta', install: 'Instalar motor local', githubMirror: 'Espejo de GitHub', privacy: 'Por defecto solo se guarda el vídeo final. Cookies, archivo opcional y FFmpeg permanecen en este dispositivo.', sent: 'Tarea enviada al motor local', queued: 'Tarea añadida a la cola del motor local', launchHint: 'Se requiere Galaxy Local Engine v{version}+. Descarga el ZIP correspondiente, extráelo y ejecuta install.cmd.', setup: 'Instalación', setupHint: 'Extrae ZIP → mueve la carpeta → ejecuta install.cmd → mantén el motor abierto.',
  },
  ru: {
    title: 'Локальная загрузка', connected: 'Подключено', disconnected: 'Не подключено', cookieSource: 'Сессия', noCookies: 'Без cookies (по умолчанию)', edge: 'Сессия Edge', chrome: 'Сессия Chrome', firefox: 'Сессия Firefox', collection: 'Диапазон коллекции', single: 'Текущий элемент', all: 'Вся коллекция', selected: 'Выбрать элементы', selectedCount: 'Выбрано: {count}', selectAll: 'Выбрать всё', clear: 'Очистить', skipDownloaded: 'Пропускать уже загруженное', skipDownloadedHint: 'Если включено, локальный движок хранит ID успешно загруженных медиа и пропускает их в следующий раз. По умолчанию выключено.', launch: 'Скачать итоговый файл', queueAction: 'Добавить в очередь', queueStatus: 'Очередь {count}/{capacity}', currentQueue: 'Текущая задача · ждут {count}', idleQueue: 'Свободно · ждут {count}', queueFull: 'Очередь загрузок заполнена', queueJobs: 'Ожидающие задачи', cancel: 'Отменить текущую задачу', cancelQueued: 'Отменить задачу в очереди', queuedCancelled: 'Удалено из очереди загрузок', openFolder: 'Открыть папку', install: 'Установить локальный движок', githubMirror: 'Зеркало GitHub', privacy: 'По умолчанию сохраняется только итоговое видео. Cookies, опциональный архив и FFmpeg остаются на устройстве.', sent: 'Задание отправлено', queued: 'Задание добавлено в очередь загрузок', launchHint: 'Требуется Galaxy Local Engine v{version}+. Скачайте соответствующий ZIP, распакуйте и запустите install.cmd.', setup: 'Установка', setupHint: 'Распаковать ZIP → переместить папку → запустить install.cmd → оставить движок запущенным.',
  },
};

function copyFor(pathname: string | null): Copy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
  return COPY[locale] || COPY.en;
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function scopedSingleSourceUrl(result: ResultData): string {
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

function compactItemTitle(value: string, index: number): string {
  const title = value.trim();
  return title || `#${index}`;
}

function scopedSubtitles(result: ResultData): SubtitleTrack[] {
  const currentPage = result.pages?.find((page) => page.page === result.currentPage);
  if (currentPage?.subtitles?.length) return currentPage.subtitles;
  const currentVideo = result.videos?.find((video) => video.id === result.currentItemId);
  if (currentVideo?.subtitles?.length) return currentVideo.subtitles;
  return result.subtitles || [];
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
  const launchHint = copy.launchHint.replace('{version}', LOCAL_ENGINE_REQUIRED_VERSION);
  const collectionItems = useMemo(() => result.pages?.filter((page) => page.page > 0) || [], [result.pages]);
  const subtitleTracks = useMemo(() => scopedSubtitles(result), [result]);
  const hasCollection = collectionItems.length > 1;
  const currentItem = result.currentPage && collectionItems.some((item) => item.page === result.currentPage)
    ? result.currentPage
    : collectionItems[0]?.page || 1;

  const [browser, setBrowser] = useState<LocalEngineBrowser>('none');
  const [bridge, setBridge] = useState<LocalEngineBridgeStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const [cancellingQueuedJobId, setCancellingQueuedJobId] = useState<string | null>(null);
  const [collectionMode, setCollectionMode] = useState<LocalEngineCollectionMode>('single');
  const [selectedItems, setSelectedItems] = useState<number[]>([currentItem]);
  const [skipPreviouslyDownloaded, setSkipPreviouslyDownloaded] = useState(false);
  const [advancedOptions, setAdvancedOptions] = useState<LocalEngineAdvancedOptions>(() => ({
    segmentStart: '',
    segmentEnd: '',
    splitChapters: false,
    subtitleMode: 'both',
    subtitleLanguages: [],
    audioLanguages: [],
    sponsorBlockCategories: [],
    useAria2c: false,
  }));

  const originalSourceUrl = typeof result.url === 'string' ? result.url.trim() : '';
  const singleSourceUrl = scopedSingleSourceUrl(result);
  const sourceUrl = collectionMode === 'single' ? singleSourceUrl : originalSourceUrl;
  const supported = sourceUrl.startsWith('http://') || sourceUrl.startsWith('https://');

  useEffect(() => {
    setCollectionMode('single');
    setSelectedItems([currentItem]);
  }, [currentItem, originalSourceUrl]);

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

  const normalizedSelectedItems = selectedItems.length ? selectedItems : [currentItem];
  const engineCollectionMode: LocalEngineCollectionMode = collectionMode === 'single' && currentItem > 1
    ? 'selected'
    : collectionMode;
  const engineSelectedItems = engineCollectionMode === 'selected'
    ? (collectionMode === 'single' ? [currentItem] : normalizedSelectedItems)
    : undefined;
  const advancedBridge = bridge as AdvancedBridgeStatus | null;

  const localJob: LocalEngineBridgeJob & LocalEngineAdvancedOptions = {
    sourceUrl,
    displayTitle: typeof result.title === 'string' ? result.title : undefined,
    videoQuality: resolveLocalDesktopVideoQuality(plan.videoSelection),
    audioQuality: plan.audioQuality || 'best',
    includeAudio: plan.includeAudio,
    includeSubtitle: plan.includeSubtitle,
    subtitleLanguage: plan.includeSubtitle ? plan.subtitleLanguage || null : null,
    includeCover: plan.includeCover,
    skipPreviouslyDownloaded,
    browser,
    collectionMode: engineCollectionMode,
    selectedItems: engineSelectedItems,
    playlist: engineCollectionMode === 'all',
    ...advancedOptions,
    useAria2c: Boolean(advancedBridge?.aria2Ready && advancedOptions.useAria2c),
  };

  const queueCapacity = bridge?.queueCapacity || 0;
  const queueLength = bridge?.queueLength || 0;
  const queuedJobs = bridge?.queuedJobs || [];
  const queueFull = Boolean(bridge?.busy && queueCapacity > 0 && queueLength >= queueCapacity);
  const queueStatus = copy.queueStatus
    .replace('{count}', String(queueLength))
    .replace('{capacity}', String(queueCapacity || '—'));
  const currentQueueText = (bridge?.busy ? copy.currentQueue : copy.idleQueue)
    .replace('{count}', String(queueLength));

  const setMode = (mode: LocalEngineCollectionMode) => {
    setCollectionMode(mode);
    if (mode === 'selected' && !selectedItems.length) setSelectedItems([currentItem]);
  };

  const toggleItem = (page: number) => {
    setSelectedItems((previous) => previous.includes(page)
      ? previous.filter((item) => item !== page)
      : [...previous, page].sort((a, b) => a - b));
  };

  const handleLaunch = async () => {
    if (
      disabled
      || launching
      || queueFull
      || (collectionMode === 'selected' && selectedItems.length === 0)
    ) return;

    setLaunching(true);
    try {
      if (bridge) {
        const wasBusy = bridge.busy;
        const message = await submitLocalEngineBridgeJob(localJob);
        toast.success(wasBusy ? copy.queued : copy.sent, wasBusy ? { description: message } : undefined);
        await refreshBridge();
        return;
      }

      launchLocalDesktopEngine(localJob);
      for (let attempt = 0; attempt < 10; attempt += 1) {
        await sleep(attempt === 0 ? 500 : 700);
        const next = await refreshBridge();
        if (next) {
          toast.success(copy.sent);
          return;
        }
      }
      toast.message(launchHint);
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

  const handleCancelQueued = async (jobId: string) => {
    if (cancellingQueuedJobId) return;
    setCancellingQueuedJobId(jobId);
    try {
      await cancelLocalEngineQueuedJob(jobId);
      await refreshBridge();
      toast.success(copy.queuedCancelled);
    } catch (error) {
      await refreshBridge();
      if (error instanceof LocalEngineBridgeSubmissionError && error.code === 'QUEUE_ITEM_NOT_FOUND') return;
      toast.error(copy.cancelQueued, { description: error instanceof Error ? error.message : String(error) });
    } finally {
      setCancellingQueuedJobId(null);
    }
  };

  const handleOpenFolder = async () => {
    try {
      await openLocalEngineDownloadFolder();
    } catch (error) {
      toast.error(copy.openFolder, { description: error instanceof Error ? error.message : String(error) });
    }
  };

  const modeButton = (mode: LocalEngineCollectionMode, label: string) => (
    <button
      type="button"
      aria-pressed={collectionMode === mode}
      disabled={disabled}
      onClick={() => setMode(mode)}
      className={`h-8 rounded-md px-2 text-[11px] font-medium outline-none transition-[background-color,color,transform] duration-150 active:scale-[0.96] focus-visible:ring-2 focus-visible:ring-ring ${
        collectionMode === mode
          ? 'bg-foreground text-background'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
      }`}
    >
      {label}
    </button>
  );

  return (
    <section className="min-w-0 border-t pt-3">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${bridge ? 'bg-emerald-600' : 'bg-muted-foreground/35'}`}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1 truncate text-sm font-medium">
          {copy.title}
          <span className="ms-2 text-[11px] font-normal text-muted-foreground">
            {bridge ? `${copy.connected} · v${bridge.version}` : copy.disconnected}
          </span>
          {bridge ? (
            <span className="ms-2 text-[10px] font-normal tabular-nums text-muted-foreground">
              {currentQueueText}
            </span>
          ) : null}
        </div>
        {bridge ? (
          <Button type="button" variant="ghost" size="xs" className="shrink-0 text-muted-foreground hover:text-foreground" onClick={() => void handleOpenFolder()}>
            <FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />
            {copy.openFolder}
          </Button>
        ) : null}
      </div>

      {bridge?.busy ? (
        <div className="mt-3 space-y-1.5" role="status" aria-live="polite">
          <div className="flex items-center justify-between gap-3 text-[11px] text-muted-foreground">
            <span className="min-w-0 truncate">{bridge.detail || bridge.status}</span>
            <span className="shrink-0 tabular-nums">{Math.round(bridge.progress)}%</span>
          </div>
          <div className="h-1 overflow-hidden bg-muted">
            <div className="h-full bg-foreground transition-[width] duration-300" style={{ width: `${bridge.progress}%` }} />
          </div>
          <div className="flex justify-between gap-3 text-[10px] tabular-nums text-muted-foreground">
            <span>{bridge.speed}</span><span>{bridge.downloaded}</span><span>ETA {bridge.eta}</span>
          </div>
        </div>
      ) : null}

      {queuedJobs.length > 0 ? (
        <div className="mt-3 border-y" aria-label={copy.queueJobs}>
          <div className="flex min-h-8 items-center justify-between gap-2 px-1 text-[11px] font-medium">
            <span>{copy.queueJobs}</span>
            <span className="tabular-nums text-muted-foreground">{queueStatus}</span>
          </div>
          <div className="divide-y border-t">
            {queuedJobs.map((queuedJob) => {
              const cancelling = cancellingQueuedJobId === queuedJob.id;
              return (
                <div key={queuedJob.id} className="flex min-h-9 min-w-0 items-center gap-2 px-1 py-1">
                  <span className="w-6 shrink-0 text-[10px] tabular-nums text-muted-foreground">#{queuedJob.position}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium" title={queuedJob.label}>{queuedJob.label}</div>
                    {queuedJob.sourceHost && queuedJob.sourceHost !== queuedJob.label ? (
                      <div className="truncate text-[10px] text-muted-foreground">{queuedJob.sourceHost}</div>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    disabled={disabled || cancellingQueuedJobId !== null}
                    onClick={() => void handleCancelQueued(queuedJob.id)}
                    aria-label={`${copy.cancelQueued}: ${queuedJob.label}`}
                    title={copy.cancelQueued}
                    className="ui-pressable inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50"
                  >
                    {cancelling ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <X className="h-3.5 w-3.5" aria-hidden="true" />}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className={`mt-3 grid gap-2 ${hasCollection ? 'lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]' : ''}`}>
        <label className="space-y-1.5 text-[11px] font-medium text-muted-foreground">
          <span>{copy.cookieSource}</span>
          <Select value={browser} onValueChange={(value) => setBrowser(value as LocalEngineBrowser)} disabled={disabled}>
            <SelectTrigger className="h-8 bg-background text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{copy.noCookies}</SelectItem>
              <SelectItem value="edge">{copy.edge}</SelectItem>
              <SelectItem value="chrome">{copy.chrome}</SelectItem>
              <SelectItem value="firefox">{copy.firefox}</SelectItem>
            </SelectContent>
          </Select>
        </label>

        {hasCollection ? (
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium text-muted-foreground">{copy.collection}</div>
            <div className="grid grid-cols-3 gap-0.5 rounded-md border bg-background p-0.5">
              {modeButton('single', copy.single)}
              {modeButton('all', copy.all)}
              {modeButton('selected', copy.selected)}
            </div>
          </div>
        ) : null}
      </div>

      <label className="mt-2 flex cursor-pointer items-start gap-2 border-y py-2 text-[11px] text-muted-foreground" title={copy.skipDownloadedHint}>
        <input
          type="checkbox"
          checked={skipPreviouslyDownloaded}
          disabled={disabled}
          onChange={(event) => setSkipPreviouslyDownloaded(event.target.checked)}
          className="mt-0.5 h-3.5 w-3.5 accent-foreground"
        />
        <span className="min-w-0">
          <span className="font-medium text-foreground">{copy.skipDownloaded}</span>
          <span className="ms-1.5 opacity-80">{copy.skipDownloadedHint}</span>
        </span>
      </label>

      {hasCollection && collectionMode === 'selected' ? (
        <div className="mt-2 border-t pt-2">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium">{copy.selectedCount.replace('{count}', String(selectedItems.length))}</span>
            <div className="flex items-center gap-1 text-[11px]">
              <button type="button" disabled={disabled} className="rounded px-1.5 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-50" onClick={() => setSelectedItems(collectionItems.map((item) => item.page))}>{copy.selectAll}</button>
              <button type="button" disabled={disabled} className="rounded px-1.5 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-50" onClick={() => setSelectedItems([])}>{copy.clear}</button>
            </div>
          </div>
          <div className="max-h-36 divide-y overflow-y-auto border-y">
            {collectionItems.map((item, index) => {
              const checked = selectedItems.includes(item.page);
              return (
                <label key={`${item.page}-${item.cid}`} className="flex min-h-8 cursor-pointer items-center gap-2 px-1 py-1 text-xs hover:bg-muted/60">
                  <input type="checkbox" disabled={disabled} checked={checked} onChange={() => toggleItem(item.page)} className="h-3.5 w-3.5 accent-foreground" />
                  <span className="w-8 shrink-0 tabular-nums text-muted-foreground">#{item.page}</span>
                  <span className={`min-w-0 flex-1 truncate ${checked ? 'font-medium' : ''}`}>{compactItemTitle(item.part, index + 1)}</span>
                  {checked ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : null}
                </label>
              );
            })}
          </div>
        </div>
      ) : null}

      <LocalEngineAdvancedControls
        value={advancedOptions}
        onChange={setAdvancedOptions}
        disabled={disabled || launching}
        aria2Ready={Boolean(advancedBridge?.aria2Ready)}
        subtitles={subtitleTracks}
      />

      <div className="mt-3 grid gap-1.5 sm:grid-cols-2">
        {bridge?.busy ? (
          <>
            <Button type="button" variant="destructive" size="sm" onClick={() => void handleCancel()}>
              <X className="h-4 w-4" aria-hidden="true" />{copy.cancel}
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => void handleLaunch()}
              disabled={disabled || launching || queueFull || (collectionMode === 'selected' && selectedItems.length === 0)}
            >
              {launching ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <HardDriveDownload className="h-4 w-4" aria-hidden="true" />}
              {queueFull ? copy.queueFull : copy.queueAction}
            </Button>
          </>
        ) : (
          <Button
            type="button"
            size="sm"
            className={bridge ? 'sm:col-span-2' : undefined}
            onClick={() => void handleLaunch()}
            disabled={disabled || launching || (collectionMode === 'selected' && selectedItems.length === 0)}
          >
            {launching ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <HardDriveDownload className="h-4 w-4" aria-hidden="true" />}
            {copy.launch}
          </Button>
        )}

        {!bridge ? (
          <Button type="button" variant="outline" size="sm" asChild>
            <a href={LOCAL_ENGINE_RELEASE_URL}>{copy.install}</a>
          </Button>
        ) : null}
      </div>

      {!bridge ? (
        <details className="group mt-2 border-t pt-1 text-[11px] text-muted-foreground">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-md px-0.5 py-1.5 outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronDown className="h-3.5 w-3.5 transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
            {copy.setup}
          </summary>
          <div className="ms-1.5 mt-1 space-y-1.5 border-s ps-3 leading-5">
            <p>{copy.setupHint}</p>
            <a href={LOCAL_ENGINE_GITHUB_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-4 hover:text-foreground">
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />{copy.githubMirror}
            </a>
            <p>{launchHint}</p>
          </div>
        </details>
      ) : null}

      <p className="mt-2 text-[10px] leading-4 text-muted-foreground">{copy.privacy}</p>
    </section>
  );
}
