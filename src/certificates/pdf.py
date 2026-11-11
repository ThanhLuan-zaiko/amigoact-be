"""The certificate as a PDF: A4 landscape, drawn from its template.

The page matches the frontend preview: positions are percentages of the page, x is the
center of the text, y is its middle, and font sizes are points on the A4 page.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status
from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.auth.errors import api_error
from src.certificates import service
from src.certificates.template_schemas import Layout
from src.media import service as media_service
from src.models.certificates import Certificate, CertificateTemplate

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
REGULAR = "BeVietnamPro"
BOLD = "BeVietnamPro-Bold"
NAME_COLOR = HexColor("#0f172a")
TEXT_COLOR = HexColor("#334155")
# Texts keep a margin on both sides, so a long title shrinks instead of leaving the page.
MAX_TEXT_WIDTH = PAGE_WIDTH * 0.9
MIN_FONT_SIZE = 6.0
# Enough for A4 at 300 dpi. Larger pictures are scaled down to keep the file small.
MAX_BACKGROUND_PIXELS = (3508, 2480)
# Vietnam has no daylight saving time, so a fixed offset is exact.
VIETNAM = timezone(timedelta(hours=7))
# Vietnamese for "volunteer hours", written as escapes because code stays ASCII.
HOURS_SUFFIX = " gi\u1edd t\u00ecnh nguy\u1ec7n"


@dataclass(frozen=True)
class PrintedTexts:
    name: str
    activity: str
    hours: str
    date: str
    serial: str


def _register_fonts() -> None:
    registered = pdfmetrics.getRegisteredFontNames()
    for name, file in ((REGULAR, "Regular"), (BOLD, "Bold")):
        if name not in registered:
            path = FONT_DIR / f"BeVietnamPro-{file}.ttf"
            pdfmetrics.registerFont(TTFont(name, str(path)))


def hours_text(hours: float) -> str:
    """4.5 stays 4.5 and 4.0 becomes 4, as the frontend shows it."""
    return f"{hours:g}{HOURS_SUFFIX}"


def date_text(moment: datetime) -> str:
    return moment.astimezone(VIETNAM).strftime("%d/%m/%Y")


def fit_size(text: str, font: str, size: float, max_width: float) -> float:
    """The largest size up to `size` at which the text fits in `max_width`."""
    _register_fonts()
    width = pdfmetrics.stringWidth(text, font, size)
    if width <= max_width:
        return size
    return max(MIN_FONT_SIZE, size * max_width / width)


def page_point(x_percent: float, y_percent: float) -> tuple[float, float]:
    """PDF points start at the bottom left. Template percentages start at the top left."""
    return x_percent / 100 * PAGE_WIDTH, PAGE_HEIGHT - y_percent / 100 * PAGE_HEIGHT


def load_background(data: bytes) -> Image.Image | None:
    """Decode the whole picture now, so a broken file leaves the page plain instead of
    failing halfway. Uploads are checked by their first bytes only."""
    try:
        with Image.open(BytesIO(data)) as source:
            source.load()
            picture = source.convert("RGB")
    except OSError, ValueError, Image.DecompressionBombError:
        return None
    picture.thumbnail(MAX_BACKGROUND_PIXELS)
    return picture


def _draw_background(canvas: Canvas, picture: Image.Image) -> None:
    """Cover the page and keep the picture's proportions, like CSS background cover."""
    image = ImageReader(picture)
    width, height = image.getSize()
    scale = max(PAGE_WIDTH / width, PAGE_HEIGHT / height)
    drawn_width, drawn_height = width * scale, height * scale
    canvas.drawImage(
        image,
        (PAGE_WIDTH - drawn_width) / 2,
        (PAGE_HEIGHT - drawn_height) / 2,
        drawn_width,
        drawn_height,
    )


def render_pdf(texts: PrintedTexts, layout: Layout, background: bytes | None) -> bytes:
    """Pure: no database and no files besides the bundled fonts."""
    _register_fonts()
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    canvas.setTitle(f"Certificate {texts.serial}")
    picture = load_background(background) if background is not None else None
    if picture is not None:
        _draw_background(canvas, picture)
    for key in ("name", "activity", "hours", "date", "serial"):
        placement = getattr(layout, key)
        text = getattr(texts, key)
        font = BOLD if key == "name" else REGULAR
        size = fit_size(text, font, placement.size, MAX_TEXT_WIDTH)
        x, y = page_point(placement.x, placement.y)
        canvas.setFont(font, size)
        canvas.setFillColor(NAME_COLOR if key == "name" else TEXT_COLOR)
        # The baseline sits a little below the middle, so the text is centered on y.
        canvas.drawCentredString(x, y - size * 0.35, text)
    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _background_bytes(
    db: Session, root: Path, media_id: uuid.UUID | None
) -> bytes | None:
    """A picture that is gone or not public any more leaves the page plain."""
    if media_id is None:
        return None
    try:
        asset = media_service.load_visible(db, media_id, None)
        return media_service.stored_file(root, asset).read_bytes()
    except HTTPException:
        return None


def certificate_pdf(db: Session, root: Path, serial: str) -> tuple[bytes, str]:
    """The PDF and its file name. Only a valid certificate is printed."""
    verified = service.verify_certificate(db, serial)
    if verified.status != service.ISSUED:
        raise api_error(status.HTTP_409_CONFLICT, "certificate_not_issued")
    template = db.scalar(
        select(CertificateTemplate)
        .join(Certificate, Certificate.template_id == CertificateTemplate.template_id)
        .where(Certificate.serial_no == verified.serial_no)
    )
    texts = PrintedTexts(
        name=verified.full_name,
        activity=verified.activity_title,
        hours=hours_text(verified.hours),
        date=date_text(verified.issued_at),
        serial=verified.serial_no,
    )
    layout = verified.design.layout if verified.design else Layout()
    background = _background_bytes(
        db, root, template.background_media_id if template else None
    )
    data = render_pdf(texts, layout, background)
    return data, f"certificate-{verified.serial_no}.pdf"
