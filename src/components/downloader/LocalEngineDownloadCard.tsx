'use client';

import { useMemo, useState } from 'react';
import { usePathname } from 'next/navigation';
import { ExternalLink, HardDriveDownload, ShieldCheck } from 'lucide-react';

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
    install: '安装本地引擎',
    privacy: 'Cookie、视频和 FFmpeg 处理全部留在你的电脑，不上传 Galaxy 服务器。',
    launchHint: '如果点击后没有打开程序，请先安装 Galaxy Local Engine。',
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
    install: '安裝本地引擎',
    privacy: 'Cookie、影片與 FFmpeg 處理全部保留在你的電腦。',
    launchHint: '如果點擊後沒有開啟程式，請先安裝 Galaxy Local Engine。',
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
    install: 'Install local engine',
    privacy: 'Cookies, media and FFmpeg processing stay on this computer and are not uploaded to Galaxy servers.',
    launchHint: 'If no app opens, install Galaxy Local Engine first.',
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
    install: 'ローカルエンジンをインストール',
    privacy: 'Cookie、メディア、FFmpeg 処理はこの PC 内だけで行われます。',
    launchHint: 'アプリが開かない場合は Galaxy Local Engine を先にインストールしてください。',
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
    install: 'Instalar motor local',
    privacy: 'Las cookies, el contenido y FFmpeg permanecen en este equipo.',
    launchHint: 'Si no se abre ninguna aplicación, instala primero Galaxy Local Engine.',
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
    install: 'Установить локальный движок',
    privacy: 'Cookies, медиа и обработка FFmpeg остаются только на этом компьютере.',
    launchHint: 'Если приложение не открылось, сначала установите Galaxy Local Engine.',
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

  const supported = useMemo(
    () => sourceUrl.startsWith('http://') || sourceUrl.startsWith('https://'),
    [sourceUrl],
  );
  if (!supported) return null;

  const handleLaunch = () => {
    if (disabled) return;
    launchLocalDesktopEngine({
      sourceUrl,
      videoQuality: resolveLocalDesktopVideoQuality(plan.videoSelection),
      audioQuality: plan.audioQuality || 'best',
      includeAudio: plan.includeAudio,
      includeSubtitle: plan.includeSubtitle,
      subtitleLanguage: plan.includeSubtitle ? plan.subtitleLanguage || null : null,
      includeCover: plan.includeCover,
      browser,
      playlist: false,
    });
    window.setTimeout(() => toast.message(copy.launchHint), 1200);
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

        <div className="space-y-2">
          <label className="text-xs font-medium text-muted-foreground">{copy.cookieSource}</label>
          <Select
            value={browser}
            onValueChange={(value) => setBrowser(value as LocalEngineBrowser)}
            disabled={disabled}
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
          <Button
            type="button"
            className="min-h-11 w-full font-semibold"
            onClick={handleLaunch}
            disabled={disabled}
          >
            <HardDriveDownload className="h-4 w-4" aria-hidden="true" />
            {copy.launch}
          </Button>
          <Button type="button" variant="outline" className="min-h-10 w-full" asChild>
            <a href={LOCAL_ENGINE_RELEASE_URL} target="_blank" rel="noreferrer">
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              {copy.install}
            </a>
          </Button>
        </div>

        <div className="flex items-start gap-2 border-t border-primary/10 pt-3 text-xs leading-5 text-muted-foreground">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
          <span>{copy.privacy}</span>
        </div>
      </div>
    </section>
  );
}
