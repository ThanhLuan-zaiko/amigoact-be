from datetime import UTC, datetime

from src.certificates.pdf import (
    BOLD,
    HOURS_SUFFIX,
    MAX_BACKGROUND_PIXELS,
    MIN_FONT_SIZE,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    REGULAR,
    PrintedTexts,
    date_text,
    fit_size,
    hours_text,
    load_background,
    page_point,
    render_pdf,
)
from src.certificates.template_schemas import Layout
from tests.media_helpers import PNG
from tests.pdf_helpers import picture_bytes

TEXTS = PrintedTexts(
    name="Nguy\u1ec5n V\u0103n A",
    activity="D\u1ecdn r\u00e1c b\u00e3i bi\u1ec3n",
    hours=hours_text(4.5),
    date="10/11/2026",
    serial="AMG-ABCD-EFGH-2345",
)


def test_pdf_is_one_a4_landscape_page_with_the_bundled_font() -> None:
    data = render_pdf(TEXTS, Layout(), None)

    assert data.startswith(b"%PDF")
    assert PAGE_WIDTH > PAGE_HEIGHT
    assert data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 1
    assert b"BeVietnamPro" in data
    assert b"/Subtype /Image" not in data


def test_background_picture_is_drawn() -> None:
    assert b"/Subtype /Image" in render_pdf(TEXTS, Layout(), picture_bytes("PNG"))
    assert b"/Subtype /Image" in render_pdf(TEXTS, Layout(), picture_bytes("WEBP"))


def test_broken_picture_leaves_the_page_plain() -> None:
    assert load_background(PNG) is None
    data = render_pdf(TEXTS, Layout(), PNG)
    assert data.startswith(b"%PDF")
    assert b"/Subtype /Image" not in data


def test_large_picture_is_scaled_down() -> None:
    picture = load_background(picture_bytes("JPEG", (5000, 3000)))

    assert picture is not None
    assert picture.width <= MAX_BACKGROUND_PIXELS[0]
    assert picture.height <= MAX_BACKGROUND_PIXELS[1]


def test_percentages_start_at_the_top_left() -> None:
    assert page_point(50, 50) == (PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
    assert page_point(0, 0) == (0, PAGE_HEIGHT)
    assert page_point(100, 100) == (PAGE_WIDTH, 0)


def test_long_text_shrinks_to_fit_and_short_text_keeps_its_size() -> None:
    assert fit_size("A", REGULAR, 28, 500) == 28
    long_size = fit_size("Rat dai " * 40, BOLD, 28, 500)
    assert MIN_FONT_SIZE <= long_size < 28


def test_hours_and_date_read_like_the_frontend() -> None:
    assert hours_text(4.5) == "4.5" + HOURS_SUFFIX
    assert hours_text(4.0) == "4" + HOURS_SUFFIX
    # 20:00 UTC is already the next day in Vietnam.
    assert date_text(datetime(2026, 11, 9, 20, 0, tzinfo=UTC)) == "10/11/2026"
