"""Certificate PDF renderer: Pillow image composed into a one-page PDF.

The canvas is A4 landscape at 150 DPI (1754x1240 px). Text uses the
bundled Be Vietnam Pro faces (OFL, see fonts/OFL.txt) because Pillow's
built-in default font has no Vietnamese glyphs.

``layout`` (the template's parsed layout_json dict) may override:
- ``title``/``subtitle``: headline and lead-in strings.
- ``title_y``, ``subtitle_y``, ``name_y``, ``body_y``, ``activity_y``,
  ``org_y``, ``meta_y``: baseline-center y positions in pixels.
- ``ink``/``accent``: "#rrggbb" text and ornament colors.
Unknown or invalid keys are ignored so a bad layout never breaks issue.
"""

from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from certificates.interfaces import CertificateRenderer

_FONT_DIR = Path(__file__).resolve().parent / "fonts"
_REGULAR = _FONT_DIR / "BeVietnamPro-Regular.ttf"
_BOLD = _FONT_DIR / "BeVietnamPro-Bold.ttf"

# A4 landscape at 150 DPI.
PAGE_W, PAGE_H = 1754, 1240
_MARGIN = 96

_DEFAULT_TITLE = "GI\u1ea4Y CH\u1ee8NG NH\u1eacN THAM GIA"
_DEFAULT_SUBTITLE = "Ch\u1ee9ng nh\u1eadn"
_BODY_TEXT = "\u0111\u00e3 ho\u00e0n th\u00e0nh ho\u1ea1t \u0111\u1ed9ng t\u00ecnh nguy\u1ec7n"
_ORG_PREFIX = "T\u1ed5 ch\u1ee9c: "
_ISSUED_PREFIX = "C\u1ea5p ng\u00e0y "
_SERIAL_PREFIX = "M\u00e3 x\u00e1c th\u1ef1c: "

_FALLBACK_NAME = "Sinh vi\u00ean"

_POS_DEFAULTS = {
    "title_y": 240,
    "subtitle_y": 400,
    "name_y": 560,
    "body_y": 690,
    "activity_y": 800,
    "org_y": 890,
    "meta_y": 1110,
}

_SIZE_DEFAULTS = {
    "title": 64,
    "subtitle": 34,
    "name": 84,
    "body": 36,
    "activity": 46,
    "org": 32,
    "meta": 26,
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled face; cached by FreeType internally."""
    return ImageFont.truetype(
        str(_BOLD if bold else _REGULAR), size
    )


def _fit(
    draw: ImageDraw.ImageDraw, text: str, bold: bool, size: int
) -> ImageFont.FreeTypeFont:
    """Shrink the face until the line fits inside the side margins."""
    max_w = PAGE_W - 2 * _MARGIN
    font = _font(bold, size)
    while size > 20 and draw.textlength(text, font=font) > max_w:
        size = int(size * 0.92)
        font = _font(bold, size)
    return font


def _layout_int(layout: dict, key: str, default: int) -> int:
    """Read a positive pixel offset, clamped inside the page."""
    value = layout.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return max(40, min(value, PAGE_H - 40))


def _layout_color(layout: dict, key: str, default: str) -> str:
    value = layout.get(key)
    if isinstance(value, str) and _HEX.match(value):
        return value
    return default


class PillowCertificateRenderer(CertificateRenderer):
    """Render the certificate onto an A4-landscape image, saved as PDF."""

    def render(
        self,
        *,
        student_name: str,
        org_name: str,
        activity_title: str,
        serial_no: str,
        issued_at: datetime | None,
        background: bytes | None,
        layout: dict,
    ) -> bytes:
        ink = _layout_color(layout, "ink", "#292524")
        accent = _layout_color(layout, "accent", "#92400e")
        page = self._canvas(background, accent)
        draw = ImageDraw.Draw(page)

        title = layout.get("title")
        if not isinstance(title, str) or not title.strip():
            title = _DEFAULT_TITLE
        subtitle = layout.get("subtitle")
        if not isinstance(subtitle, str) or not subtitle.strip():
            subtitle = _DEFAULT_SUBTITLE

        center_x = PAGE_W // 2

        def put(text: str, bold: bool, size_key: str, y_key: str) -> None:
            size = _SIZE_DEFAULTS[size_key]
            font = _fit(draw, text, bold, size)
            y = _layout_int(layout, y_key, _POS_DEFAULTS[y_key])
            draw.text(
                (center_x, y), text, font=font, fill=ink, anchor="mm"
            )

        font = _fit(draw, title, True, _SIZE_DEFAULTS["title"])
        y = _layout_int(layout, "title_y", _POS_DEFAULTS["title_y"])
        draw.text((center_x, y), title, font=font, fill=accent, anchor="mm")
        # Accent rule under the headline.
        rule_w = 240
        rule_y = y + _layout_int(layout, "title_gap", 64)
        draw.rectangle(
            (center_x - rule_w // 2, rule_y,
             center_x + rule_w // 2, rule_y + 4),
            fill=accent,
        )

        put(subtitle, False, "subtitle", "subtitle_y")
        put(student_name or _FALLBACK_NAME, True, "name", "name_y")
        put(_BODY_TEXT, False, "body", "body_y")
        put(activity_title, True, "activity", "activity_y")
        if org_name:
            put(_ORG_PREFIX + org_name, False, "org", "org_y")

        meta = _SERIAL_PREFIX + serial_no
        if issued_at is not None:
            meta = (
                _ISSUED_PREFIX
                + f"{issued_at.day:02d}/{issued_at.month:02d}"
                + f"/{issued_at.year} \u00b7 "
                + meta
            )
        put(meta, False, "meta", "meta_y")

        out = BytesIO()
        page.convert("RGB").save(out, "PDF", resolution=150.0)
        return out.getvalue()

    @staticmethod
    def _canvas(background: bytes | None, accent: str) -> Image.Image:
        """Background image fitted to the page, else white with a frame."""
        if background:
            try:
                img = Image.open(BytesIO(background))
                return ImageOps.fit(
                    img.convert("RGB"), (PAGE_W, PAGE_H),
                    method=Image.Resampling.LANCZOS,
                )
            except Exception:
                pass
        page = Image.new("RGB", (PAGE_W, PAGE_H), "#ffffff")
        draw = ImageDraw.Draw(page)
        draw.rectangle((28, 28, PAGE_W - 28, PAGE_H - 28), outline=accent, width=3)
        draw.rectangle((44, 44, PAGE_W - 44, PAGE_H - 44), outline=accent, width=1)
        return page
