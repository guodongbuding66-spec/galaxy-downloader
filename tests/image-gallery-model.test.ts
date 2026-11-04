import { describe, expect, test } from 'vitest';
import { imageGalleryCopy, selectedImageIndices, visibleImageIndices } from '../src/components/downloader/image-gallery-model';

describe('image gallery selection and dimension filtering', () => {
    test('filters measured thumbnails but keeps unknown images available to load', () => {
        const dimensions = { 0: { width: 100, height: 100 }, 1: { width: 2000, height: 1500 }, 2: { width: 600, height: 1200 } };
        expect(visibleImageIndices(4, dimensions, 1000)).toEqual([1, 2, 3]);
        expect(visibleImageIndices(4, dimensions, 2000)).toEqual([1, 3]);
        expect(visibleImageIndices(4, dimensions, 0)).toEqual([0, 1, 2, 3]);
    });

    test('downloads only valid selected images in source order', () => {
        expect(selectedImageIndices(4, new Set([3, -1, 1, 99]))).toEqual([1, 3]);
        expect(selectedImageIndices(4, new Set())).toEqual([]);
        expect(selectedImageIndices(0, new Set([0]))).toEqual([]);
    });

    test('localizes gallery controls and provides a readable locale fallback', () => {
        expect(imageGalleryCopy('zh').preview).toBe('放大查看');
        expect(imageGalleryCopy('zh-tw').select).toBe('選擇圖片');
        expect(imageGalleryCopy('ja').select).toBe('画像を選択');
        expect(imageGalleryCopy('unknown').all).toBe('Select all');
    });
});
