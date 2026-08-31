from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

import websocket
from yt_dlp import YoutubeDL

YUANBAO_URL = "https://yuanbao.tencent.com/"
AUTH_COOKIE_NAMES = {"hy_user", "hy_token"}


class BrowserAuthError(RuntimeError):
    pass


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _profile_root() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "GalaxyDownloader" / "browser-auth"
    return _app_dir() / "browser-auth"


def _browser_executable(browser: str) -> Path:
    browser = browser.lower().strip()
    candidates: list[Path] = []
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = Path(os.environ.get("PROGRAMFILES", ""))
        program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", ""))
        if browser == "edge":
            candidates.extend([
                program_files_x86 / "Microsoft/Edge/Application/msedge.exe",
                program_files / "Microsoft/Edge/Application/msedge.exe",
                local / "Microsoft/Edge/Application/msedge.exe",
            ])
        elif browser == "chrome":
            candidates.extend([
                program_files / "Google/Chrome/Application/chrome.exe",
                program_files_x86 / "Google/Chrome/Application/chrome.exe",
                local / "Google/Chrome/Application/chrome.exe",
            ])
    executable_name = "msedge" if browser == "edge" else "chrome"
    found = shutil.which(executable_name)
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    raise BrowserAuthError(f"未找到 {browser.title()}，无法启动 Galaxy 专用腾讯元宝登录窗口。")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_json(url: str, timeout: float = 1.5):
    request = urllib.request.Request(url, headers={"User-Agent": "Galaxy Local Engine"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_browser_ws(port: int, process: subprocess.Popen, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BrowserAuthError("Galaxy 专用浏览器窗口启动后立即退出。")
        try:
            payload = _read_json(f"http://127.0.0.1:{port}/json/version")
            ws_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
            if ws_url:
                return ws_url
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.2)
    raise BrowserAuthError(f"无法连接 Galaxy 专用浏览器调试通道：{last_error or 'timeout'}")


def _page_ws_url(port: int) -> str:
    try:
        targets = _read_json(f"http://127.0.0.1:{port}/json/list", timeout=2.0)
    except Exception as exc:  # noqa: BLE001
        raise BrowserAuthError(f"无法读取 Galaxy 专用浏览器页面：{exc}") from exc
    if not isinstance(targets, list):
        raise BrowserAuthError("Galaxy 专用浏览器没有返回可用页面。")
    pages = [item for item in targets if isinstance(item, dict) and item.get("type") == "page"]
    pages.sort(key=lambda item: "yuanbao.tencent.com" not in str(item.get("url") or ""))
    for page in pages:
        ws_url = str(page.get("webSocketDebuggerUrl") or "").strip()
        if ws_url:
            return ws_url
    raise BrowserAuthError("Galaxy 专用浏览器没有可连接的腾讯元宝页面。")


def _cdp_call(ws_url: str, method: str, params: dict | None = None, timeout: float = 4.0) -> dict:
    client = websocket.create_connection(
        ws_url,
        timeout=timeout,
        origin="http://127.0.0.1",
    )
    try:
        message_id = 1
        client.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payload = json.loads(client.recv())
            if payload.get("id") != message_id:
                continue
            if payload.get("error"):
                raise BrowserAuthError(f"浏览器调试协议返回错误：{payload['error']}")
            result = payload.get("result")
            return result if isinstance(result, dict) else {}
        raise BrowserAuthError("浏览器调试协议响应超时。")
    finally:
        client.close()


def _cookies_to_header(cookies: Iterable[dict]) -> str:
    pairs: list[str] = []
    seen: set[str] = set()
    names: set[str] = set()
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if domain != "tencent.com" and not domain.endswith(".tencent.com"):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        names.add(name)
        pairs.append(f"{name}={value}")
    if not AUTH_COOKIE_NAMES.issubset(names):
        return ""
    return "; ".join(pairs)


def _cookies_from_debug_browser(port: int) -> str:
    ws_url = _page_ws_url(port)
    result = _cdp_call(
        ws_url,
        "Network.getCookies",
        {"urls": [YUANBAO_URL, "https://yuanbao.tencent.com/api/"]},
    )
    cookies = result.get("cookies")
    return _cookies_to_header(cookies if isinstance(cookies, list) else [])


def _launch_debug_browser(
    browser: str,
    profile_dir: Path,
    *,
    headless: bool,
) -> tuple[subprocess.Popen, int, str]:
    executable = _browser_executable(browser)
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    args = [
        str(executable),
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-component-update",
    ]
    if headless:
        args.extend(["--headless=new", "--disable-gpu", "--window-size=1200,900"])
    else:
        args.extend(["--new-window", "--start-maximized"])
    args.append(YUANBAO_URL)
    creationflags = 0
    if headless and sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    browser_ws = _wait_browser_ws(port, process)
    return process, port, browser_ws


def _close_debug_browser(process: subprocess.Popen, browser_ws: str) -> None:
    if browser_ws:
        try:
            _cdp_call(browser_ws, "Browser.close", timeout=2.0)
        except Exception:
            pass
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        try:
            process.terminate()
        except OSError:
            pass


def _managed_chromium_cookie_header(browser: str, on_status: Callable[[str], None]) -> str:
    profile_dir = _profile_root() / browser

    # Reuse a Galaxy-owned authenticated profile silently after the first successful login.
    if profile_dir.exists():
        process: subprocess.Popen | None = None
        browser_ws = ""
        try:
            process, port, browser_ws = _launch_debug_browser(browser, profile_dir, headless=True)
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                try:
                    header = _cookies_from_debug_browser(port)
                except BrowserAuthError:
                    header = ""
                if header:
                    on_status("已复用 Galaxy 本机保存的腾讯元宝登录状态")
                    return header
                time.sleep(0.5)
        except Exception:
            pass
        finally:
            if process is not None:
                _close_debug_browser(process, browser_ws)

    on_status(
        f"{browser.title()} 正在占用日常浏览器 Cookie 数据库。"
        "已打开 Galaxy 专用腾讯元宝登录窗口；请在新窗口完成登录，"
        "成功后程序会自动继续，不需要关闭你正在使用的浏览器。"
    )
    process = None
    browser_ws = ""
    try:
        process, port, browser_ws = _launch_debug_browser(browser, profile_dir, headless=False)
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise BrowserAuthError("Galaxy 专用腾讯元宝登录窗口已关闭，但尚未检测到有效登录状态。")
            try:
                header = _cookies_from_debug_browser(port)
            except BrowserAuthError:
                header = ""
            if header:
                on_status("已获取 Galaxy 专用腾讯元宝登录状态，正在继续解析微信视频号")
                time.sleep(1.0)
                return header
            time.sleep(0.7)
        raise BrowserAuthError("等待腾讯元宝登录超时。请重新发起下载并在 Galaxy 专用窗口完成登录。")
    finally:
        if process is not None:
            _close_debug_browser(process, browser_ws)


def _existing_browser_cookie_header(browser: str) -> str:
    with YoutubeDL({
        "quiet": True,
        "no_warnings": True,
        "cookiesfrombrowser": (browser, None, None, None),
    }) as ydl:
        cookies = [
            {
                "domain": str(getattr(cookie, "domain", "") or ""),
                "name": str(getattr(cookie, "name", "") or ""),
                "value": str(getattr(cookie, "value", "") or ""),
            }
            for cookie in ydl.cookiejar
        ]
    return _cookies_to_header(cookies)


def get_yuanbao_cookie_header(browser: str, *, on_status: Callable[[str], None]) -> str:
    requested = (browser or "none").strip().lower()
    if requested == "none":
        raise BrowserAuthError(
            "微信视频号需要腾讯元宝登录状态。请在网页“登录状态”中明确选择 Edge、Chrome 或 Firefox。"
        )
    if requested not in {"edge", "chrome", "firefox"}:
        raise BrowserAuthError(f"暂不支持从 {requested} 读取腾讯元宝登录状态。")

    on_status(f"正在读取所选 {requested.title()} 的腾讯元宝登录状态")
    direct_error: Exception | None = None
    try:
        header = _existing_browser_cookie_header(requested)
        if header:
            on_status(f"已读取 {requested.title()} 当前腾讯元宝登录状态")
            return header
    except Exception as exc:  # noqa: BLE001
        direct_error = exc

    if requested in {"edge", "chrome"}:
        return _managed_chromium_cookie_header(requested, on_status)

    suffix = ""
    if direct_error:
        suffix = " Firefox 当前无法读取 Cookie，请完全退出 Firefox 后重试。"
    raise BrowserAuthError(
        "所选 Firefox 中没有检测到有效的腾讯元宝登录状态。请先登录 yuanbao.tencent.com。" + suffix
    )
