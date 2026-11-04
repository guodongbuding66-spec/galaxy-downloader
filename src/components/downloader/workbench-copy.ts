type WorkspaceCopy = {
    workspace: string; single: string; batch: string; audio: string; history: string;
    title: string; description: string; parse: string; parsing: string; shortcut: string;
    emptyTitle: string; emptyDescription: string; quality: string; qualityDescription: string;
    originals: string; originalsDescription: string; local: string; localDescription: string;
};

const COPY: Record<string, WorkspaceCopy> = {
    zh: {
        workspace: '下载工作台', single: '链接解析', batch: '批量下载', audio: '音频工具', history: '最近解析',
        title: '从链接，到你的媒体库。', description: '粘贴视频、图文或商品链接，检查画质与文件后再下载。', parse: '解析链接', parsing: '正在解析媒体', shortcut: 'Ctrl / ⌘ + Enter 解析',
        emptyTitle: '把想保存的内容放在这里', emptyDescription: '粘贴链接或整段分享文本。解析后可选择视频画质、音轨，以及要保存的图片。',
        quality: '优先最佳画质', qualityDescription: '默认优先使用来源提供的最高可用画质。', originals: '查看图片细节', originalsDescription: '按实测尺寸筛选图片，放大检查并选择下载。', local: '连接本地引擎', localDescription: '大文件与批量任务可直接保存到你的电脑。',
    },
    'zh-tw': {
        workspace: '下載工作台', single: '連結解析', batch: '批次下載', audio: '音訊工具', history: '最近解析',
        title: '從連結，到你的媒體庫。', description: '貼上影片、圖文或商品連結，確認畫質與檔案後下載。', parse: '解析連結', parsing: '正在解析媒體', shortcut: 'Ctrl / ⌘ + Enter 解析',
        emptyTitle: '在這裡放入想保存的內容', emptyDescription: '貼上連結或完整分享文字。解析後可選擇影片畫質、音軌與圖片。',
        quality: '優先最佳畫質', qualityDescription: '預設優先使用來源提供的最高可用畫質。', originals: '查看圖片細節', originalsDescription: '依實測尺寸篩選、放大檢查並選擇下載。', local: '連接本機引擎', localDescription: '大檔案與批次工作可直接保存到你的電腦。',
    },
    en: {
        workspace: 'Download workspace', single: 'Parse a link', batch: 'Batch downloads', audio: 'Audio tools', history: 'Recent links',
        title: 'From a link to your library.', description: 'Paste a video, image post, or product link. Review quality and files before saving.', parse: 'Parse link', parsing: 'Inspecting media', shortcut: 'Ctrl / ⌘ + Enter to parse',
        emptyTitle: 'Start with something worth keeping', emptyDescription: 'Paste a link or shared text. Then choose video quality, audio tracks, and the images to save.',
        quality: 'Best available quality', qualityDescription: 'The highest available source quality is preferred by default.', originals: 'Inspect image details', originalsDescription: 'Filter by measured dimensions, preview, and select images.', local: 'Connect Local Engine', localDescription: 'Save large files and batch jobs directly to your computer.',
    },
    ja: {
        workspace: 'ダウンロード', single: 'リンク解析', batch: '一括ダウンロード', audio: '音声ツール', history: '最近のリンク',
        title: 'リンクから、あなたのライブラリへ。', description: '動画・画像投稿・商品リンクを貼り付け、画質とファイルを確認して保存。', parse: 'リンクを解析', parsing: 'メディアを解析中', shortcut: 'Ctrl / ⌘ + Enter で解析',
        emptyTitle: '保存したいコンテンツをここに', emptyDescription: 'リンクや共有テキストを貼り付けると、画質・音声・保存する画像を選べます。',
        quality: '最高画質を優先', qualityDescription: 'ソースが提供する最高の画質を既定で優先します。', originals: '画像の詳細を確認', originalsDescription: '実測サイズで絞り込み、拡大して選択。', local: 'Local Engine に接続', localDescription: '大きなファイルと一括処理はPCに直接保存。',
    },
    es: {
        workspace: 'Espacio de descargas', single: 'Analizar enlace', batch: 'Descargas por lote', audio: 'Herramientas de audio', history: 'Enlaces recientes',
        title: 'Del enlace a tu biblioteca.', description: 'Pega un enlace de vídeo, imágenes o producto. Revisa los archivos y la calidad antes de guardarlos.', parse: 'Analizar enlace', parsing: 'Analizando medios', shortcut: 'Ctrl / ⌘ + Enter para analizar',
        emptyTitle: 'Empieza con algo que quieras guardar', emptyDescription: 'Pega un enlace o texto compartido. Después elige la calidad, las pistas y las imágenes.',
        quality: 'La mejor calidad disponible', qualityDescription: 'Se prioriza la mayor calidad disponible en la fuente.', originals: 'Revisa los detalles', originalsDescription: 'Filtra por dimensiones medidas, amplía y selecciona.', local: 'Conecta Local Engine', localDescription: 'Guarda archivos grandes y lotes directamente en tu equipo.',
    },
    ru: {
        workspace: 'Рабочая область', single: 'Разобрать ссылку', batch: 'Пакетная загрузка', audio: 'Аудиоинструменты', history: 'Недавние ссылки',
        title: 'Из ссылки — в вашу медиатеку.', description: 'Вставьте ссылку на видео, изображения или товар. Проверьте качество и файлы перед сохранением.', parse: 'Разобрать ссылку', parsing: 'Анализ медиа', shortcut: 'Ctrl / ⌘ + Enter для анализа',
        emptyTitle: 'Добавьте то, что хотите сохранить', emptyDescription: 'Вставьте ссылку или текст публикации, затем выберите качество, дорожки и изображения.',
        quality: 'Лучшее доступное качество', qualityDescription: 'По умолчанию выбирается наивысшее качество источника.', originals: 'Проверьте изображения', originalsDescription: 'Фильтруйте по измеренному размеру, просматривайте и выбирайте.', local: 'Подключите Local Engine', localDescription: 'Большие файлы и пакеты сохраняются прямо на компьютер.',
    },
};

export function workbenchUiCopy(pathname: string | null): WorkspaceCopy {
    const locale = pathname?.split('/').filter(Boolean)[0] || 'en';
    return COPY[locale] || COPY.en;
}
