from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
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

TOKEN = "reader-pdf-test-token"


def _stream(content: bytes) -> bytes:
    return f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream"


def _write_pdf(path: Path) -> None:
    page_one = (
        b"BT\n/F1 18 Tf\n72 720 Td\n(Headless Galaxy PDF page one) Tj\n"
        b"0 -40 Td\n(Selection target phrase) Tj\nET"
    )
    page_two = b"BT\n/F1 18 Tf\n72 720 Td\n(Second GALAXY result) Tj\nET"
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        4: _stream(page_one),
        5: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        6: _stream(page_two),
        7: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for number in range(1, len(objects) + 1):
        offsets[number] = len(payload)
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(objects[number])
        payload.extend(b"\nendobj\n")
    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for number in range(1, len(objects) + 1):
        payload.extend(f"{offsets[number]:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(payload)


def _request(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: dict | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _json_response(*args, **kwargs) -> tuple[int, dict, dict[str, str]]:  # noqa: ANN002,ANN003
    status, headers, body = _request(*args, **kwargs)
    return status, json.loads(body.decode("utf-8")), headers


def _assert_no_paths(value) -> None:  # noqa: ANN001
    forbidden = {
        "path",
        "filePath",
        "managedPath",
        "contentRoot",
        "sourcePath",
        "pdfPath",
        "cookieFile",
        "httpHeaders",
    }
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
        pdf_file = source / "Headless.pdf"
        _write_pdf(pdf_file)
        imported = import_book(reader_context, pdf_file, title="Headless PDF")
        text = source / "Plain.txt"
        text.write_text("plain text", encoding="utf-8")
        non_pdf = import_book(reader_context, text, title="Plain")
        reader_api = HeadlessReaderApi(context=reader_context)

        direct_document = reader_api.pdf_document(imported["id"])
        assert direct_document["pageCount"] == 2
        direct_page = reader_api.pdf_page(imported["id"], "pdf-page:1")
        assert "Headless Galaxy PDF page one" in direct_page["text"]
        direct_search = reader_api.pdf_search(imported["id"], "galaxy", max_pages=2, limit=10)
        assert [row["pageNumber"] for row in direct_search["results"]] == [1, 2]
        direct_selection = reader_api.pdf_selection(
            imported["id"],
            "pdf-page:1",
            {"left": 60, "bottom": 650, "right": 450, "top": 750},
        )
        assert "Selection target phrase" in direct_selection["text"]
        direct_render = reader_api.pdf_render_png(imported["id"], "pdf-page:1", scale=1.0)
        assert direct_render.body.startswith(b"\x89PNG\r\n\x1a\n")
        assert direct_render.pixel_width > 500 and direct_render.pixel_height > 700
        for value in (direct_document, direct_page, direct_search, direct_selection):
            _assert_no_paths(value)

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
            document_url = base + f"/v1/reader/books/{imported['id']}/pdf"

            code, payload, _headers = _json_response(document_url)
            assert code == 401 and payload["error"] == "unauthorized"
            code, payload, _headers = _json_response(document_url + f"?token={TOKEN}")
            assert code == 401 and payload["error"] == "unauthorized"
            code, payload, _headers = _json_response(document_url, token="wrong-token")
            assert code == 401

            code, document, headers = _json_response(document_url, token=TOKEN)
            assert code == 200 and document["ok"] is True and document["pageCount"] == 2
            assert headers.get("Cache-Control") == "no-store"
            _assert_no_paths(document)

            page_url = document_url + "/pages/pdf-page%3A1"
            code, page, _headers = _json_response(page_url, token=TOKEN)
            assert code == 200 and page["pageNumber"] == 1
            assert "Headless Galaxy PDF page one" in page["text"]
            _assert_no_paths(page)

            query = urllib.parse.urlencode({"q": "galaxy", "maxPages": 2, "limit": 10})
            code, search, _headers = _json_response(document_url + "/search?" + query, token=TOKEN)
            assert code == 200 and [row["pageNumber"] for row in search["results"]] == [1, 2]
            _assert_no_paths(search)

            selection_url = page_url + "/selection"
            code, selection, _headers = _json_response(
                selection_url,
                token=TOKEN,
                method="POST",
                payload={"left": 60, "bottom": 650, "right": 450, "top": 750},
            )
            assert code == 200 and "Selection target phrase" in selection["text"]
            _assert_no_paths(selection)

            render_url = page_url + "/render?scale=1.25"
            status, render_headers, render_body = _request(render_url, token=TOKEN)
            assert status == 200
            assert render_headers.get("Content-Type") == "image/png"
            assert render_headers.get("Cache-Control") == "no-store"
            assert render_headers.get("X-Content-Type-Options") == "nosniff"
            assert render_body.startswith(b"\x89PNG\r\n\x1a\n")
            assert len(render_body) < 32 * 1024 * 1024

            code, payload, _headers = _json_response(page_url + f"/render?token={TOKEN}")
            assert code == 401 and payload["error"] == "unauthorized"

            code, missing, _headers = _json_response(document_url + "/pages/pdf-page%3A99", token=TOKEN)
            assert code == 404 and missing["error"] == "PDF 页面不存在"
            code, invalid, _headers = _json_response(document_url + "/pages/not-a-page", token=TOKEN)
            assert code == 400 and invalid["error"] == "PDF page ID 无效"
            code, wrong_format, _headers = _json_response(
                base + f"/v1/reader/books/{non_pdf['id']}/pdf", token=TOKEN
            )
            assert code == 400 and wrong_format["error"] == "book is not PDF"
            code, missing_selection, _headers = _json_response(
                selection_url,
                token=TOKEN,
                method="POST",
                payload={"left": 1, "bottom": 2},
            )
            assert code == 400 and missing_selection["error"] == "PDF selection rectangle is incomplete"

            original_pdf_document = reader_api.pdf_document
            reader_api.pdf_document = lambda _book_id: (_ for _ in ()).throw(  # type: ignore[method-assign]
                RuntimeError(f"secret internal path {data / 'reader.sqlite3'}")
            )
            try:
                code, failed, _headers = _json_response(document_url, token=TOKEN)
                assert code == 502 and failed["error"] == "reader PDF request failed"
                assert str(data) not in json.dumps(failed)
            finally:
                reader_api.pdf_document = original_pdf_document  # type: ignore[method-assign]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            runtime.stop()


if __name__ == "__main__":
    run()
    print("Headless Reader PDF tests passed")
