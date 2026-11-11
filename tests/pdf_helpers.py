"""Small real pictures for the certificate PDF tests. The media helpers only fake headers."""

from io import BytesIO

from PIL import Image


def picture_bytes(fmt: str = "PNG", size: tuple[int, int] = (40, 30)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, (200, 220, 240)).save(buffer, format=fmt)
    return buffer.getvalue()
