# Galaxy Local Engine

Galaxy Local Engine is the free, local-only fallback for media sites that cannot be downloaded reliably through browser or edge-network routes.

## Why it exists

Some services bind media URLs to the client IP/ASN, require logged-in browser cookies, or use anti-bot checks that are unreliable from a shared cloud address. Running yt-dlp on the user's own computer avoids those cloud-egress problems while keeping large media files off Galaxy servers.

## User flow

1. Download `GalaxyLocalEngine-Windows.zip` from the latest Galaxy release.
2. Extract the complete ZIP and double-click `install.cmd` once.
3. The installer copies `GalaxyLocalEngine.exe` into `%LOCALAPPDATA%\GalaxyDownloader\LocalEngine`, downloads the free FFmpeg essentials build, verifies its publisher SHA-256 checksum, and registers the `galaxy-downloader://` protocol for the current Windows user. No administrator account is required.
4. On the Galaxy website choose a browser login session if needed and click **Local yt-dlp download**.
5. Windows opens Galaxy Local Engine. yt-dlp downloads and FFmpeg assembles the final file locally.

Default output folder:

`%USERPROFILE%\Downloads\Galaxy Downloader`

`install.cmd` starts PowerShell with a process-scoped execution-policy bypass so users do not need to modify the machine-wide PowerShell policy.

## Browser cookies

The web launcher can request a local browser cookie source such as Edge, Chrome or Firefox. Cookies are read directly by yt-dlp from the local browser profile. They are never sent to the Galaxy website or a Galaxy server.

This is useful for services that require the same login/IP/browser session as normal playback.

## Custom protocol

Example:

```text
galaxy-downloader://download?url=https%3A%2F%2Fexample.com%2Fvideo&video=1080&audio=best&include_audio=1&subtitle=1&subtitle_lang=zh-Hans&cover=1&browser=edge
```

Only `http` and `https` source URLs are accepted by the engine.

## Versioning and releases

`local-engine/VERSION` is the single source of truth for the desktop engine version. The source runtime reads it directly, PyInstaller bundles the same file into the executable, and the release workflow publishes the corresponding `local-engine-vX.Y.Z` tag.

Changing `local-engine/VERSION` on `main` triggers the free Windows release workflow. If that release already exists, the workflow safely skips publishing it again.

Each release contains:

- `GalaxyLocalEngine-Windows.zip`
- `SHA256SUMS.txt`

The ZIP contains the executable, one-click installer/uninstaller, VERSION file and README.

## Building the Windows executable

The repository workflow `.github/workflows/local-engine-windows.yml` builds the executable with Python 3.12, yt-dlp and PyInstaller on GitHub Actions, then starts the packaged EXE with `--self-test`.

Local build from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r local-engine\requirements.txt
pyinstaller --noconfirm --clean --onefile --windowed --name GalaxyLocalEngine --collect-all yt_dlp --add-data "local-engine/VERSION;." local-engine\engine.py
```

Keep `GalaxyLocalEngine.exe`, `install.cmd`, `install.ps1`, `uninstall.cmd`, `uninstall.ps1`, `VERSION`, and `README.md` together before installation.

## Security boundaries

- Custom-protocol jobs only accept `http(s)` source URLs.
- The engine does not expose a public network server.
- Browser cookies stay on the user's computer.
- FFmpeg and downloaded media stay on the user's computer.
- FFmpeg ZIP integrity is checked against the SHA-256 published by the build provider before extraction.
- No paid backend or subscription service is required.
