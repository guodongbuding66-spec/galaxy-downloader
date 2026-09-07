from __future__ import annotations

import io
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENGINE = ROOT / "local-engine"
if str(LOCAL_ENGINE) not in sys.path:
    sys.path.insert(0, str(LOCAL_ENGINE))

from desktop_cbz_reader import (  # noqa: E402
    DesktopCbzReaderError,
    VERTICAL_WINDOW_PAGES,
    _decode_page,
    _fit_dimensions,
    _locator_page_index,
    _max_start_index,
    _navigation_step,
    _opaque_locator,
    _read_cbz_page_bytes,
    _settings_from_book,
    _visible_page_indices,
    run_desktop_cbz_reader_self_test,
)
from reader_workspace import cbz_pages, import_book  # noqa: E402


def _image_bytes(size: tuple[int, int], format_id: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(buffer, format=format_id)
    return buffer.getvalue()


def run_test() -> None:
    run_desktop_cbz_reader_self_test()

    assert _visible_page_indices(7, 2, "double", "ltr") == [2, 3]
    assert _visible_page_indices(7, 2, "double", "rtl") == [3, 2]
    assert _visible_page_indices(4, 3, "single", "ltr") == [3]
    assert _max_start_index(4, "vertical") == 0
    assert _max_start_index(20, "vertical") == 20 - VERTICAL_WINDOW_PAGES
    assert _navigation_step("vertical") == VERTICAL_WINDOW_PAGES
    assert _navigation_step("fit-width") == 1
    assert _locator_page_index("cbz-page:99", 4) == 3
    assert _locator_page_index("legacy", 5, 50) == 2
    assert _opaque_locator(-5) == "cbz-page:1"
    assert _fit_dimensions(400, 800, 1000, 700, "fit-width")[0] == 954
    assert _fit_dimensions(4000, 2000, 1000, 700, "single") == (960, 480)

    mode, direction, focus = _settings_from_book(
        {"settings": {"readingMode": "double", "mangaDirection": "rtl", "focusMode": True}}
    )
    assert (mode, direction, focus) == ("double", "rtl", True)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        state = root / "state"
        data = root / "data"
        source = root / "source"
        state.mkdir()
        data.mkdir()
        source.mkdir()

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

        cbz_file = source / "comic.cbz"
        first = _image_bytes((40, 60), "PNG")
        second = _image_bytes((80, 40), "JPEG")
        with zipfile.ZipFile(cbz_file, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("001.png", first)
            archive.writestr("chapter/002.jpg", second)
            archive.writestr("notes.txt", b"not an image page")

        book = import_book(Engine, cbz_file)
        pages = cbz_pages(Engine, book["id"])
        assert pages == ["001.png", "chapter/002.jpg"]

        payload = _read_cbz_page_bytes(Engine, book["id"], "001.png")
        image = _decode_page(payload)
        assert image.size == (40, 60)
        assert image.mode == "RGB"

        nested_payload = _read_cbz_page_bytes(Engine, book["id"], "chapter/002.jpg")
        assert _decode_page(nested_payload).size == (80, 40)

        for unsafe in ("notes.txt", "../001.png", "", "chapter\\..\\notes.txt"):
            try:
                _read_cbz_page_bytes(Engine, book["id"], unsafe)
            except DesktopCbzReaderError:
                pass
            else:
                raise AssertionError(f"unmanaged CBZ member was readable: {unsafe!r}")

        try:
            _decode_page(b"not-an-image")
        except DesktopCbzReaderError:
            pass
        else:
            raise AssertionError("invalid image payload was decoded")


if __name__ == "__main__":
    run_test()
    print("Desktop CBZ reader tests passed")
