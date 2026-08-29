#!/usr/bin/env python3
"""Inspect primary/origin parsed media candidates for degraded platforms."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.parse
from pathlib import Path

MODULE_PATH = Path(__file__).with_name('platform-smoke.py')
spec = importlib.util.spec_from_file_location('platform_smoke_origin', MODULE_PATH)
if spec is None or spec.loader is None:
    raise SystemExit('Unable to load platform-smoke.py')
smoke = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)

API_BASE = os.environ.get('PLATFORM_SMOKE_API_BASE', smoke.DEFAULT_API_BASE).rstrip('/')
TIMEOUT = int(os.environ.get('PLATFORM_SMOKE_TIMEOUT', '30'))
TARGETS = ('youtube', 'weibo', 'vimeo', 'okru', 'odysee')


def backend_proxy(url: str) -> str:
    return f"{API_BASE}/api/download?{urllib.parse.urlencode({'url': url})}"


def probe_candidate(url: str | None):
    if not url:
        return None
    direct = smoke.probe_media_url(url, TIMEOUT)
    proxied = smoke.probe_media_url(backend_proxy(url), TIMEOUT)
    parsed = urllib.parse.urlparse(url)
    return {
        'host': parsed.netloc,
        'path': parsed.path,
        'hasType': 'type' in urllib.parse.parse_qs(parsed.query),
        'direct': smoke.asdict(direct),
        'backendProxy': smoke.asdict(proxied),
    }


def main() -> int:
    candidates = smoke.build_fixture_candidates()
    report = {}
    for platform in TARGETS:
        selected, parse_probe, payload, diagnostics = smoke.choose_parsable_fixture(
            platform, candidates.get(platform, []), API_BASE, TIMEOUT
        )
        row = {
            'parse': smoke.asdict(parse_probe),
            'fixture': smoke.asdict(selected) if selected else None,
            'diagnostics': diagnostics,
        }
        if not payload or not isinstance(payload.get('data'), dict):
            row['status'] = 'PARSE_FAIL'
            report[platform] = row
            print(f'[PARSE_FAIL] {platform}')
            continue

        data = payload['data']
        row['videoAudioMode'] = data.get('videoAudioMode')
        row['video'] = {
            'download': probe_candidate(data.get('downloadVideoUrl')),
            'origin': probe_candidate(data.get('originDownloadVideoUrl')),
        }
        row['audio'] = {
            'download': probe_candidate(data.get('downloadAudioUrl')),
            'origin': probe_candidate(data.get('originDownloadAudioUrl')),
        }
        report[platform] = row
        print(f'[{platform}] {json.dumps(row, ensure_ascii=False)}')

    out_dir = Path('platform-smoke-artifacts')
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'origin-candidate-smoke.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
