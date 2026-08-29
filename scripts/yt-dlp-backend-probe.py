#!/usr/bin/env python3
"""Probe whether a first-party yt-dlp backend can replace failing shared providers.

This does not download complete media. It runs the latest yt-dlp on the same
machine that probes the returned format URL, which is important for signed/IP-
bound CDNs such as YouTube googlevideo.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).with_name('platform-smoke.py')
spec = importlib.util.spec_from_file_location('platform_smoke_selfhost', MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit('Unable to load platform-smoke.py')
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)

TARGETS = ('youtube', 'weibo', 'vimeo', 'xiaohongshu', 'twitch', 'rumble')
TWITCH_CLIP = 'https://m.twitch.tv/ninja/clip/SuaveNeighborlySrirachaHeyGirl-1J8kzeLFWxdUBZ4C'
TIMEOUT = 75


def pick_fixture(platform: str, candidates: dict[str, list[Any]]) -> str | None:
    if platform == 'twitch':
        return TWITCH_CLIP
    items = candidates.get(platform, [])
    return items[0].url if items else None


def run_yt_dlp(url: str) -> tuple[dict[str, Any] | None, str | None]:
    command = [
        'yt-dlp',
        '--dump-single-json',
        '--skip-download',
        '--no-playlist',
        '--no-warnings',
        '--js-runtimes', 'node',
        url,
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, 'yt-dlp timed out'
    if completed.returncode != 0:
        return None, (completed.stderr or completed.stdout or f'exit {completed.returncode}')[-3000:]
    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError as exc:
        return None, f'invalid yt-dlp JSON: {exc}'


def codec_present(value: Any) -> bool:
    return isinstance(value, str) and value and value.lower() != 'none'


def score_format(fmt: dict[str, Any]) -> tuple[int, int, float]:
    has_video = codec_present(fmt.get('vcodec'))
    has_audio = codec_present(fmt.get('acodec'))
    height = int(fmt.get('height') or 0)
    bitrate = float(fmt.get('tbr') or fmt.get('abr') or 0)
    return (2 if has_video and has_audio else 1 if has_video else 0, height, bitrate)


def best_video_format(info: dict[str, Any]) -> dict[str, Any] | None:
    formats = [fmt for fmt in info.get('formats') or [] if isinstance(fmt, dict)]
    candidates = [fmt for fmt in formats if codec_present(fmt.get('vcodec')) and isinstance(fmt.get('url'), str)]
    return max(candidates, key=score_format, default=None)


def best_audio_format(info: dict[str, Any]) -> dict[str, Any] | None:
    formats = [fmt for fmt in info.get('formats') or [] if isinstance(fmt, dict)]
    candidates = [fmt for fmt in formats if codec_present(fmt.get('acodec')) and isinstance(fmt.get('url'), str)]
    return max(candidates, key=lambda fmt: float(fmt.get('abr') or fmt.get('tbr') or 0), default=None)


def probe_format(fmt: dict[str, Any] | None) -> dict[str, Any] | None:
    if not fmt or not isinstance(fmt.get('url'), str):
        return None
    req = urllib.request.Request(
        fmt['url'],
        headers={
            'Range': 'bytes=0-65535',
            'User-Agent': fmt.get('http_headers', {}).get('User-Agent', 'Mozilla/5.0'),
            'Referer': fmt.get('http_headers', {}).get('Referer', ''),
        },
        method='GET',
    )
    # Copy extractor-provided headers because some CDNs validate them.
    for key, value in (fmt.get('http_headers') or {}).items():
        if isinstance(key, str) and isinstance(value, str) and value:
            req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            chunk = response.read(65536)
            return {
                'ok': bool(chunk),
                'status': getattr(response, 'status', 200),
                'bytes': len(chunk),
                'contentType': response.headers.get('content-type'),
                'host': urllib.request.urlparse(fmt['url']).netloc if False else None,
            }
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'status': exc.code, 'error': str(exc)}
    except Exception as exc:
        return {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}


def main() -> int:
    fixture_candidates = smoke.build_fixture_candidates()
    report: dict[str, Any] = {}
    for platform in TARGETS:
        url = pick_fixture(platform, fixture_candidates)
        if not url:
            report[platform] = {'status': 'NO_FIXTURE'}
            print(f'[NO_FIXTURE] {platform}')
            continue

        info, error = run_yt_dlp(url)
        if not info:
            report[platform] = {'status': 'PARSE_FAIL', 'url': url, 'error': error}
            print(f'[PARSE_FAIL] {platform}: {error}')
            continue

        video = best_video_format(info)
        audio = best_audio_format(info)
        video_probe = probe_format(video)
        audio_probe = probe_format(audio) if audio and audio is not video else video_probe
        status = 'PASS' if video_probe and video_probe.get('ok') else 'MEDIA_FAIL'
        report[platform] = {
            'status': status,
            'url': url,
            'extractor': info.get('extractor_key') or info.get('extractor'),
            'title': info.get('title'),
            'formatCount': len(info.get('formats') or []),
            'videoFormat': {
                'formatId': video.get('format_id') if video else None,
                'ext': video.get('ext') if video else None,
                'height': video.get('height') if video else None,
                'vcodec': video.get('vcodec') if video else None,
                'acodec': video.get('acodec') if video else None,
            } if video else None,
            'audioFormat': {
                'formatId': audio.get('format_id') if audio else None,
                'ext': audio.get('ext') if audio else None,
                'abr': audio.get('abr') if audio else None,
                'acodec': audio.get('acodec') if audio else None,
            } if audio else None,
            'videoProbe': video_probe,
            'audioProbe': audio_probe,
        }
        print(f'[{status}] {platform}: extractor={report[platform]["extractor"]} formats={report[platform]["formatCount"]} video={video_probe} audio={audio_probe}')

    output = Path('platform-smoke-artifacts')
    output.mkdir(parents=True, exist_ok=True)
    (output / 'yt-dlp-backend-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
