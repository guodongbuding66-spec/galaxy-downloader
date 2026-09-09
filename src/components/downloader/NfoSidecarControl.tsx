'use client';

import { usePathname } from 'next/navigation';

import type { LocalEngineAdvancedOptions } from '@/lib/local-engine';

type Copy = {
  label: string;
  ready: string;
  checking: string;
  missing: string;
};

const COPY: Record<string, Copy> = {
  zh: {
    label: '生成 NFO 元数据文件',
    ready: '在媒体旁生成 Kodi / Jellyfin 可读取的 .nfo 元数据；不会改变视频文件本身。默认关闭。',
    checking: '正在确认本地引擎是否支持 NFO 元数据…',
    missing: '当前本地引擎未声明 NFO sidecar 能力，请升级并保持本地引擎运行。',
  },
  'zh-tw': {
    label: '產生 NFO 中繼資料檔',
    ready: '在媒體旁產生 Kodi / Jellyfin 可讀取的 .nfo 中繼資料；不會改變影片本身。預設關閉。',
    checking: '正在確認本機引擎是否支援 NFO 中繼資料…',
    missing: '目前本機引擎未宣告 NFO sidecar 能力，請升級並保持本機引擎執行。',
  },
  en: {
    label: 'Generate NFO metadata sidecar',
    ready: 'Create a Kodi / Jellyfin-readable .nfo beside the media without modifying the media file. Off by default.',
    checking: 'Checking Local Engine NFO-sidecar support…',
    missing: 'The current Local Engine does not advertise NFO-sidecar support. Upgrade it and keep it running.',
  },
  ja: {
    label: 'NFO メタデータを別ファイルで保存',
    ready: 'Kodi / Jellyfin で読める .nfo をメディアの横に作成します。動画自体は変更しません。既定オフ。',
    checking: 'ローカルエンジンの NFO 対応を確認中…',
    missing: '現在のローカルエンジンは NFO sidecar 対応を宣言していません。更新して起動してください。',
  },
  es: {
    label: 'Generar metadatos NFO',
    ready: 'Crea un .nfo compatible con Kodi / Jellyfin junto al archivo sin modificar el medio. Desactivado por defecto.',
    checking: 'Comprobando si el motor local admite NFO…',
    missing: 'El motor local actual no anuncia soporte para NFO sidecar. Actualízalo y mantenlo en ejecución.',
  },
  ru: {
    label: 'Создавать файл метаданных NFO',
    ready: 'Создавать рядом с медиа .nfo для Kodi / Jellyfin, не изменяя сам медиафайл. По умолчанию выключено.',
    checking: 'Проверяем поддержку NFO локальным движком…',
    missing: 'Текущий локальный движок не заявляет поддержку NFO sidecar. Обновите и запустите его.',
  },
};

function locale(pathname: string | null): string {
  return pathname?.split('/').filter(Boolean)[0] || 'en';
}

export function NfoSidecarControl({
  value,
  onChange,
  capability,
  disabled = false,
}: {
  value: LocalEngineAdvancedOptions;
  onChange: (next: LocalEngineAdvancedOptions) => void;
  capability: boolean | null;
  disabled?: boolean;
}) {
  const pathname = usePathname();
  const copy = COPY[locale(pathname)] || COPY.en;
  const ready = capability === true;
  const hint = capability === null ? copy.checking : ready ? copy.ready : copy.missing;

  return (
    <section className="rounded-lg border bg-background/60 p-2.5">
      <label className={`flex items-start gap-2 text-[10px] ${ready ? 'cursor-pointer' : 'cursor-not-allowed opacity-60'}`}>
        <input
          type="checkbox"
          checked={ready && Boolean(value.includeNfo)}
          disabled={disabled || !ready}
          onChange={(event) => onChange({ ...value, includeNfo: event.target.checked })}
          className="mt-0.5 h-3.5 w-3.5 accent-foreground"
        />
        <span>
          <span className="block text-[11px] font-medium text-foreground">{copy.label}</span>
          <span className="mt-0.5 block leading-4 text-muted-foreground">{hint}</span>
        </span>
      </label>
    </section>
  );
}
