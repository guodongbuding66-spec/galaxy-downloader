import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { HardDriveDownload, PlayCircle } from 'lucide-react';
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
};

const COPY: Record<string, QuickStartCopy> = {
    zh: {
        title: '四步轻松下载',
        engineTitle: '下载并打开本地引擎',
        engineDescription: '首次使用先下载安装 Galaxy Local Engine，运行 install.cmd 后打开引擎。',
        download: '下载引擎',
    },
    'zh-tw': {
        title: '四步輕鬆下載',
        engineTitle: '下載並開啟本機引擎',
        engineDescription: '首次使用先下載 Galaxy Local Engine，執行 install.cmd 後開啟引擎。',
        download: '下載引擎',
    },
    en: {
        title: 'Download in four steps',
        engineTitle: 'Download and open Local Engine',
        engineDescription: 'On first use, install Galaxy Local Engine with install.cmd, then open it.',
        download: 'Download engine',
    },
    ja: {
        title: '4ステップでダウンロード',
        engineTitle: 'Local Engine を取得して起動',
        engineDescription: '初回は Galaxy Local Engine をダウンロードし、install.cmd 実行後に起動します。',
        download: 'エンジンを取得',
    },
    es: {
        title: 'Descarga en cuatro pasos',
        engineTitle: 'Descarga y abre Local Engine',
        engineDescription: 'La primera vez, instala Galaxy Local Engine con install.cmd y luego ábrelo.',
        download: 'Descargar motor',
    },
    ru: {
        title: 'Скачивание за четыре шага',
        engineTitle: 'Скачайте и откройте Local Engine',
        engineDescription: 'При первом запуске установите Galaxy Local Engine через install.cmd и откройте его.',
        download: 'Скачать',
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
                        <a
                            href={LOCAL_ENGINE_RELEASE_URL}
                            className="mt-1 inline-flex items-center gap-1 text-xs font-medium underline-offset-4 hover:underline"
                        >
                            <HardDriveDownload className="h-3.5 w-3.5" aria-hidden="true" />
                            {copy.download}
                        </a>
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