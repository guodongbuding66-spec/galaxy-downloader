from importlib.metadata import version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_curl_cffi_is_pinned_to_supported_release() -> None:
    assert version("curl-cffi") == "0.15.0"


def test_bgutil_pot_plugin_is_installed() -> None:
    assert version("bgutil-ytdlp-pot-provider") == "1.3.2"


def test_youtube_challenge_stack_is_fully_configured() -> None:
    config = (ROOT / "yt-dlp.conf").read_text(encoding="utf-8")
    assert "youtubepot-bgutilhttp:base_url=http://127.0.0.1:4416" in config
    assert "youtube:player_client=mweb" in config
    assert "--js-runtimes node" in config
