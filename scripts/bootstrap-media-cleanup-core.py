from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "local-engine" / "media_cleanup.py"
ENTRYPOINT = ROOT / "local-engine" / "entrypoint.py"
TEST = ROOT / "scripts" / "test-local-media-cleanup.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


media = MEDIA.read_text(encoding="utf-8")
media = replace_once(
    media,
    '''def _default_output_path(source: Path, media_kind: str) -> Path:\n    suffix = ".mp4" if media_kind == "video" else source.suffix.lower()\n    return source.with_name(f"{source.stem}.cleaned{suffix}")\n\n\ndef _validate_output(source: Path, output_path: Path | None, media_kind: str) -> Path:\n    output = (output_path or _default_output_path(source, media_kind)).expanduser().resolve()\n    if output == source:\n        raise MediaCleanupError("Cleanup output must not overwrite the original media file")\n    if media_kind == "image" and output.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:\n        raise MediaCleanupError("Image cleanup output must be JPG, PNG or WebP")\n    if media_kind == "video" and output.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:\n        raise MediaCleanupError("Video cleanup output must be MP4, MOV, MKV or WebM")\n    output.parent.mkdir(parents=True, exist_ok=True)\n    return output\n''',
    '''def _manifest_path(output: Path) -> Path:\n    return output.with_suffix(output.suffix + ".cleanup.json")\n\n\ndef _output_slot_available(output: Path) -> bool:\n    return not output.exists() and not _manifest_path(output).exists()\n\n\ndef _default_output_path(source: Path, media_kind: str) -> Path:\n    suffix = ".mp4" if media_kind == "video" else source.suffix.lower()\n    base = source.with_name(f"{source.stem}.cleaned{suffix}")\n    if _output_slot_available(base):\n        return base\n    for index in range(2, 10_000):\n        candidate = source.with_name(f"{source.stem}.cleaned-{index}{suffix}")\n        if _output_slot_available(candidate):\n            return candidate\n    raise MediaCleanupError("Could not allocate a non-destructive cleanup output path")\n\n\ndef _validate_output(source: Path, output_path: Path | None, media_kind: str) -> Path:\n    explicit_output = output_path is not None\n    output = (output_path or _default_output_path(source, media_kind)).expanduser().resolve()\n    if output == source:\n        raise MediaCleanupError("Cleanup output must not overwrite the original media file")\n    if media_kind == "image" and output.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:\n        raise MediaCleanupError("Image cleanup output must be JPG, PNG or WebP")\n    if media_kind == "video" and output.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:\n        raise MediaCleanupError("Video cleanup output must be MP4, MOV, MKV or WebM")\n    output.parent.mkdir(parents=True, exist_ok=True)\n    if explicit_output and not _output_slot_available(output):\n        raise MediaCleanupError("Cleanup output already exists; choose a new file name")\n    return output\n''',
    "non-destructive output policy",
)
media = replace_once(
    media,
    '''        "-hide_banner",\n        "-nostdin",\n        "-y",\n        "-i",\n''',
    '''        "-hide_banner",\n        "-loglevel",\n        "error",\n        "-nostdin",\n        "-n",\n        "-i",\n''',
    "ffmpeg no-overwrite flags",
)
media = replace_once(
    media,
    '''def _write_manifest(\n    source: Path,\n    output: Path,\n    regions: tuple[CleanupRegion, ...],\n    media_kind: str,\n    source_sha256: str,\n    output_sha256: str,\n) -> Path:\n    manifest = output.with_suffix(output.suffix + ".cleanup.json")\n''',
    '''def _write_manifest(\n    source: Path,\n    output: Path,\n    regions: tuple[CleanupRegion, ...],\n    media_kind: str,\n    source_sha256: str,\n    output_sha256: str,\n) -> Path:\n    manifest = _manifest_path(output)\n''',
    "manifest helper",
)
media = replace_once(
    media,
    '''    source_sha256 = _sha256(source)\n    if progress_callback:\n        progress_callback(0.0, "Preparing visible overlay cleanup")\n\n    command = build_cleanup_command(ffmpeg_path, source, output, normalized_regions, media_kind)\n''',
    '''    source_sha256 = _sha256(source)\n    if cancel_event is not None and cancel_event.is_set():\n        raise MediaCleanupCancelled("Visible overlay cleanup was cancelled")\n    if progress_callback:\n        progress_callback(0.0, "Preparing visible overlay cleanup")\n\n    command = build_cleanup_command(ffmpeg_path, source, output, normalized_regions, media_kind)\n''',
    "pre-launch cancellation",
)
media = replace_once(
    media,
    '''    try:\n        if media_kind == "video" and process.stdout is not None:\n            for raw_line in process.stdout:\n                if cancel_event is not None and cancel_event.is_set():\n                    process.terminate()\n                    try:\n                        process.wait(timeout=5)\n                    except subprocess.TimeoutExpired:\n                        process.kill()\n                    raise MediaCleanupCancelled("Visible overlay cleanup was cancelled")\n                seconds = _parse_progress_seconds(raw_line.strip())\n                if seconds is not None and probe.duration_seconds > 0:\n                    percent = max(0.0, min(99.0, seconds / probe.duration_seconds * 100.0))\n                    if progress_callback:\n                        progress_callback(percent, "Cleaning video frames")\n        elif cancel_event is not None and cancel_event.is_set():\n            process.terminate()\n            raise MediaCleanupCancelled("Visible overlay cleanup was cancelled")\n\n        return_code = process.wait()\n        stderr = process.stderr.read() if process.stderr is not None else ""\n    except BaseException:\n        if process.poll() is None:\n            process.kill()\n        output.unlink(missing_ok=True)\n        raise\n''',
    '''    cancel_watch_stop = threading.Event()\n    cancel_watch: threading.Thread | None = None\n    if cancel_event is not None:\n        def watch_cancel() -> None:\n            while not cancel_watch_stop.wait(0.1):\n                if not cancel_event.is_set():\n                    continue\n                if process.poll() is None:\n                    process.terminate()\n                    try:\n                        process.wait(timeout=5)\n                    except subprocess.TimeoutExpired:\n                        process.kill()\n                return\n\n        cancel_watch = threading.Thread(\n            target=watch_cancel,\n            name="GalaxyMediaCleanupCancel",\n            daemon=True,\n        )\n        cancel_watch.start()\n\n    try:\n        if media_kind == "video" and process.stdout is not None:\n            for raw_line in process.stdout:\n                seconds = _parse_progress_seconds(raw_line.strip())\n                if seconds is not None and probe.duration_seconds > 0:\n                    percent = max(0.0, min(99.0, seconds / probe.duration_seconds * 100.0))\n                    if progress_callback:\n                        progress_callback(percent, "Cleaning video frames")\n\n        return_code = process.wait()\n        stderr = process.stderr.read() if process.stderr is not None else ""\n        if cancel_event is not None and cancel_event.is_set():\n            raise MediaCleanupCancelled("Visible overlay cleanup was cancelled")\n    except BaseException:\n        if process.poll() is None:\n            process.kill()\n        output.unlink(missing_ok=True)\n        raise\n    finally:\n        cancel_watch_stop.set()\n        if cancel_watch is not None:\n            cancel_watch.join(timeout=0.5)\n''',
    "runtime cancellation watcher",
)
media = replace_once(
    media,
    '''    assert "-vf" in command\n    assert "libx264" in command\n    assert "-progress" in command\n    assert command[-1] == "output.mp4"\n''',
    '''    assert "-vf" in command\n    assert "libx264" in command\n    assert "-progress" in command\n    assert "-n" in command\n    assert "-y" not in command\n    assert command[-1] == "output.mp4"\n''',
    "self-test no-overwrite contract",
)
MEDIA.write_text(media, encoding="utf-8")

entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
entrypoint = replace_once(
    entrypoint,
    'from media_policy import install_media_policy\n',
    'from media_cleanup import run_media_cleanup_self_test\nfrom media_policy import install_media_policy\n',
    "entrypoint cleanup import",
)
entrypoint = replace_once(
    entrypoint,
    '    run_batch_input_self_test()\n',
    '    run_media_cleanup_self_test()\n    run_batch_input_self_test()\n',
    "entrypoint cleanup self-test",
)
ENTRYPOINT.write_text(entrypoint, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations\n\nimport json\nimport sys\nimport tempfile\nimport threading\nimport unittest\nfrom pathlib import Path\n\nROOT = Path(__file__).resolve().parents[1]\nLOCAL_ENGINE = ROOT / "local-engine"\nsys.path.insert(0, str(LOCAL_ENGINE))\n\nfrom media_cleanup import (  # noqa: E402\n    MAX_CLEANUP_REGIONS,\n    CleanupRegion,\n    MediaCleanupCancelled,\n    MediaCleanupError,\n    MediaProbe,\n    _default_output_path,\n    _manifest_path,\n    _normalize_regions,\n    _parse_progress_seconds,\n    _validate_output,\n    _validate_regions_within_frame,\n    _write_manifest,\n    build_cleanup_command,\n    build_delogo_filter,\n    run_media_cleanup_self_test,\n)\n\n\nclass MediaCleanupPolicyTests(unittest.TestCase):\n    def test_region_validation_and_limit(self) -> None:\n        self.assertEqual(CleanupRegion(0, 0, 2, 2).validate().width, 2)\n        with self.assertRaises(MediaCleanupError):\n            CleanupRegion(-1, 0, 10, 10).validate()\n        with self.assertRaises(MediaCleanupError):\n            CleanupRegion(0, 0, 1, 10).validate()\n        with self.assertRaises(MediaCleanupError):\n            _normalize_regions(CleanupRegion(i, 0, 2, 2) for i in range(MAX_CLEANUP_REGIONS + 1))\n\n    def test_regions_must_fit_frame(self) -> None:\n        probe = MediaProbe(width=1920, height=1080, duration_seconds=5.0, media_kind="video")\n        _validate_regions_within_frame((CleanupRegion(1800, 1000, 120, 80),), probe)\n        with self.assertRaises(MediaCleanupError):\n            _validate_regions_within_frame((CleanupRegion(1801, 1000, 120, 80),), probe)\n\n    def test_default_output_is_collision_free_and_explicit_output_is_fail_closed(self) -> None:\n        with tempfile.TemporaryDirectory() as directory:\n            root = Path(directory)\n            source = root / "photo.png"\n            source.write_bytes(b"source")\n            first = _default_output_path(source, "image")\n            self.assertEqual(first.name, "photo.cleaned.png")\n            first.write_bytes(b"old-result")\n            second = _default_output_path(source, "image")\n            self.assertEqual(second.name, "photo.cleaned-2.png")\n            _manifest_path(second).write_text("{}", encoding="utf-8")\n            third = _default_output_path(source, "image")\n            self.assertEqual(third.name, "photo.cleaned-3.png")\n            with self.assertRaises(MediaCleanupError):\n                _validate_output(source, first, "image")\n            with self.assertRaises(MediaCleanupError):\n                _validate_output(source, source, "image")\n\n    def test_ffmpeg_command_never_overwrites_and_preserves_audio(self) -> None:\n        regions = (CleanupRegion(10, 20, 100, 40),)\n        command = build_cleanup_command(\n            Path("ffmpeg"),\n            Path("input.mp4"),\n            Path("output.mp4"),\n            regions,\n            "video",\n        )\n        self.assertIn("-n", command)\n        self.assertNotIn("-y", command)\n        self.assertEqual(command[command.index("-loglevel") + 1], "error")\n        self.assertIn("0:a?", command)\n        self.assertIn("-progress", command)\n        self.assertEqual(command[-1], "output.mp4")\n        self.assertEqual(build_delogo_filter(regions), "delogo=x=10:y=20:w=100:h=40:show=0")\n\n    def test_progress_parser_is_bounded_input_only(self) -> None:\n        self.assertEqual(_parse_progress_seconds("out_time_us=2500000"), 2.5)\n        self.assertEqual(_parse_progress_seconds("out_time_ms=1000000"), 1.0)\n        self.assertIsNone(_parse_progress_seconds("progress=continue"))\n        self.assertIsNone(_parse_progress_seconds("out_time_us=oops"))\n\n    def test_manifest_records_edit_without_source_path_or_url(self) -> None:\n        with tempfile.TemporaryDirectory() as directory:\n            root = Path(directory)\n            source = root / "private" / "input.png"\n            source.parent.mkdir()\n            source.write_bytes(b"source")\n            output = root / "output.png"\n            output.write_bytes(b"output")\n            manifest = _write_manifest(\n                source,\n                output,\n                (CleanupRegion(1, 2, 10, 12),),\n                "image",\n                "a" * 64,\n                "b" * 64,\n            )\n            payload = json.loads(manifest.read_text(encoding="utf-8"))\n            self.assertEqual(payload["operation"], "visible-overlay-cleanup")\n            self.assertEqual(payload["method"], "ffmpeg-delogo")\n            self.assertEqual(payload["sourceFile"], "input.png")\n            self.assertNotIn(str(source.parent), manifest.read_text(encoding="utf-8"))\n            self.assertIn("does not target invisible provenance", payload["note"])\n\n    def test_embedded_self_test(self) -> None:\n        run_media_cleanup_self_test()\n\n\nif __name__ == "__main__":\n    unittest.main(verbosity=2)\n''',
    encoding="utf-8",
)

print("media cleanup bootstrap transform complete")
