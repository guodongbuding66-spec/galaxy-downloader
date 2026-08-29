import { describe, expect, it } from 'vitest';

import { buildFinalMediaFfmpegArgs } from '../src/lib/final-media-export.ts';

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
    expect(args).toContain('-c:s');
    expect(args).toContain('mov_text');
    expect(args).toContain('-c:v:1');
    expect(args).toContain('mjpeg');
    expect(args).toContain('-disposition:v:1');
    expect(args).toContain('attached_pic');
    expect(args).toContain('language=zho');
    expect(args).toContain('final-output.mp4');
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
});
