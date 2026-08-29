#!/usr/bin/env python3
"""Validate the browser-equivalent fallback path for problematic platforms.

AdvancedDownloadOptions falls back from source-aware /api/download requests to
parser-returned CDN URLs. The browser does not fetch those external URLs
straight from the user's IP: getProxiedDownloadUrl sends them back through
/api/download?url=<resolved-media-url>. This diagnostic verifies that exact path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.parse
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('platform-smoke.py')
spec = importlib.util.spec_from_file_location('platform_smoke', MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit('Unable to load platform-smoke.py')
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)

API_BASE = os.environ.get('PLATFORM_SMOKE_API_BASE', smoke.DEFAULT_API_BASE).rstrip('/')
TIMEOUT = int(os.environ.get('PLATFORM_SMOKE_TIMEOUT', '30'))
TARGETS = ('youtube', 'weibo', 'vimeo')


def proxy_url(media_url: str) -> str:
    return f"{API_BASE}/api/download?{urllib.parse.urlencode({'url': media_url})}"


def main() -> int:
    candidates = smoke.build_fixture_candidates()
    output: dict[str, object] = {}

    for platform in TARGETS:
        selected, parse_probe, payload, diagnostics = smoke.choose_parsable_fixture(
            platform,
            candidates.get(platform, []),
            API_BASE,
            TIMEOUT,
        )
        record: dict[str, object] = {
            'platform': platform,
            'parse': smoke.asdict(parse_probe),
            'fixture': smoke.asdict(selected) if selected else None,
            'diagnostics': diagnostics,
        }
        if not selected or not payload or not isinstance(payload.get('data'), dict):
            record['status'] = 'PARSE_FAIL'
            output[platform] = record
            print(f"[PARSE_FAIL] {platform}")
            continue

        data = payload['data']
        media_results: dict[str, object] = {}
        success = True
        for media_type, keys in (
            ('video', ('downloadVideoUrl', 'originDownloadVideoUrl')),
            ('audio', ('downloadAudioUrl', 'originDownloadAudioUrl')),
        ):
            raw = next((data.get(key) for key in keys if isinstance(data.get(key), str) and data.get(key)), None)
            if not raw:
                media_results[media_type] = {'status': 'NOT_EXPOSED'}
                continue
            direct = smoke.probe_media_url(raw, TIMEOUT)
            proxied = smoke.probe_media_url(proxy_url(raw), TIMEOUT)
            media_results[media_type] = {
                'rawUrlHost': urllib.parse.urlparse(raw).netloc,
                'direct': smoke.asdict(direct),
                'backendProxy': smoke.asdict(proxied),
            }
            if media_type == 'video' and not proxied.ok:
                success = False
            if media_type == 'audio' and data.get('videoAudioMode') == 'separate' and not proxied.ok:
                success = False

        record['media'] = media_results
        record['status'] = 'PASS' if success else 'FAIL'
        output[platform] = record
        print(f"[{record['status']}] {platform}: {json.dumps(media_results, ensure_ascii=False)}")

    out_dir = Path('platform-smoke-artifacts')
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'browser-fallback-smoke.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
