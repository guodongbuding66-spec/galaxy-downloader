from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import websocket
from yt_dlp import YoutubeDL

import web_document as base

MAX_DYNAMIC_HTML_BYTES = 10 * 1024 * 1024
CDP_START_TIMEOUT_SECONDS = 12.0
CDP_NAVIGATION_TIMEOUT_SECONDS = 20.0


class DynamicDocumentError(RuntimeError):
    pass


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _browser_candidates(requested: str) -> list[tuple[str, Path]]:
    browser = (requested or "none").strip().lower()
    order = [browser] if browser in {"edge", "chrome"} else []
    order.extend(["edge", "chrome"])
    seen: set[str] = set()
    result: list[tuple[str, Path]] = []

    local = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("PROGRAMFILES", ""))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", ""))

    for name in order:
        if name in seen:
            continue
        seen.add(name)
        candidates: list[Path] = []
        if sys.platform == "win32":
            if name == "edge":
                candidates.extend([
                    program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
                    program_files / "Microsoft/Edge/Application/msedge.exe",
                    local / "Microsoft/Edge/Application/msedge.exe",
                ])
            elif name == "chrome":
                candidates.extend([
                    program_files / "Google/Chrome/Application/chrome.exe",
                    program_files_x86 / "Google/Chrome/Application/chrome.exe",
                    local / "Google/Chrome/Application/chrome.exe",
                ])
        found = shutil.which("msedge" if name == "edge" else "chrome")
        if found:
            candidates.append(Path(found))
        for candidate in candidates:
            if candidate and candidate.exists():
                result.append((name, candidate))
                break
    return result


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_json(url: str, timeout: float = 1.5) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Galaxy Local Engine"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_page_ws(port: int, process: subprocess.Popen[Any]) -> str:
    deadline = time.monotonic() + CDP_START_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise DynamicDocumentError("Dynamic browser exited before CDP became ready")
        try:
            targets = _read_json(f"http://127.0.0.1:{port}/json/list")
            if isinstance(targets, list):
                for target in targets:
                    if not isinstance(target, dict) or target.get("type") != "page":
                        continue
                    ws_url = str(target.get("webSocketDebuggerUrl") or "").strip()
                    if ws_url:
                        return ws_url
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.2)
    raise DynamicDocumentError(f"Could not connect to dynamic browser CDP: {last_error or 'timeout'}")


class _CdpClient:
    def __init__(self, ws_url: str):
        self._socket = websocket.create_connection(
            ws_url,
            timeout=2.5,
            origin="http://127.0.0.1",
        )
        self._next_id = 1

    def close(self) -> None:
        try:
            self._socket.close()
        except Exception:
            pass

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 6.0) -> dict[str, Any]:
        message_id = self._next_id
        self._next_id += 1
        self._socket.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._socket.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                payload = json.loads(self._socket.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if payload.get("id") != message_id:
                continue
            if payload.get("error"):
                raise DynamicDocumentError(f"CDP {method} failed: {payload['error']}")
            result = payload.get("result")
            return result if isinstance(result, dict) else {}
        raise DynamicDocumentError(f"CDP {method} timed out")


def _install_browser_cookies(client: _CdpClient, source_url: str, browser: str) -> None:
    requested = (browser or "none").strip().lower()
    if requested == "none":
        return
    if requested not in {"edge", "chrome", "firefox", "brave", "chromium", "opera", "vivaldi"}:
        return

    source = urlparse(source_url)
    source_host = (source.hostname or "").lower().rstrip(".")
    if not source_host:
        return

    with YoutubeDL({
        "quiet": True,
        "no_warnings": True,
        "cookiesfrombrowser": (requested, None, None, None),
    }) as ydl:
        for cookie in ydl.cookiejar:
            domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower().rstrip(".")
            if not domain or not (source_host == domain or source_host.endswith(f".{domain}")):
                continue
            name = str(getattr(cookie, "name", "") or "").strip()
            value = str(getattr(cookie, "value", "") or "")
            if not name:
                continue
            path = str(getattr(cookie, "path", "") or "/")
            secure = bool(getattr(cookie, "secure", False))
            cookie_url = f"{'https' if secure or source.scheme == 'https' else 'http'}://{source_host}{path if path.startswith('/') else '/'}"
            params: dict[str, Any] = {
                "name": name,
                "value": value,
                "url": cookie_url,
                "path": path if path.startswith("/") else "/",
                "secure": secure,
            }
            try:
                client.call("Network.setCookie", params, timeout=2.0)
            except DynamicDocumentError:
                # One malformed or partitioned cookie should not prevent the
                # remaining browser login state from being installed.
                continue


def _evaluate_value(client: _CdpClient, expression: str, *, await_promise: bool = False, timeout: float = 6.0) -> Any:
    result = client.call(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        },
        timeout=timeout,
    )
    value = result.get("result")
    if isinstance(value, dict):
        return value.get("value")
    return None


