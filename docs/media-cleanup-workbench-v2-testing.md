# Workbench 2.0 test surface

Dedicated Linux/Windows gate validates:
- compile of all cleanup cores, V2 presenter, and entrypoint
- image/video mode contract
- moving-video single-region guard
- legacy presenter replacement contract

Repository-level gates additionally cover:
- full source self-test
- UI smoke
- Windows portable package and installer lifecycle
- Linux x64/arm64 portable packages
- macOS Intel/Apple Silicon application packages
- dependency audit and CodeQL
