#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


def _status(port: int) -> dict[str, object] | None:
    request = urllib.request.Request(f"http://127.0.0.1:{port}/status", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=0.75) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None


def _tail(path: Path, limit: int = 8000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the tray inside a frozen Linux GalaxyLocalEngine binary")
    parser.add_argument("executable", type=Path)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--port", type=int, default=18736)
    args = parser.parse_args()

    executable = args.executable.resolve()
    if not executable.is_file():
        raise SystemExit(f"Packaged executable not found: {executable}")

    log_path = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / f"galaxy-linux-tray-{os.getpid()}.log"
    env = os.environ.copy()
    env["GALAXY_LOCAL_BRIDGE_PORT"] = str(args.port)
    env["PYSTRAY_BACKEND"] = "appindicator"
    env["GDK_BACKEND"] = "x11"
    env["NO_AT_BRIDGE"] = "1"
    if executable.name.endswith(".AppImage"):
        env["APPIMAGE_EXTRACT_AND_RUN"] = "1"

    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )

    deadline = time.monotonic() + max(args.timeout, 1.0)
    last_payload: dict[str, object] | None = None
    try:
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise AssertionError(
                    f"Packaged engine exited before tray became active (code {return_code}).\n{_tail(log_path)}"
                )
            payload = _status(args.port)
            if payload is not None:
                last_payload = payload
                if payload.get("systemTrayAvailable") is True and payload.get("systemTrayActive") is True:
                    print(
                        "Packaged Linux AppIndicator active: "
                        f"available={payload.get('systemTrayAvailable')} active={payload.get('systemTrayActive')}"
                    )
                    return 0
            time.sleep(0.2)
        raise AssertionError(
            "Packaged engine did not report an active AppIndicator tray before timeout. "
            f"Last status={last_payload!r}\n{_tail(log_path)}"
        )
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        try:
            log_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
