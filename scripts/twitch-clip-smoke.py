#!/usr/bin/env python3
"""Test the Twitch Clip shape documented by Galaxy Downloader."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('platform-smoke.py')
spec = importlib.util.spec_from_file_location('platform_smoke_twitch', MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit('Unable to load platform-smoke.py')
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)

API_BASE = os.environ.get('PLATFORM_SMOKE_API_BASE', smoke.DEFAULT_API_BASE).rstrip('/')
TIMEOUT = int(os.environ.get('PLATFORM_SMOKE_TIMEOUT', '30'))
URL = 'https://m.twitch.tv/ninja/clip/SuaveNeighborlySrirachaHeyGirl-1J8kzeLFWxdUBZ4C'


def main() -> int:
    parse, payload = smoke.parse_source(API_BASE, URL, TIMEOUT)
    result = {'url': URL, 'parse': smoke.asdict(parse)}
    if parse.ok and payload and isinstance(payload.get('data'), dict):
        data = payload['data']
        video_url = data.get('downloadVideoUrl') or data.get('originDownloadVideoUrl')
        result['platform'] = data.get('platform')
        result['title'] = data.get('title')
        result['videoAudioMode'] = data.get('videoAudioMode')
        result['video'] = smoke.asdict(smoke.probe_media_url(video_url, TIMEOUT)) if isinstance(video_url, str) else None
        result['status'] = 'PASS' if result['video'] and result['video']['ok'] else 'MEDIA_FAIL'
    else:
        result['status'] = 'PARSE_FAIL'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
