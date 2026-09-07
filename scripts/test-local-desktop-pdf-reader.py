from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_pdf_reader import (  # noqa: E402
    PdfRect,
    _canvas_rect_to_pdf,
    _page_number_from_locator,
    _parse_rect_locator,
    _pdf_rect_to_canvas,
    _progress_percent,
    _rect_locator,
    run_desktop_pdf_reader_self_test,
)
from reader_pdf import pdf_document, pdf_text_in_rect, render_pdf_page  # noqa: E402
from reader_workspace import (  # noqa: E402
    add_annotation,
    add_bookmark,
    import_book,
    list_annotations,
    list_bookmarks,
    update_reader_settings,
    update_reading_position,
)


def _stream(content: bytes) -> bytes:
    return f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream"


def _write_pdf(path: Path) -> None:
    page_one = (
        b"BT\n/F1 18 Tf\n72 720 Td\n(Galaxy desktop PDF) Tj\n"
        b"0 -40 Td\n(Selectable highlight phrase) Tj\nET"
    )
    page_two = b"BT\n/F1 18 Tf\n72 720 Td\n(Second page note target) Tj\nET"
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


def run_test() -> None:
    run_desktop_pdf_reader_self_test()

    rect = PdfRect(60.0, 650.0, 420.0, 750.0)
    locator = _rect_locator("pdf-page:1", rect)
    parsed = _parse_rect_locator(locator)
    assert parsed is not None and parsed[0] == "pdf-page:1" and parsed[1] == rect
    assert _page_number_from_locator(locator, 2) == 1
    assert _progress_percent(2, 2) == 100.0

    canvas_rect = _pdf_rect_to_canvas(rect, origin=(24.0, 24.0), scale=1.25, page_height=792.0)
    roundtrip = _canvas_rect_to_pdf(
        (canvas_rect[0], canvas_rect[1]),
        (canvas_rect[2], canvas_rect[3]),
        origin=(24.0, 24.0),
        scale=1.25,
        page_width=612.0,
        page_height=792.0,
    )
    assert roundtrip is not None
    assert max(
        abs(roundtrip.left - rect.left),
        abs(roundtrip.bottom - rect.bottom),
        abs(roundtrip.right - rect.right),
        abs(roundtrip.top - rect.top),
    ) < 0.001

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

        pdf_file = source / "desktop.pdf"
        _write_pdf(pdf_file)
        book = import_book(Engine, pdf_file, title="Desktop PDF")
        document = pdf_document(Engine, book["id"])
        assert document["pageCount"] == 2

        rendered = render_pdf_page(Engine, book["id"], "pdf-page:1", scale=1.25)
        assert rendered.page_number == 1 and rendered.image.width > 700

        selected = pdf_text_in_rect(
            Engine,
            book["id"],
            "pdf-page:1",
            left=rect.left,
            bottom=rect.bottom,
            right=rect.right,
            top=rect.top,
        )
        assert "Galaxy desktop PDF" in selected["text"]
        assert "Selectable highlight phrase" in selected["text"]

        update_reading_position(Engine, book["id"], 50.0, "pdf-page:1")
        saved_settings = update_reader_settings(Engine, book["id"], {"focusMode": True})
        assert saved_settings["focusMode"] is True

        bookmark = add_bookmark(Engine, book["id"], "pdf-page:1", label="Page 1")
        assert list_bookmarks(Engine, book["id"])[0]["id"] == bookmark["id"]

        highlight = add_annotation(
            Engine,
            book["id"],
            locator,
            kind="highlight",
            selected_text=selected["text"],
        )
        note = add_annotation(
            Engine,
            book["id"],
            _rect_locator("pdf-page:2", PdfRect(60.0, 680.0, 360.0, 750.0)),
            kind="note",
            selected_text="Second page note target",
            note="Remember this",
        )
        annotations = list_annotations(Engine, book["id"])
        assert [row["id"] for row in annotations] == [highlight["id"], note["id"]]
        assert _parse_rect_locator(annotations[0]["locator"])[0] == "pdf-page:1"


if __name__ == "__main__":
    run_test()
    print("Desktop PDF reader tests passed")
