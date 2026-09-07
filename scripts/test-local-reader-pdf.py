from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from reader_pdf import (  # noqa: E402
    ReaderPdfError,
    _bounded_scale,
    pdf_document,
    pdf_page,
    pdf_search,
    pdf_text_in_rect,
    render_pdf_page,
    run_reader_pdf_self_test,
)
from reader_workspace import import_book  # noqa: E402


def _stream(content: bytes) -> bytes:
    return f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream"


def _write_pdf(path: Path) -> None:
    page_one = (
        b"BT\n/F1 18 Tf\n72 720 Td\n(Galaxy PDF page one) Tj\n"
        b"0 -40 Td\n(Highlight target phrase) Tj\nET"
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


def _assert_no_paths(value) -> None:  # noqa: ANN001
    forbidden = {
        "path",
        "filePath",
        "managedPath",
        "contentRoot",
        "sourcePath",
        "pdfPath",
    }
    if isinstance(value, dict):
        assert not forbidden.intersection(value.keys()), value
        for nested in value.values():
            _assert_no_paths(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_paths(nested)


def run_test() -> None:
    run_reader_pdf_self_test()
    assert _bounded_scale(612.0, 792.0, 99) <= 4.0

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

        pdf_file = source / "fixture.pdf"
        _write_pdf(pdf_file)
        book = import_book(Engine, pdf_file, title="PDF Fixture")
        assert book["format"] == "pdf"

        document = pdf_document(Engine, book["id"])
        assert document == {
            "bookId": book["id"],
            "pageCount": 2,
            "firstPageId": "pdf-page:1",
            "lastPageId": "pdf-page:2",
        }
        _assert_no_paths(document)

        page_one = pdf_page(Engine, book["id"], "pdf-page:1")
        assert page_one["pageNumber"] == 1
        assert page_one["pageCount"] == 2
        assert page_one["previousPageId"] is None
        assert page_one["nextPageId"] == "pdf-page:2"
        assert abs(float(page_one["width"]) - 612.0) < 0.1
        assert abs(float(page_one["height"]) - 792.0) < 0.1
        assert "Galaxy PDF page one" in page_one["text"]
        assert "Highlight target phrase" in page_one["text"]
        _assert_no_paths(page_one)

        rendered = render_pdf_page(Engine, book["id"], "pdf-page:1", scale=1.25)
        assert rendered.book_id == book["id"]
        assert rendered.page_number == 1 and rendered.page_count == 2
        assert 760 <= rendered.image.width <= 770
        assert 985 <= rendered.image.height <= 995
        assert rendered.image.width * rendered.image.height <= 12_000_000
        assert rendered.image.mode in {"RGB", "RGBA"}
        # The fixture contains black text on a white page, so the render must not be blank.
        extrema = rendered.image.convert("L").getextrema()
        assert extrema[0] < extrema[1]

        selected = pdf_text_in_rect(
            Engine,
            book["id"],
            "pdf-page:1",
            left=60,
            bottom=650,
            right=420,
            top=750,
        )
        assert "Galaxy PDF page one" in selected["text"]
        assert "Highlight target phrase" in selected["text"]
        assert selected["rect"] == {"left": 60.0, "bottom": 650.0, "right": 420.0, "top": 750.0}
        _assert_no_paths(selected)

        first_search = pdf_search(
            Engine,
            book["id"],
            "galaxy",
            start_page=1,
            max_pages=1,
            limit=1,
        )
        assert len(first_search["results"]) == 1
        first_hit = first_search["results"][0]
        assert first_hit["pageId"] == "pdf-page:1"
        assert first_hit["pageNumber"] == 1
        assert first_hit["length"] == len("Galaxy")
        assert first_hit["rects"]
        assert first_search["truncated"] is True
        assert first_search["next"]["pageNumber"] == 1
        assert first_search["next"]["charIndex"] > first_hit["index"]
        _assert_no_paths(first_search)

        second_search = pdf_search(
            Engine,
            book["id"],
            "galaxy",
            start_page=first_search["next"]["pageNumber"],
            start_char=first_search["next"]["charIndex"],
            max_pages=2,
            limit=20,
        )
        assert [row["pageNumber"] for row in second_search["results"]] == [2]
        assert second_search["truncated"] is False
        assert second_search["next"] is None
        _assert_no_paths(second_search)

        try:
            pdf_page(Engine, book["id"], "pdf-page:3")
        except ReaderPdfError as exc:
            assert "页面不存在" in str(exc)
        else:
            raise AssertionError("out-of-range PDF page was accepted")

        text_file = source / "plain.txt"
        text_file.write_text("not pdf", encoding="utf-8")
        text_book = import_book(Engine, text_file)
        try:
            pdf_document(Engine, text_book["id"])
        except ReaderPdfError as exc:
            assert str(root) not in str(exc)
        else:
            raise AssertionError("non-PDF book was accepted by PDF core")

        broken_pdf = source / "broken.pdf"
        broken_pdf.write_bytes(b"%PDF-1.4\nnot a document")
        broken_book = import_book(Engine, broken_pdf)
        try:
            pdf_document(Engine, broken_book["id"])
        except ReaderPdfError as exc:
            assert str(root) not in str(exc)
            assert "PDF" in str(exc)
        else:
            raise AssertionError("broken PDF was accepted")


if __name__ == "__main__":
    run_test()
    print("Reader PDF core tests passed")
