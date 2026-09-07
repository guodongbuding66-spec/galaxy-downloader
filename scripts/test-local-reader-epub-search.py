from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from reader_epub import epub_chapter  # noqa: E402
from reader_epub_search import EpubSearchError, epub_search, run_reader_epub_search_self_test  # noqa: E402
from reader_workspace import import_book  # noqa: E402


def _write_epub(path: Path) -> None:
    container = """<?xml version='1.0'?>
<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' version='1.0'>
<rootfiles><rootfile full-path='OPS/content.opf'/></rootfiles></container>"""
    package = """<?xml version='1.0'?>
<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
<manifest>
<item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/>
<item id='a' href='a.xhtml' media-type='application/xhtml+xml'/>
<item id='b' href='b.xhtml' media-type='application/xhtml+xml'/>
</manifest><spine><itemref idref='a'/><itemref idref='b'/></spine></package>"""
    nav = """<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'>
<body><nav epub:type='toc'><ol><li><a href='a.xhtml'>Alpha</a></li><li><a href='b.xhtml'>Beta</a></li></ol></nav></body></html>"""
    a = """<html><head><title>Alpha</title><style>Galaxy hidden</style></head>
<body><p>Galaxy Reader starts here.</p><script>Galaxy secret</script><p>Another galaxy appears.</p></body></html>"""
    b = "<html><head><title>Beta</title></head><body><p>Final GALAXY chapter.</p></body></html>"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/content.opf", package)
        archive.writestr("OPS/nav.xhtml", nav)
        archive.writestr("OPS/a.xhtml", a)
        archive.writestr("OPS/b.xhtml", b)


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
    run_reader_epub_search_self_test()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        source = root / "source"
        for target in (state, data, source):
            target.mkdir()

        class Engine:
            @staticmethod
            def app_dir() -> Path:
                return root

            @staticmethod
            def state_dir() -> Path:
                return state

            @staticmethod
            def data_dir() -> Path:
                return data

        epub = source / "search.epub"
        _write_epub(epub)
        book = import_book(Engine, epub, title="Search Book")
        result = epub_search(Engine, book["id"], "galaxy", limit=20)
        assert result["bookId"] == book["id"]
        assert result["query"] == "galaxy"
        assert len(result["results"]) == 3
        assert [row["chapterId"] for row in result["results"]] == [
            "epub-chapter:1",
            "epub-chapter:1",
            "epub-chapter:2",
        ]
        assert all("hidden" not in row["snippet"] and "secret" not in row["snippet"] for row in result["results"])
        _assert_no_paths(result)

        for row in result["results"]:
            chapter = epub_chapter(Engine, book["id"], row["chapterId"])
            found = chapter["text"][row["offset"] : row["offset"] + row["length"]]
            assert found.lower() == "galaxy"
            assert row["snippetStart"] <= row["offset"]

        limited = epub_search(Engine, book["id"], "galaxy", limit=2)
        assert len(limited["results"]) == 2 and limited["truncated"] is True

        empty = epub_search(Engine, book["id"], "not present", limit=20)
        assert empty["results"] == [] and empty["truncated"] is False

        try:
            epub_search(Engine, book["id"], "   ")
        except EpubSearchError:
            pass
        else:
            raise AssertionError("empty EPUB search query was accepted")

        text = source / "plain.txt"
        text.write_text("galaxy", encoding="utf-8")
        non_epub = import_book(Engine, text)
        try:
            epub_search(Engine, non_epub["id"], "galaxy")
        except EpubSearchError:
            pass
        else:
            raise AssertionError("non-EPUB search was accepted")


if __name__ == "__main__":
    run_test()
    print("Reader EPUB search tests passed")
