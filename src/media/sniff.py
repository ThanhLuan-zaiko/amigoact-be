"""Recognizing an image by its first bytes, never by its name or declared type."""

from dataclasses import dataclass

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SNIFF_BYTES = 16


@dataclass(frozen=True)
class ImageKind:
    mime: str
    extension: str


JPEG = ImageKind("image/jpeg", "jpg")
PNG = ImageKind("image/png", "png")
WEBP = ImageKind("image/webp", "webp")


def detect_image(head: bytes) -> ImageKind | None:
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    return None
