#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / "local-engine" / "web-dashboard"

html = (DASH / "index.html").read_text(encoding="utf-8")
css = (DASH / "galaxy-v16.css").read_text(encoding="utf-8")
js = (DASH / "galaxy-v16.js").read_text(encoding="utf-8")
server = (ROOT / "local-engine" / "headless_web_dashboard.py").read_text(encoding="utf-8")

checks = {
    "single V1.6 stylesheet": html.count('/dashboard/galaxy-v16.css') == 1,
    "single V1.6 script": html.count('/dashboard/galaxy-v16.js') == 1,
    "icon source wired": '/dashboard/assets/galaxy-icon.svg' in html,
    "server serves V1.6 stylesheet": '/dashboard/galaxy-v16.css' in server,
    "server serves V1.6 script": '/dashboard/galaxy-v16.js' in server,
    "server serves SVG icon": '/dashboard/assets/galaxy-icon.svg' in server,
    "no transition all": 'transition: all' not in css.lower(),
    "reduced motion": 'prefers-reduced-motion' in css,
    "skin system": 'GalaxySkin' in js,
    "media preview": 'GalaxyMediaPreview' in js,
    "media helper loopback": '127.0.0.1:17837' in js,
}

ids = re.findall(r'\bid=["\']([^"\']+)', html)
checks["unique DOM IDs"] = len(ids) == len(set(ids))
checks["workbench DOM preserved"] = len(ids) >= 190

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(("PASS" if ok else "FAIL") + "  " + name)
if failed:
    raise SystemExit("V1.6 dashboard contract failed: " + ", ".join(failed))
print(f"PASS  {len(checks)}/{len(checks)} V1.6 dashboard contract checks")
