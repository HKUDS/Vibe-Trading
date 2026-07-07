"""Validate social-card metadata for static wiki pages."""

from __future__ import annotations

import struct
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MetaParser(HTMLParser):
    """Collect simple head metadata from a static HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attr_map = {name: value or "" for name, value in attrs}
        key = attr_map.get("property") or attr_map.get("name")
        content = attr_map.get("content")
        if key and content:
            self.meta[key] = content


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) < 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AssertionError(f"{path} is not a PNG file")
    return struct.unpack(">II", header[16:24])


def page_meta(relative_path: str) -> dict[str, str]:
    parser = MetaParser()
    parser.feed((ROOT / relative_path).read_text(encoding="utf-8"))
    return parser.meta


def require_alpha_library_card() -> None:
    expected_url = "https://vibetrading.wiki/assets/alpha-library-og.png"
    expected_asset = ROOT / "assets" / "alpha-library-og.png"
    meta = page_meta("alpha-library/index.html")

    assert meta.get("og:image") == expected_url, "Alpha Library og:image must use the 1200x630 card"
    assert meta.get("twitter:card") == "summary_large_image", "Alpha Library must request a large Twitter card"
    assert meta.get("twitter:image") == expected_url, "Alpha Library twitter:image must match og:image"
    assert expected_asset.exists(), f"Missing {expected_asset.relative_to(ROOT)}"
    assert png_size(expected_asset) == (1200, 630), "Alpha Library social card must be 1200x630"


def main() -> None:
    require_alpha_library_card()


if __name__ == "__main__":
    main()
