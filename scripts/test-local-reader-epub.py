from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from reader_epub import (  # noqa: E402
    EpubDocumentError,
    epub_chapter,
    epub_document,
    run_reader_epub_self_test,
)
from reader_workspace import import_book  # noqa: E402


def _write_epub3(path: Path) -> None:
    container = """<?xml version='1.0' encoding='UTF-8'?>
<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' version='1.0'>
  <rootfiles><rootfile full-path='OEBPS/package.opf' media-type='application/oebps-package+xml'/></rootfiles>
</container>"""
    package = """<?xml version='1.0' encoding='UTF-8'?>
<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>
  <manifest>
    <item id='nav' href='nav.xhtml' media-type='application/xhtml+xml' properties='nav'/>
    <item id='c1' href='Text/ch1.xhtml' media-type='application/xhtml+xml'/>
    <item id='c2' href='Text/ch2.xhtml' media-type='application/xhtml+xml'/>
  </manifest>
  <spine><itemref idref='c1'/><itemref idref='c2'/></spine>
</package>"""
    nav = """<?xml version='1.0' encoding='UTF-8'?>
<html xmlns='http://www.w3.org/1999/xhtml' xmlns:epub='http://www.idpf.org/2007/ops'>
<body><nav epub:type='toc'><ol>
  <li><a href='Text/ch1.xhtml#start'>Getting Started</a>
    <ol><li><a href='Text/ch2.xhtml'>Deep Dive</a></li></ol>
  </li>
  <li><a href='https://example.com/outside'>External</a></li>
  <li><a href='../../../outside.xhtml'>Traversal</a></li>
</ol></nav></body></html>"""
    ch1 = """<!doctype html><html><head><title>Chapter One</title><style>.x{display:none}</style></head>
<body><h1>Welcome</h1><p>Galaxy EPUB chapter one text.</p><script>secretToken()</script></body></html>"""
    ch2 = """<html><head><title>Chapter Two</title></head><body><h2>Details</h2><p>Second chapter body.</p></body></html>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/package.opf", package)
        archive.writestr("OEBPS/nav.xhtml", nav)
        archive.writestr("OEBPS/Text/ch1.xhtml", ch1)
        archive.writestr("OEBPS/Text/ch2.xhtml", ch2)


def _write_epub2(path: Path) -> None:
    container = """<?xml version='1.0'?>
<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' version='1.0'>
<rootfiles><rootfile full-path='OPS/content.opf'/></rootfiles></container>"""
    package = """<?xml version='1.0'?>
<package xmlns='http://www.idpf.org/2007/opf' version='2.0'>
<manifest>
  <item id='ncx' href='toc.ncx' media-type='application/x-dtbncx+xml'/>
  <item id='a' href='chapters/a.html' media-type='application/xhtml+xml'/>
  <item id='b' href='chapters/b.html' media-type='application/xhtml+xml'/>
</manifest>
<spine toc='ncx'><itemref idref='a'/><itemref idref='b'/></spine>
</package>"""
    ncx = """<?xml version='1.0'?>
<ncx xmlns='http://www.daisy.org/z3986/2005/ncx/'><navMap>
<navPoint id='n1'><navLabel><text>NCX One</text></navLabel><content src='chapters/a.html'/>
<navPoint id='n2'><navLabel><text>NCX Two</text></navLabel><content src='chapters/b.html#x'/></navPoint>
</navPoint></navMap></ncx>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/content.opf", package)
        archive.writestr("OPS/toc.ncx", ncx)
        archive.writestr("OPS/chapters/a.html", "<html><head><title>A</title></head><body><p>Alpha body</p></body></html>")
        archive.writestr("OPS/chapters/b.html", "<html><head><title>B</title></head><body><p>Beta body</p></body></html>")


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
    run_reader_epub_self_test()
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

        epub3 = source / "book3.epub"
        _write_epub3(epub3)
        imported3 = import_book(Engine, epub3, title="EPUB Three")
        document3 = epub_document(Engine, imported3["id"])
        assert document3["chapterCount"] == 2
        assert document3["chapters"] == [
            {"id": "epub-chapter:1", "index": 0, "title": "Getting Started"},
            {"id": "epub-chapter:2", "index": 1, "title": "Deep Dive"},
        ]
        assert document3["toc"] == [
            {"chapterId": "epub-chapter:1", "title": "Getting Started", "depth": 0},
            {"chapterId": "epub-chapter:2", "title": "Deep Dive", "depth": 1},
        ]
        _assert_no_paths(document3)

        first = epub_chapter(Engine, imported3["id"], "epub-chapter:1")
        assert first["previousChapterId"] is None
        assert first["nextChapterId"] == "epub-chapter:2"
        assert "Galaxy EPUB chapter one text." in first["text"]
        assert "secretToken" not in first["text"]
        assert "display:none" not in first["text"]
        _assert_no_paths(first)

        second = epub_chapter(Engine, imported3["id"], "epub-chapter:2")
        assert second["previousChapterId"] == "epub-chapter:1"
        assert second["nextChapterId"] is None

        epub2 = source / "book2.epub"
        _write_epub2(epub2)
        imported2 = import_book(Engine, epub2, title="EPUB Two")
        document2 = epub_document(Engine, imported2["id"])
        assert [row["title"] for row in document2["toc"]] == ["NCX One", "NCX Two"]
        assert [row["depth"] for row in document2["toc"]] == [0, 1]
        assert epub_chapter(Engine, imported2["id"], "epub-chapter:2")["text"] == "B\nBeta body"
        _assert_no_paths(document2)

        text = source / "not-epub.txt"
        text.write_text("plain", encoding="utf-8")
        non_epub = import_book(Engine, text)
        for bad_book, chapter_id in ((non_epub["id"], "epub-chapter:1"), (imported3["id"], "chapter:1")):
            try:
                epub_chapter(Engine, bad_book, chapter_id)
            except EpubDocumentError:
                pass
            else:
                raise AssertionError("invalid EPUB request was accepted")


if __name__ == "__main__":
    run_test()
    print("Reader EPUB document tests passed")
