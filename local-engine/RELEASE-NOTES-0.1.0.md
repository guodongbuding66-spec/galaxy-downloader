# Galaxy Local Engine 0.1.0

Initial Windows release of the local yt-dlp + FFmpeg fallback.

Highlights:

- one-click `galaxy-downloader://` launch from the website
- yt-dlp download and FFmpeg merge on the user's own Windows computer
- optional Edge, Chrome, or Firefox login-session cookies kept local
- current-user installation with no administrator requirement
- `install.cmd` launcher for a simpler first-run experience
- FFmpeg publisher SHA-256 verification before extraction
- executable self-test plus install/register/uninstall lifecycle tests on GitHub Actions
- automatic versioned GitHub Release driven by `local-engine/VERSION`
