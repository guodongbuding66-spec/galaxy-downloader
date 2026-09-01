'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import { BookOpen, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { toast } from '@/lib/deferred-toast';
import { LOCAL_ENGINE_REQUIRED_VERSION } from '@/lib/local-engine';
import { submitLocalImageDownload } from '@/lib/local-image-engine';
import { sanitizeFilename } from '@/lib/utils';

type Copy = {
  cbz: string;
  hint: string;
  sent: string;
  unavailable: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    cbz: '导出 CBZ',
    hint: '长期归档：CBZ 与本机 ZIP 都会写入 metadata.json，包含作者、发布时间、来源、平台、原图 URL 与本地文件映射。',
    sent: 'CBZ 归档任务已发送到本地引擎',
    unavailable: `需要 Galaxy Local Engine v${LOCAL_ENGINE_REQUIRED_VERSION}+ 才能生成 CBZ 与完整 metadata.json。`,
  },
  'zh-tw': {
    cbz: '匯出 CBZ',
    hint: '長期封存：CBZ 與本機 ZIP 都會寫入 metadata.json，包含作者、發布時間、來源、平台、原圖 URL 與本機檔案對應。',
    sent: 'CBZ 封存工作已傳送到本機引擎',
    unavailable: `需要 Galaxy Local Engine v${LOCAL_ENGINE_REQUIRED_VERSION}+ 才能產生 CBZ 與完整 metadata.json。`,
  },
  en: {
    cbz: 'Export CBZ',
    hint: 'Long-term archives: CBZ and Local Engine ZIP packages include metadata.json with author, date, source, platform, original image URLs and local-file mapping.',
    sent: 'CBZ archive job sent to the Local Engine',
    unavailable: `Galaxy Local Engine v${LOCAL_ENGINE_REQUIRED_VERSION}+ is required for CBZ and complete metadata.json archives.`,
  },
  ja: {
    cbz: 'CBZを書き出す',
    hint: '長期保存用の CBZ / ローカル ZIP には、作者・公開日時・元 URL・プラットフォーム・画像 URL・ローカル対応表を含む metadata.json を保存します。',
    sent: 'CBZ 保存ジョブをローカルエンジンへ送信しました',
    unavailable: `CBZ と完全な metadata.json には Galaxy Local Engine v${LOCAL_ENGINE_REQUIRED_VERSION}+ が必要です。`,
  },
  es: {
    cbz: 'Exportar CBZ',
    hint: 'Los archivos CBZ y ZIP locales incluyen metadata.json con autor, fecha, fuente, plataforma, URL originales y la relación de archivos locales.',
    sent: 'Tarea CBZ enviada al motor local',
    unavailable: `Se requiere Galaxy Local Engine v${LOCAL_ENGINE_REQUIRED_VERSION}+ para CBZ y metadata.json completo.`,
  },
  ru: {
    cbz: 'Экспорт CBZ',
    hint: 'CBZ и локальные ZIP-архивы содержат metadata.json с автором, датой, источником, платформой, исходными URL и соответствием локальных файлов.',
    sent: 'Задача CBZ отправлена локальному движку',
    unavailable: `Для CBZ и полного metadata.json требуется Galaxy Local Engine v${LOCAL_ENGINE_REQUIRED_VERSION}+.`,
  },
};

function copyFor(pathname: string | null): Copy {
  const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
  return COPY[locale] || COPY.en;
}

export function ImageArchiveActions({
  images,
  title,
  description,
  markdownContent,
  author,
  publishedAt,
  sourceUrl,
  platform,
}: {
  images: string[];
  title: string;
  description?: string | null;
  markdownContent?: string | null;
  author?: string | null;
  publishedAt?: string | null;
  sourceUrl?: string | null;
  platform?: string | null;
}) {
  const pathname = usePathname();
  const copy = copyFor(pathname);
  const [running, setRunning] = useState(false);

  if (images.length < 2) return null;

  const exportCbz = async () => {
    if (running) return;
    setRunning(true);
    try {
      const submission = await submitLocalImageDownload({
        images,
        title: sanitizeFilename(title),
        sourceUrl,
        platform,
        package: true,
        archiveFormat: 'cbz',
        description,
        markdownContent,
        author,
        publishedAt,
      });
      if (submission.accepted) {
        toast.success('Galaxy Local Engine', { description: copy.sent });
        return;
      }
      if (!submission.available) {
        toast.error('Galaxy Local Engine', { description: copy.unavailable });
        return;
      }
      toast.error('Galaxy Local Engine', { description: submission.message || copy.unavailable });
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-y py-2">
      <p className="min-w-0 flex-1 text-[10px] leading-4 text-muted-foreground">{copy.hint}</p>
      <Button type="button" size="xs" variant="outline" disabled={running} onClick={() => void exportCbz()}>
        {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <BookOpen className="h-3.5 w-3.5" aria-hidden="true" />}
        {copy.cbz}
      </Button>
    </div>
  );
}
