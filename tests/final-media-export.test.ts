import { describe, expect, it } from 'vitest';

import {
  buildFinalMediaFfmpegArgs,
  inferJoinedHlsExtension,
  isHlsMediaResponse,
  shouldStreamCopyAudio,
} from '../src/lib/final-media-export.ts';

describe('final media export', () => {
  it('builds one MP4 with best video/audio, subtitle and attached cover', () => {
    const args = buildFinalMediaFfmpegArgs({
      videoInput: 'video.webm',
      audioInput: 'audio.m4a',
      subtitleInput: 'subtitle.vtt',
      coverInput: 'cover.webp',
      subtitleLanguage: 'zh-CN',
      title: 'Example',
      sourceUrl: 'https://youtu.be/example',
    });

    expect(args).toContain('-c:v:0');
    expect(args).toContain('copy');
    expect(args).toContain('-c:a');
    expect(args).toContain('aac');
    expect(args).toContain('320k');
    expect(args).toContain('-c:s');
    expect(args).toContain('mov_text');
    expect(args).toContain('-c:v:1');
    expect(args).toContain('mjpeg');
    expect(args).toContain('-disposition:v:1');
    expect(args).toContain('attached_pic');
    expect(args).toContain('language=zho');
    expect(args).toContain('final-output.mp4');
  });

  it('can preserve a compatible selected audio bitstream without recompression', () => {
    const args = buildFinalMediaFfmpegArgs({
      videoInput: 'video.mp4',
      audioInput: 'best-audio.m4a',
      audioCodec: 'copy',
    });

    const codecIndex = args.indexOf('-c:a');
    expect(args[codecIndex + 1]).toBe('copy');
    expect(args).not.toContain('-b:a');
    expect(shouldStreamCopyAudio(new File([new Uint8Array([1])], 'best.m4a', { type: 'audio/mp4' }))).toBe(true);
    expect(shouldStreamCopyAudio(new File([new Uint8Array([1])], 'best.aac', { type: 'audio/aac' }))).toBe(true);
    expect(shouldStreamCopyAudio(new File([new Uint8Array([1])], 'best.webm', { type: 'audio/webm' }))).toBe(false);
  });

  it('falls back to audio already inside the video when no separate audio URL exists', () => {
    const args = buildFinalMediaFfmpegArgs({
      videoInput: 'video.mp4',
    });

    const mapPairs = args
      .map((value, index) => value === '-map' ? args[index + 1] : null)
      .filter(Boolean);
    expect(mapPairs).toContain('0:v:0');
    expect(mapPairs).toContain('0:a:0?');
    expect(args).not.toContain('mov_text');
    expect(args).not.toContain('attached_pic');
  });

  it('detects HLS from MIME type, URL suffix, or playlist bytes', () => {
    expect(isHlsMediaResponse('application/vnd.apple.mpegurl', 'https://example.com/video')).toBe(true);
    expect(isHlsMediaResponse('text/plain', 'https://example.com/master.m3u8')).toBe(true);
    expect(isHlsMediaResponse('text/plain', 'https://example.com/proxy', new TextEncoder().encode('#EXTM3U\n#EXT-X-VERSION:3'))).toBe(true);
    expect(isHlsMediaResponse('video/mp4', 'https://example.com/video.mp4', new Uint8Array([0, 1, 2]))).toBe(false);
  });

  it('uses MP4 for fragmented HLS and TS for transport-stream HLS', () => {
    expect(inferJoinedHlsExtension('https://example.com/init.mp4', [{ url: 'https://example.com/seg.m4s' }])).toBe('mp4');
    expect(inferJoinedHlsExtension(null, [{ url: 'https://example.com/seg.m4s' }])).toBe('mp4');
    expect(inferJoinedHlsExtension(null, [{ url: 'https://example.com/seg.ts' }])).toBe('ts');
  });
});
