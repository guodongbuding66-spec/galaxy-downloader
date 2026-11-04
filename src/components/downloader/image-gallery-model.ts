export type ImageDimensions = { width: number; height: number };

/** Unknown dimensions stay visible so their image can load and be measured. */
export function visibleImageIndices(count: number, dimensions: Record<number, ImageDimensions>, minimumLongEdge: number): number[] {
    return Array.from({ length: count }, (_, index) => index).filter((index) => {
        const size = dimensions[index];
        return !size || Math.max(size.width, size.height) >= minimumLongEdge;
    });
}

/** Downloads keep source order and ignore stale or out-of-range selections. */
export function selectedImageIndices(count: number, selected: ReadonlySet<number>): number[] {
    return Array.from({ length: count }, (_, index) => index).filter((index) => selected.has(index));
}

type GalleryCopy = {
    select: string; selected: string; all: string; none: string; preview: string;
    dimensions: string; any: string; minimum: string; selectHint: string;
    previous: string; next: string; empty: string; visible: string;
};

const COPY: Record<string, GalleryCopy> = {
    zh: { select: '选择图片', selected: '已选择 {count} / {total} 张', all: '全选', none: '清空选择', preview: '放大查看', dimensions: '显示尺寸', any: '全部尺寸', minimum: '长边至少 {size} px', selectHint: '尺寸为已加载图片的实际尺寸；下载优先请求来源原图。', previous: '上一张', next: '下一张', empty: '没有图片符合当前尺寸条件，请降低筛选尺寸。', visible: '选择当前显示' },
    'zh-tw': { select: '選擇圖片', selected: '已選擇 {count} / {total} 張', all: '全選', none: '清空選擇', preview: '放大查看', dimensions: '顯示尺寸', any: '全部尺寸', minimum: '長邊至少 {size} px', selectHint: '尺寸為已載入圖片的實際尺寸；下載優先請求來源原圖。', previous: '上一張', next: '下一張', empty: '沒有符合尺寸條件的圖片，請降低篩選尺寸。', visible: '選擇目前顯示' },
    en: { select: 'Select image', selected: '{count} / {total} selected', all: 'Select all', none: 'Clear selection', preview: 'Enlarge image', dimensions: 'Display dimensions', any: 'All dimensions', minimum: 'Long edge at least {size} px', selectHint: 'Dimensions describe the loaded image. Downloads request the source original first.', previous: 'Previous image', next: 'Next image', empty: 'No images match this size. Lower the dimension filter.', visible: 'Select visible' },
    ja: { select: '画像を選択', selected: '{total} 枚中 {count} 枚を選択', all: 'すべて選択', none: '選択解除', preview: '拡大表示', dimensions: '表示サイズ', any: 'すべてのサイズ', minimum: '長辺 {size} px 以上', selectHint: '読み込んだ画像の実測サイズです。保存時は元画像を優先します。', previous: '前の画像', next: '次の画像', empty: '一致する画像がありません。サイズ条件を下げてください。', visible: '表示中を選択' },
    es: { select: 'Seleccionar imagen', selected: '{count} / {total} seleccionadas', all: 'Seleccionar todo', none: 'Borrar selección', preview: 'Ampliar imagen', dimensions: 'Dimensiones visibles', any: 'Todos los tamaños', minimum: 'Lado largo de al menos {size} px', selectHint: 'Se muestra el tamaño de la imagen cargada. La descarga solicita primero el original.', previous: 'Imagen anterior', next: 'Imagen siguiente', empty: 'No hay imágenes de ese tamaño. Reduce el filtro.', visible: 'Seleccionar visibles' },
    ru: { select: 'Выбрать изображение', selected: 'Выбрано {count} / {total}', all: 'Выбрать все', none: 'Снять выбор', preview: 'Увеличить изображение', dimensions: 'Размер изображения', any: 'Все размеры', minimum: 'Длинная сторона от {size} px', selectHint: 'Показан размер загруженного изображения. При скачивании сначала запрашивается оригинал.', previous: 'Предыдущее изображение', next: 'Следующее изображение', empty: 'Нет изображений такого размера. Уменьшите фильтр.', visible: 'Выбрать видимые' },
};

export function imageGalleryCopy(locale: string): GalleryCopy {
    return COPY[locale] || COPY.en;
}
