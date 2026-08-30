# Galaxy Local Engine

Galaxy Local Engine is the free, local-only fallback for media sites that cannot be downloaded reliably through browser or edge-network routes.

## Why it exists

Some services bind media URLs to the client IP/ASN, require logged-in browser cookies, or use anti-bot checks that are unreliable from a shared cloud address. Running yt-dlp on the user's own computer avoids those cloud-egress problems while keeping large media files off Galaxy servers.

## User flow

1. Download the Windows Local Engine ZIP from a Galaxy release.
2. Extract the ZIP and run `install.ps1` once.
3. The installer copies `GalaxyLocalEngine.exe` into `%LOCALAPPDATA%\GalaxyDownloader\LocalEngine`, downloads the free FFmpeg essentials build, and registers the `galaxy-downloader://` protocol for the current Windows user. No administrator account is required.
4. On the Galaxy website choose the desired video/audio/subtitle/cover settings and click **Local yt-dlp download**.
5. Windows opens Galaxy Local Engine. yt-dlp downloads and FFmpeg assembles the final file locally.

Default output folder:

`%USERPROFILE%\Downloads\Galaxy Downloader`

## Browser cookies

The web launcher can request a local browser cookie source such as Edge, Chrome or Firefox. Cookies are read directly by yt-dlp from the local browser profile. They are never sent to the Galaxy website or a Galaxy server.

This is useful for services that require the same login/IP/browser session as normal playback.

## Custom protocol

Example:

```text
galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fvideo&video=1080&audio=best&include_audio=1&subtitle=1&subtitle_lang=zh-Hans&cover=1&browser=edge
```

Only `http` and `https` source URLs are accepted by the engine.

## Building the Windows executable

The repository workflow `.github/workflows/local-engine-windows.yml` builds the executable with Python 3.12, yt-dlp and PyInstaller on GitHub Actions.

Local build:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r local-engine\requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name GalaxyLocalEngine --collect-all yt_dlp local-engine\engine.py
```

Copy `dist\GalaxyLocalEngine.exe`, `local-engine\install.ps1`, and `local-engine\uninstall.ps1` into one folder before installation.

## Security boundaries

- Custom-protocol jobs only accept `http(s)` source URLs.
- The engine does not expose a public network server.
- Browser cookies stay on the user's computer.
- FFmpeg and downloaded media stay on the user's computer.
- No paid backend or subscription service is required.
