# Galaxy Local Engine 0.14.1 Hotfix

## User-visible fix

Galaxy Local Engine 0.14.0 could fail immediately during Tk desktop construction on Windows with:

```text
expected integer but got "UI"
```

The cause was the Tk option database font descriptor:

```python
window.option_add("*Font", "Segoe UI 9")
```

Tk parses string font descriptors as Tcl lists. The multi-word family name was split so `UI` was interpreted as the size token. 0.14.1 quotes the family as one Tcl list element:

```python
window.option_add("*Font", "{Segoe UI} 9")
```

## Regression gate

0.14.1 adds `--ui-smoke-test`, which constructs the fully wrapped desktop `EngineWindow`, processes Tk layout work, and exits automatically.

`.github/workflows/local-engine-ui-smoke.yml` runs this twice on Windows:

1. directly from Python source;
2. after building the real `--onefile --windowed` PyInstaller executable.

The packaged executable must exit normally within 20 seconds. A blocking exception dialog or startup deadlock is therefore treated as a failed check instead of a successful "process still running" result.

## Scope

This hotfix intentionally does not contain the Dailymotion/Vimeo/staging release-gate work from PR #54. Those changes remain on their own stabilization line.
