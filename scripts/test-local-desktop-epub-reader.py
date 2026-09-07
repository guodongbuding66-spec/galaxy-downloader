from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_epub_reader import (  # noqa: E402
    EpubPosition,
    EpubRange,
    _initial_chapter,
    _normalize_settings,
    _parse_position_locator,
    _parse_range_locator,
    _position_locator,
    _progress_percent,
    _range_locator,
    _text_columns,
    _theme_palette,
    run_desktop_epub_reader_self_test,
)
from desktop_reader import run_desktop_reader_self_test  # noqa: E402
from reader_epub import epub_chapter, epub_document  # noqa: E402
from reader_epub_search import epub_search  # noqa: E402
from reader_workspace import (  # noqa: E402
    add_annotation,
    add_bookmark,
    import_book,
    list_annotations,
    list_bookmarks,
    list_books,
    update_reader_settings,
    update_reading_position,
)


def _write_epub(path: Path) -> None:
    container = """<?xml version='1.0'?>
<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' version='1.0'>
<rootfiles><rootfile full-path='OPS/content.opf'/></rootfiles></container>"""
    package = """<?xml version='1.0'?>
<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
<manifest>
<item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/>
<item id='intro' href='text/intro.xhtml' media-type='application/xhtml+xml'/>
<item id='chapter' href='text/chapter.xhtml' media-type='application/xhtml+xml'/>
</manifest>
<spine><itemref idref='intro'/><itemref idref='chapter'/></spine>
</package>"""
    nav = """<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'>
<body><nav epub:type='toc'><ol>
<li><a href='text/intro.xhtml'>Introduction</a>
  <ol><li><a href='text/chapter.xhtml#deep'>Deep section</a></li></ol>
</li>
</ol></nav></body></html>"""
    intro = """<html><head><title>Introduction</title><style>hidden galaxy</style></head>
<body><h1>Introduction</h1><p>Galaxy desktop reading starts here.</p>
<script>secret galaxy</script><p>Readable introduction text.</p></body></html>"""
    chapter = """<html><head><title>Chapter Two</title></head><body>
<h1 id='deep'>Chapter Two</h1><p>The second GALAXY result lives in this chapter.</p>
<p>Highlight this exact sentence for annotation persistence.</p></body></html>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/content.opf", package)
        archive.writestr("OPS/nav.xhtml", nav)
        archive.writestr("OPS/text/intro.xhtml", intro)
        archive.writestr("OPS/text/chapter.xhtml", chapter)


def _assert_no_paths(value) -> None:  # noqa: ANN001
    forbidden = {"path", "filePath", "managedPath", "contentRoot", "opfPath", "href", "sourcePath"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value.keys()), value
        for nested in value.values():
            _assert_no_paths(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_paths(nested)


def run_test() -> None:
    run_desktop_epub_reader_self_test()
    run_desktop_reader_self_test()

    ids = {"epub-chapter:1", "epub-chapter:2"}
    assert _position_locator("epub-chapter:1", 31) == "epub-chapter:1@char:31"
    assert _range_locator("epub-chapter:2", 4, 19) == "epub-chapter:2@chars:4-19"
    assert _parse_position_locator("epub-chapter:2@char:7", ids) == EpubPosition("epub-chapter:2", 7)
    assert _parse_range_locator("epub-chapter:2@chars:4-19", ids, 50) == EpubRange("epub-chapter:2", 4, 19)
    assert _parse_position_locator("epub-chapter:9@char:7", ids) is None
    assert _parse_range_locator("epub-chapter:2@chars:50-60", ids, 50) is None
    assert _progress_percent(0, 2, 50, 100) == 25.0
    assert _progress_percent(1, 2, 100, 100) == 100.0
    assert 32 <= _text_columns(820, 18) <= 180
    assert _theme_palette("dark")[0:2] == ("#202124", "#f1f3f4")
    assert _theme_palette("system", "#101010", "#efefef")[0:2] == ("#101010", "#efefef")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        source = root / "source"
        for target in (state, data, source):
            target.mkdir()

        class Engine:
            APP_NAME = "Desktop EPUB Test"

            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

        source_epub = source / "desktop-reader.epub"
        _write_epub(source_epub)
        book = import_book(Engine, source_epub, title="Desktop EPUB Fixture")
        assert book["format"] == "epub"

        document = epub_document(Engine, book["id"])
        assert document["chapterCount"] == 2
        assert [row["id"] for row in document["chapters"]] == ["epub-chapter:1", "epub-chapter:2"]
        assert [row["depth"] for row in document["toc"]] == [0, 1]
        _assert_no_paths(document)

        first = epub_chapter(Engine, book["id"], "epub-chapter:1")
        second = epub_chapter(Engine, book["id"], "epub-chapter:2")
        assert "secret galaxy" not in first["text"].lower()
        assert "hidden galaxy" not in first["text"].lower()
        assert second["previousChapterId"] == "epub-chapter:1"
        assert first["nextChapterId"] == "epub-chapter:2"

        search = epub_search(Engine, book["id"], "galaxy", limit=20)
        assert [row["chapterId"] for row in search["results"]] == ["epub-chapter:1", "epub-chapter:2"]
        for row in search["results"]:
            chapter = first if row["chapterId"] == "epub-chapter:1" else second
            match = chapter["text"][row["offset"] : row["offset"] + row["length"]]
            assert match.lower() == "galaxy"
        _assert_no_paths(search)

        position = _position_locator("epub-chapter:2", 12)
        update_reading_position(Engine, book["id"], 56.25, position)
        saved_settings = update_reader_settings(
            Engine,
            book["id"],
            {"fontSize": 22, "contentWidth": 960, "theme": "sepia", "focusMode": True},
        )
        assert saved_settings["fontSize"] == 22
        assert saved_settings["contentWidth"] == 960
        assert saved_settings["theme"] == "sepia"
        assert saved_settings["focusMode"] is True

        bookmark = add_bookmark(Engine, book["id"], position, label="Chapter Two · 56.3%")
        selection_text = "Highlight this exact sentence"
        selection_start = second["text"].index(selection_text)
        selection_end = selection_start + len(selection_text)
        selection_locator = _range_locator("epub-chapter:2", selection_start, selection_end)
        highlight = add_annotation(
            Engine,
            book["id"],
            selection_locator,
            kind="highlight",
            selected_text=selection_text,
        )
        note = add_annotation(
            Engine,
            book["id"],
            selection_locator,
            kind="note",
            selected_text=selection_text,
            note="Desktop EPUB note",
        )

        stored = next(row for row in list_books(Engine, limit=20) if row["id"] == book["id"])
        assert stored["locator"] == position
        assert abs(float(stored["progressPercent"]) - 56.25) < 0.001
        assert _normalize_settings(stored) == {
            "fontSize": 22,
            "contentWidth": 960,
            "theme": "sepia",
            "focusMode": True,
        }
        initial = _initial_chapter(stored, ["epub-chapter:1", "epub-chapter:2"])
        assert initial == EpubPosition("epub-chapter:2", 12)

        bookmarks = list_bookmarks(Engine, book["id"], limit=20)
        assert bookmarks == [bookmark]
        annotations = list_annotations(Engine, book["id"], limit=20)
        assert [item["id"] for item in annotations] == [highlight["id"], note["id"]]
        assert _parse_range_locator(annotations[0]["locator"], ids, len(second["text"])) == EpubRange(
            "epub-chapter:2", selection_start, selection_end
        )
        assert second["text"][selection_start:selection_end] == selection_text

        reader_source = (LOCAL_ENGINE / "desktop_reader.py").read_text(encoding="utf-8")
        assert "打开 EPUB 阅读器" in reader_source
        assert "show_epub_reader(engine_module, book, parent=dialog, on_change=refresh_detail)" in reader_source
        assert 'format_id == "epub"' in reader_source


if __name__ == "__main__":
    run_test()
    print("Desktop EPUB reader tests passed")