def _render_html(source_url: str, browser: str) -> tuple[str, str, str]:
    if not base._safe_http_url(source_url):
        raise DynamicDocumentError("URL is not allowed")

    candidates = _browser_candidates(browser)
    if not candidates:
        raise DynamicDocumentError("Edge or Chrome is required for dynamic page rendering")

    last_error: Exception | None = None
    for browser_name, executable in candidates:
        profile_dir = tempfile.mkdtemp(prefix="galaxy-dynamic-document-")
        port = _free_port()
        args = [
            str(executable),
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile_dir}",
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-component-update",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-extensions",
            "--window-size=1365,900",
            "about:blank",
        ]
        process: subprocess.Popen[Any] | None = None
        client: _CdpClient | None = None
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=_creation_flags(),
            )
            ws_url = _wait_page_ws(port, process)
            client = _CdpClient(ws_url)
            client.call("Network.enable")
            client.call("Page.enable")
            client.call("Runtime.enable")
            client.call("Network.setExtraHTTPHeaders", {
                "headers": {
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
                }
            })
            _install_browser_cookies(client, source_url, browser)
            client.call("Page.navigate", {"url": source_url}, timeout=5.0)

            deadline = time.monotonic() + CDP_NAVIGATION_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                try:
                    ready = _evaluate_value(client, "document.readyState", timeout=2.0)
                except DynamicDocumentError:
                    ready = None
                if ready in {"interactive", "complete"}:
                    break
                time.sleep(0.25)

            # Trigger common lazy-loaded gallery blocks without spending several
            # seconds scrolling a long social feed.
            try:
                _evaluate_value(
                    client,
                    "new Promise(resolve => { window.scrollTo(0, document.body ? document.body.scrollHeight : 0); setTimeout(() => { window.scrollTo(0, 0); resolve(true); }, 700); })",
                    await_promise=True,
                    timeout=3.0,
                )
            except DynamicDocumentError:
                pass
            time.sleep(0.5)

            final_url = str(_evaluate_value(client, "location.href", timeout=2.0) or source_url)
            if not base._safe_http_url(final_url):
                raise DynamicDocumentError("Dynamic page redirected to a URL that is not allowed")
            html = str(_evaluate_value(client, "document.documentElement ? document.documentElement.outerHTML : ''", timeout=6.0) or "")
            if not html:
                raise DynamicDocumentError("Dynamic browser returned an empty document")
            if len(html.encode("utf-8", errors="ignore")) > MAX_DYNAMIC_HTML_BYTES:
                raise DynamicDocumentError("Dynamic document is too large to parse safely")
            return html, final_url, browser_name
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        finally:
            if client is not None:
                client.close()
            if process is not None:
                try:
                    process.terminate()
                    process.wait(timeout=3.0)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            shutil.rmtree(profile_dir, ignore_errors=True)

    raise DynamicDocumentError(str(last_error or "Dynamic browser rendering failed"))


def parse_dynamic_web_document(source_url: str, browser: str = "none") -> dict[str, Any]:
    try:
        raw_html, final_url, browser_used = _render_html(source_url, browser)
        payload = base._document_payload(source_url, raw_html, final_url, browser)
        if payload is None:
            return {
                "success": False,
                "code": "UNSUPPORTED_PLATFORM",
                "status": 422,
                "error": "Dynamic page contained no downloadable document media",
                "details": {"renderer": "cdp", "browser": browser_used},
            }
        details = payload.setdefault("details", {})
        if isinstance(details, dict):
            details.update({"renderer": "cdp", "browser": browser_used})
        return payload
    except DynamicDocumentError as exc:
        return {
            "success": False,
            "code": "DYNAMIC_RENDER_FAILED",
            "status": 502,
            "error": str(exc),
            "details": {"renderer": "cdp"},
        }
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        lowered = detail.lower()
        if browser != "none" and any(token in lowered for token in (
            "cookie database",
            "database is locked",
            "failed to decrypt",
            "could not copy",
        )):
            return {
                "success": False,
                "code": "BROWSER_COOKIE_UNAVAILABLE",
                "status": 409,
                "error": f"无法读取 {browser.title()} 登录 Cookie：{detail}",
                "details": {"renderer": "cdp", "browser": browser},
            }
        return {
            "success": False,
            "code": "DYNAMIC_RENDER_FAILED",
            "status": 502,
            "error": f"Dynamic document renderer failed: {detail}",
            "details": {"renderer": "cdp"},
        }
