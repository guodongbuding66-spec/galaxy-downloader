# Local Engine Release Checklist

The automated Windows release is allowed to publish only after these checks pass in GitHub Actions:

- `local-engine/VERSION` is valid `x.y.z` and is the runtime version source.
- Python source compiles and `--self-test` passes.
- PyInstaller builds the one-file Windows executable with the VERSION resource bundled.
- The packaged executable starts and passes `--self-test`.
- The package contains `install.cmd`, `install.ps1`, `uninstall.cmd`, `uninstall.ps1`, `VERSION`, and `README.md`.
- The installer writes the current-user `galaxy-downloader://` protocol to the built executable path.
- The uninstaller removes that protocol registration.
- The release ZIP receives a SHA-256 checksum in `SHA256SUMS.txt`.
- The installer independently verifies the FFmpeg provider's SHA-256 before extracting FFmpeg.

A `main` change to `local-engine/VERSION` triggers publication of `local-engine-vX.Y.Z`. Existing releases are never overwritten automatically.
