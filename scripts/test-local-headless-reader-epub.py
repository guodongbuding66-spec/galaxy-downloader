from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from headless_api import GalaxyApiServer  # noqa: E402
from headless_media_api import HeadlessMediaApi, HeadlessMediaContext  # noqa: E402
from headless_reader_api import HeadlessReaderApi, HeadlessReaderContext  # noqa: E402
from headless_service import HeadlessRuntime  # noqa: E402
from reader_workspace import import_book  # noqa: E402

TOKEN = "reader-epub-test-token"


def _write_epub(path: Path) -> None:
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
<li><a href='Text/ch1.xhtml'>One</a></li><li><a href='Text/ch2.xhtml'>Two</a></li>
</ol></nav></body></html>"""
    first = """<html><head><title>One</title><style>.secret{display:none}</style></head>
<body><h1>One</h1><p>Headless EPUB chapter text.</p><script>privateToken()</script></body></html>"""
    second = "<html><head><title>Two</title></head><body><p>Second chapter.</p></body></html>"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/package.opf", package)
        archive.writestr("OEBPS/nav.xhtml", nav)
        archive.writestr("OEBPS/Text/ch1.xhtml", first)
        archive.writestr("OEBPS/Text/ch2.xhtml", second)


def _request_json(url: str, *, token: str | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _assert_no_paths(value) -> None:  # noqa: ANN001
    forbidden = {"path", "filePath", "managedPath", "contentRoot", "opfPath", "href", "sourcePath", "cookieFile", "httpHeaders"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value.keys()), value
        for nested in value.values():
            _assert_no_paths(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_paths(nested)


def run() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        downloads = root / "downloads"
        state = root / "state"
        data = root / "data"
        program = root / "program"
        source = root / "source"
        for target in (downloads, state, data, program, source):
            target.mkdir()

        reader_context = HeadlessReaderContext(program, data, state)
        epub = source / "Headless.epub"
        _write_epub(epub)
        imported = import_book(reader_context, epub, title="Headless EPUB")
        text = source / "Plain.txt"
        text.write_text("plain text", encoding="utf-8")
        non_epub = import_book(reader_context, text, title="Plain")
        reader_api = HeadlessReaderApi(context=reader_context)

        direct = reader_api.epub_document(imported["id"])
        assert direct["chapterCount"] == 2
        assert direct["chapters"][0]["id"] == "epub-chapter:1"
        _assert_no_paths(direct)

        media_context = HeadlessMediaContext(program, state, downloads)
        media_api = HeadlessMediaApi(downloads, context=media_context)
        runtime = HeadlessRuntime(downloads, max_queue_size=2)
        server = GalaxyApiServer(
            ("127.0.0.1", 0), runtime, TOKEN, "127.0.0.1", media_api, reader_api=reader_api
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            document_url = base + f"/v1/reader/books/{imported['id']}/epub"

            code, payload = _request_json(document_url)
            assert code == 401 and payload["error"] == "unauthorized"
            code, payload = _request_json(document_url + f"?token={TOKEN}")
            assert code == 401 and payload["error"] == "unauthorized"
            code, payload = _request_json(document_url, token="wrong-token")
            assert code == 401

            code, document = _request_json(document_url, token=TOKEN)
            assert code == 200 and document["ok"] is True and document["chapterCount"] == 2
            _assert_no_paths(document)
            serialized = json.dumps(document, ensure_ascii=False)
            assert str(data) not in serialized and str(source) not in serialized and str(program) not in serialized

            chapter_url = document_url + "/chapters/epub-chapter%3A1"
            code, chapter = _request_json(chapter_url, token=TOKEN)
            assert code == 200 and chapter["chapterId"] == "epub-chapter:1"
            assert "Headless EPUB chapter text." in chapter["text"]
            assert "privateToken" not in chapter["text"] and "display:none" not in chapter["text"]
            assert chapter["nextChapterId"] == "epub-chapter:2"
            _assert_no_paths(chapter)

            code, missing_chapter = _request_json(document_url + "/chapters/epub-chapter%3A99", token=TOKEN)
            assert code == 404 and missing_chapter["error"] == "EPUB chapter not found"
            code, invalid_chapter = _request_json(document_url + "/chapters/not-a-chapter", token=TOKEN)
            assert code == 400 and invalid_chapter["error"] == "invalid EPUB chapter id"

            missing_book = "0" * 32
            code, missing = _request_json(base + f"/v1/reader/books/{missing_book}/epub", token=TOKEN)
            assert code == 404 and missing["error"] == "book not found"
            code, wrong_format = _request_json(base + f"/v1/reader/books/{non_epub['id']}/epub", token=TOKEN)
            assert code == 400 and wrong_format["error"] == "book is not EPUB"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless Reader EPUB tests passed")
