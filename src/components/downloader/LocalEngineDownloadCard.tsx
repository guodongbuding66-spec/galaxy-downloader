'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import {
  Check,
  ChevronDown,
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
  type LocalEngineCollectionMode,
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
  launch: string;
  cancel: string;
  openFolder: string;
  install: string;
  githubMirror: string;
  privacy: string;
  sent: string;
  launchHint: string;
  setup: string;
  setupHint: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    title: '本机下载',
    connected: '本地引擎已连接',
    disconnected: '本地引擎未连接',
    cookieSource: '登录状态',
    noCookies: '不读取 Cookie（默认）',
    edge: 'Edge 登录状态',
    chrome: 'Chrome 登录状态',
    firefox: 'Firefox 登录状态',
    collection: '合集范围',
    single: '只下载当前一项',
    all: '下载整个合集',
    selected: '选择部分',
    selectedCount: '已选 {count} 项',
    selectAll: '全选',
    clear: '清空',
    launch: '按当前方案下载',
    cancel: '取消任务',
    openFolder: '打开文件夹',
    install: '下载本地引擎',
    githubMirror: 'GitHub 备用线路',
    privacy: '默认只输出最终视频；封面仅在勾选时嵌入，不单独保存。Cookie 与 FFmpeg 处理留在本机。',
    sent: '任务已发送到 Galaxy Local Engine',
    launchHint: '需要 Galaxy Local Engine v0.5.0+。请下载最新版、完整解压并运行 install.cmd。',
    setup: '首次使用 / 安装说明',
    setupHint: '完整解压 ZIP → 放到长期使用目录 → 运行 install.cmd → 保持本地引擎运行。',
  },
  'zh-tw': {
    title: '本機下載', connected: '本機引擎已連線', disconnected: '本機引擎未連線', cookieSource: '登入狀態', noCookies: '不讀取 Cookie（預設）', edge: 'Edge 登入狀態', chrome: 'Chrome 登入狀態', firefox: 'Firefox 登入狀態', collection: '合輯範圍', single: '只下載目前一項', all: '下載整個合輯', selected: '選擇部分', selectedCount: '已選 {count} 項', selectAll: '全選', clear: '清空', launch: '依目前方案下載', cancel: '取消工作', openFolder: '開啟資料夾', install: '下載本機引擎', githubMirror: 'GitHub 備用線路', privacy: '預設只輸出最終影片；封面只在勾選時嵌入，不另外保存。Cookie 與 FFmpeg 處理留在本機。', sent: '工作已傳送到 Galaxy Local Engine', launchHint: '需要 Galaxy Local Engine v0.5.0+。請下載最新版、完整解壓並執行 install.cmd。', setup: '首次使用 / 安裝說明', setupHint: '完整解壓 ZIP → 放到長期使用目錄 → 執行 install.cmd → 保持本機引擎運行。',
  },
  en: {
    title: 'Local download', connected: 'Local engine connected', disconnected: 'Local engine offline', cookieSource: 'Login session', noCookies: 'No cookies (default)', edge: 'Edge session', chrome: 'Chrome session', firefox: 'Firefox session', collection: 'Collection range', single: 'Current item only', all: 'Entire collection', selected: 'Choose items', selectedCount: '{count} selected', selectAll: 'Select all', clear: 'Clear', launch: 'Download current plan', cancel: 'Cancel', openFolder: 'Open folder', install: 'Download local engine', githubMirror: 'GitHub mirror', privacy: 'The default output is one finished video. Covers are embedded only when enabled and are not kept as sidecar files.', sent: 'Job sent to Galaxy Local Engine', launchHint: 'Galaxy Local Engine v0.5.0+ is required. Download the latest ZIP, extract it fully, and run install.cmd.', setup: 'First-time setup', setupHint: 'Extract ZIP → move it to a permanent folder → run install.cmd → keep the engine running.',
  },
  ja: {
    title: 'ローカル保存', connected: 'ローカルエンジン接続済み', disconnected: 'ローカルエンジン未接続', cookieSource: 'ログイン状態', noCookies: 'Cookie を使わない（既定）', edge: 'Edge セッション', chrome: 'Chrome セッション', firefox: 'Firefox セッション', collection: 'コレクション範囲', single: '現在の1件のみ', all: 'すべて', selected: '選択', selectedCount: '{count} 件選択', selectAll: 'すべて選択', clear: 'クリア', launch: '現在の設定で保存', cancel: 'キャンセル', openFolder: 'フォルダーを開く', install: 'ローカルエンジンを取得', githubMirror: 'GitHub ミラー', privacy: '既定では完成動画1本だけを保存します。カバーは有効時のみ埋め込み、別ファイルにはしません。', sent: 'ジョブを送信しました', launchHint: 'Galaxy Local Engine v0.5.0+ が必要です。ZIP を完全に展開し install.cmd を実行してください。', setup: '初回セットアップ', setupHint: 'ZIP を展開 → 保存場所へ移動 → install.cmd → エンジンを起動したまま使用。',
  },
  es: {
    title: 'Descarga local', connected: 'Motor local conectado', disconnected: 'Motor local desconectado', cookieSource: 'Sesión', noCookies: 'Sin cookies (predeterminado)', edge: 'Sesión de Edge', chrome: 'Sesión de Chrome', firefox: 'Sesión de Firefox', collection: 'Rango de colección', single: 'Solo el elemento actual', all: 'Toda la colección', selected: 'Elegir elementos', selectedCount: '{count} seleccionados', selectAll: 'Seleccionar todo', clear: 'Limpiar', launch: 'Descargar plan actual', cancel: 'Cancelar', openFolder: 'Abrir carpeta', install: 'Descargar motor local', githubMirror: 'Espejo de GitHub', privacy: 'Por defecto solo se guarda el vídeo final. La portada se incrusta cuando se activa y no se conserva como archivo separado.', sent: 'Tarea enviada al motor local', launchHint: 'Se requiere Galaxy Local Engine v0.5.0+. Descarga el ZIP, extráelo y ejecuta install.cmd.', setup: 'Configuración inicial', setupHint: 'Extrae ZIP → mueve la carpeta → ejecuta install.cmd → mantén el motor abierto.',
  },
  ru: {
    title: 'Локальная загрузка', connected: 'Локальный движок подключён', disconnected: 'Локальный движок не подключён', cookieSource: 'Сессия', noCookies: 'Без cookies (по умолчанию)', edge: 'Сессия Edge', chrome: 'Сессия Chrome', firefox: 'Сессия Firefox', collection: 'Диапазон коллекции', single: 'Только текущий элемент', all: 'Вся коллекция', selected: 'Выбрать элементы', selectedCount: 'Выбрано: {count}', selectAll: 'Выбрать всё', clear: 'Очистить', launch: 'Скачать текущий план', cancel: 'Отменить', openFolder: 'Открыть папку', install: 'Скачать локальный движок', githubMirror: 'Зеркало GitHub', privacy: 'По умолчанию сохраняется один итоговый видеофайл. Обложка встраивается только при включении и не сохраняется отдельно.', sent: 'Задание отправлено', launchHint: 'Требуется Galaxy Local Engine v0.5.0+. Распакуйте ZIP и запустите install.cmd.', setup: 'Первоначальная настройка', setupHint: 'Распаковать ZIP → переместить папку → запустить install.cmd → оставить движок запущенным.',
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
  const collectionItems = useMemo(() => result.pages?.filter((page) => page.page > 0) || [], [result.pages]);
  const hasCollection = collectionItems.length > 1;
  const currentItem = result.currentPage && collectionItems.some((item) => item.page === result.currentPage)
    ? result.currentPage
    : collectionItems[0]?.page || 1;

  const [browser, setBrowser] = useState<LocalEngineBrowser>('none');
  const [bridge, setBridge] = useState<LocalEngineBridgeStatus | null>(null);
  const [launching, setLaunching] = useState(false);
  const [collectionMode, setCollectionMode] = useState<LocalEngineCollectionMode>('single');
  const [selectedItems, setSelectedItems] = useState<number[]>([currentItem]);

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

  const localJob: LocalEngineBridgeJob = {
    sourceUrl,
    videoQuality: resolveLocalDesktopVideoQuality(plan.videoSelection),
    audioQuality: plan.audioQuality || 'best',
    includeAudio: plan.includeAudio,
    includeSubtitle: plan.includeSubtitle,
    subtitleLanguage: plan.includeSubtitle ? plan.subtitleLanguage || null : null,
    includeCover: plan.includeCover,
    browser,
    collectionMode: engineCollectionMode,
    selectedItems: engineSelectedItems,
    playlist: engineCollectionMode === 'all',
  };

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
    if (disabled || launching || (collectionMode === 'selected' && selectedItems.length === 0)) return;
    setLaunching(true);
    try {
      if (bridge) {
        await submitLocalEngineBridgeJob(localJob);
        toast.success(copy.sent);
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

  const modeButton = (mode: LocalEngineCollectionMode, label: string) => (
    <button
      type="button"
      aria-pressed={collectionMode === mode}
      disabled={disabled || bridge?.busy}
      onClick={() => setMode(mode)}
      className={`min-h-9 rounded-lg px-2.5 text-xs font-medium outline-none transition-[background-color,color,transform] duration-150 active:scale-[0.96] focus-visible:ring-2 focus-visible:ring-ring ${
        collectionMode === mode
          ? 'bg-foreground text-background'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'
      }`}
    >
      {label}
    </button>
  );

  return (
    <section className="min-w-0 rounded-xl bg-muted/20 p-3 ring-1 ring-border/70">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {bridge ? (
            <CircleCheck className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
          ) : (
            <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-muted-foreground/40" />
          )}
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold">{copy.title}</div>
            <div className="truncate text-[11px] text-muted-foreground">
              {bridge ? `${copy.connected} · v${bridge.version}` : copy.disconnected}
            </div>
          </div>
        </div>
        {bridge ? (
          <Button type="button" variant="ghost" size="sm" className="h-8 px-2 text-xs" onClick={() => void handleOpenFolder()}>
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
          <div className="h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-foreground transition-[width] duration-300" style={{ width: `${bridge.progress}%` }} />
          </div>
          <div className="flex justify-between gap-3 text-[10px] tabular-nums text-muted-foreground">
            <span>{bridge.speed}</span><span>{bridge.downloaded}</span><span>ETA {bridge.eta}</span>
          </div>
        </div>
      ) : (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground">{copy.cookieSource}</label>
            <Select value={browser} onValueChange={(value) => setBrowser(value as LocalEngineBrowser)} disabled={disabled}>
              <SelectTrigger className="h-9 bg-background text-xs">
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

          {hasCollection ? (
            <div className="space-y-1.5">
              <div className="text-[11px] font-medium text-muted-foreground">{copy.collection}</div>
              <div className="grid grid-cols-3 gap-1 rounded-xl bg-background p-1 ring-1 ring-border/70">
                {modeButton('single', copy.single)}
                {modeButton('all', copy.all)}
                {modeButton('selected', copy.selected)}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {!bridge?.busy && hasCollection && collectionMode === 'selected' ? (
        <div className="mt-3 rounded-xl bg-background p-2 ring-1 ring-border/70">
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <span className="text-xs font-medium">{copy.selectedCount.replace('{count}', String(selectedItems.length))}</span>
            <div className="flex items-center gap-1">
              <button type="button" className="rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground" onClick={() => setSelectedItems(collectionItems.map((item) => item.page))}>{copy.selectAll}</button>
              <button type="button" className="rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground" onClick={() => setSelectedItems([])}>{copy.clear}</button>
            </div>
          </div>
          <div className="max-h-40 space-y-1 overflow-y-auto pr-1">
            {collectionItems.map((item, index) => {
              const checked = selectedItems.includes(item.page);
              return (
                <label key={`${item.page}-${item.cid}`} className="flex min-h-9 cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors hover:bg-muted/70">
                  <input type="checkbox" checked={checked} onChange={() => toggleItem(item.page)} className="h-3.5 w-3.5 accent-foreground" />
                  <span className="w-8 shrink-0 tabular-nums text-muted-foreground">#{item.page}</span>
                  <span className="min-w-0 flex-1 truncate">{compactItemTitle(item.part, index + 1)}</span>
                  {checked ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : null}
                </label>
              );
            })}
          </div>
        </div>
      ) : null}

      <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]">
        {bridge?.busy ? (
          <Button type="button" variant="destructive" className="min-h-10 transition-transform duration-150 active:scale-[0.98]" onClick={() => void handleCancel()}>
            <X className="h-4 w-4" aria-hidden="true" />{copy.cancel}
          </Button>
        ) : (
          <Button
            type="button"
            className="min-h-10 transition-transform duration-150 active:scale-[0.98]"
            onClick={() => void handleLaunch()}
            disabled={disabled || launching || (collectionMode === 'selected' && selectedItems.length === 0)}
          >
            {launching ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <HardDriveDownload className="h-4 w-4" aria-hidden="true" />}
            {copy.launch}
          </Button>
        )}

        {!bridge ? (
          <Button type="button" variant="outline" className="min-h-10 transition-transform duration-150 active:scale-[0.98]" asChild>
            <a href={LOCAL_ENGINE_RELEASE_URL}>{copy.install}</a>
          </Button>
        ) : null}
      </div>

      {!bridge ? (
        <details className="group mt-2 rounded-lg text-xs text-muted-foreground">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 rounded-lg px-1 py-1.5 outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronDown className="h-3.5 w-3.5 transition-transform duration-150 group-open:rotate-180" aria-hidden="true" />
            {copy.setup}
          </summary>
          <div className="mt-1 space-y-2 rounded-lg bg-background p-2.5 ring-1 ring-border/70">
            <p className="leading-5">{copy.setupHint}</p>
            <a href={LOCAL_ENGINE_GITHUB_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline underline-offset-4">
              <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />{copy.githubMirror}
            </a>
            <p className="leading-5">{copy.launchHint}</p>
          </div>
        </details>
      ) : null}

      <div className="mt-2 flex items-start gap-1.5 text-[10px] leading-4 text-muted-foreground">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>{copy.privacy}</span>
      </div>
    </section>
  );
}
