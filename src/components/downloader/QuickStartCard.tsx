import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HardDriveDownload, Play, PlayCircle } from 'lucide-react';
import type { Dictionary } from '@/lib/i18n/types';
import type { Locale } from '@/lib/i18n/config';
import { LOCAL_ENGINE_RELEASE_URL } from '@/lib/local-engine';

interface QuickStartCardProps {
    dict: Pick<Dictionary, 'guide'>;
    locale: Locale;
}

type QuickStartCopy = {
    title: string;
    engineTitle: string;
    engineDescription: string;
    download: string;
    open: string;
};

const COPY: Record<string, QuickStartCopy> = {
    zh: {
        title: '四步轻松下载',
        engineTitle: '下载安装并打开本地引擎',
        engineDescription: '首次使用先下载 Galaxy Local Engine，完整解压后运行 install.cmd，再打开引擎并确认页面显示“本地引擎已连接”。',
        download: '下载引擎',
        open: '打开引擎',
    },
    'zh-tw': {
        title: '四步輕鬆下載',
        engineTitle: '下載安裝並開啟本機引擎',
        engineDescription: '首次使用先下載 Galaxy Local Engine，完整解壓後執行 install.cmd，再開啟引擎並確認頁面顯示「本機引擎已連線」。',
        download: '下載引擎',
        open: '開啟引擎',
    },
    en: {
        title: 'Download in four steps',
        engineTitle: 'Download, install and open Local Engine',
        engineDescription: 'On first use, download Galaxy Local Engine, extract it fully, run install.cmd, then open it and confirm the page shows Local Engine connected.',
        download: 'Download engine',
        open: 'Open engine',
    },
    ja: {
        title: '4ステップでダウンロード',
        engineTitle: 'Local Engine をダウンロード・インストールして起動',
        engineDescription: '初回は Galaxy Local Engine を完全に展開し、install.cmd を実行してから起動し、ページに接続済みと表示されることを確認します。',
        download: 'エンジンを取得',
        open: 'エンジンを開く',
    },
    es: {
        title: 'Descarga en cuatro pasos',
        engineTitle: 'Descarga, instala y abre Local Engine',
        engineDescription: 'La primera vez, descarga Galaxy Local Engine, descomprímelo por completo, ejecuta install.cmd, ábrelo y confirma que la página indica que está conectado.',
        download: 'Descargar motor',
        open: 'Abrir motor',
    },
    ru: {
        title: 'Скачивание за четыре шага',
        engineTitle: 'Скачайте, установите и откройте Local Engine',
        engineDescription: 'При первом запуске скачайте Galaxy Local Engine, полностью распакуйте архив, запустите install.cmd, затем откройте движок и убедитесь, что на странице показано подключение.',
        download: 'Скачать',
        open: 'Открыть',
    },
};

export function QuickStartCard({ dict, locale }: QuickStartCardProps) {
    const copy = COPY[locale] || COPY.en;
    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg">
                    <PlayCircle className="h-5 w-5 text-primary" />
                    {copy.title}
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
                <div className="flex items-start gap-3">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-medium text-primary-foreground">
                        1
                    </div>
                    <div className="min-w-0">
                        <p className="font-medium">{copy.engineTitle}</p>
                        <p className="text-sm text-foreground/75">{copy.engineDescription}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
                            <a
                                href={LOCAL_ENGINE_RELEASE_URL}
                                className="inline-flex items-center gap-1 text-xs font-medium underline-offset-4 hover:underline"
                            >
                                <HardDriveDownload className="h-3.5 w-3.5" aria-hidden="true" />
                                {copy.download}
                            </a>
                            <a
                                href="galaxy-downloader://open"
                                className="inline-flex items-center gap-1 text-xs font-medium underline-offset-4 hover:underline"
                            >
                                <Play className="h-3.5 w-3.5" aria-hidden="true" />
                                {copy.open}
                            </a>
                        </div>
                    </div>
                </div>
                {dict.guide.quickStart.steps.map((step, index) => (
                    <div key={index} className="flex items-start gap-3">
                        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-medium text-primary-foreground">
                            {index + 2}
                        </div>
                        <div>
                            <p className="font-medium">{step.title}</p>
                            <p className="text-sm text-foreground/75">{step.description}</p>
                        </div>
                    </div>
                ))}
            </CardContent>
        </Card>
    );
}
