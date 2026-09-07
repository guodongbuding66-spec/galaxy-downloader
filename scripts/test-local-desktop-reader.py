from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_hooks import registered_after_build_ui_hooks
from desktop_reader import (
    _annotation_summary,
    _normalize_settings,
    _settings_capabilities,
    _settings_payload,
    install_desktop_reader,
    run_desktop_reader_self_test,
)


class FakeWindow:
    pass


class FakeEngine:
    EngineWindow = FakeWindow


def test_settings_helpers() -> None:
    epub = _settings_capabilities("epub")
    assert epub == {
        "font": True,
        "width": True,
        "theme": True,
        "focus": True,
        "readingMode": False,
        "mangaDirection": False,
    }
    cbz = _settings_capabilities("cbz")
    assert cbz["readingMode"] and cbz["mangaDirection"]
    assert not cbz["font"] and not cbz["width"] and not cbz["theme"]
    pdf = _settings_capabilities("pdf")
    assert pdf["focus"] and not pdf["font"] and not pdf["readingMode"]

    normalized = _normalize_settings(
        {
            "format": "cbz",
            "settings": {
                "fontSize": 5,
                "contentWidth": 9999,
                "theme": "bad",
                "focusMode": True,
                "readingMode": "double",
                "mangaDirection": "rtl",
            },
        }
    )
    assert normalized == {
        "fontSize": 10,
        "contentWidth": 1800,
        "theme": "system",
        "focusMode": True,
        "readingMode": "double",
        "mangaDirection": "rtl",
    }

    payload = _settings_payload(
        font_size="72",
        content_width="320",
        theme="sepia",
        focus_mode=True,
        reading_mode="fit-width",
        manga_direction="rtl",
    )
    assert payload["fontSize"] == 72
    assert payload["contentWidth"] == 320
    assert payload["theme"] == "sepia"
    assert payload["focusMode"] is True
    assert payload["readingMode"] == "fit-width"
    assert payload["mangaDirection"] == "rtl"


def test_annotation_helpers_and_wiring() -> None:
    assert _annotation_summary(
        {"kind": "highlight", "locator": "chapter:2", "selectedText": "Important sentence", "note": "Memo"}
    ) == "highlight · chapter:2 · Important sentence"
    long_summary = _annotation_summary({"kind": "note", "locator": "page:1", "note": "x" * 120})
    assert long_summary.endswith("…")
    source = (LOCAL_ENGINE / "desktop_reader.py").read_text(encoding="utf-8")
    for call in (
        "update_reader_settings(engine_module, book[\"id\"], bounded)",
        "add_annotation(",
        "list_annotations(engine_module, book[\"id\"], limit=2000)",
        "delete_annotation(engine_module, item[\"id\"])",
        "show_pdf_reader(engine_module, book, parent=dialog, on_change=refresh_detail)",
    ):
        assert call in source
    for label in (
        "阅读设置",
        "标注与笔记",
        "Focus Mode",
        "阅读模式",
        "漫画方向",
        "打开 PDF 阅读器",
        "Zoom、页码、全文搜索、书签、高亮、笔记",
    ):
        assert label in source


def run_test() -> None:
    install_desktop_reader(FakeEngine)
    assert getattr(FakeWindow, "_galaxy_desktop_reader_installed", False)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-reader") == 1
    install_desktop_reader(FakeEngine)
    assert registered_after_build_ui_hooks(FakeWindow).count("desktop-reader") == 1
    test_settings_helpers()
    test_annotation_helpers_and_wiring()
    run_desktop_reader_self_test()


if __name__ == "__main__":
    run_test()
    print("Desktop Reader self-test passed")
