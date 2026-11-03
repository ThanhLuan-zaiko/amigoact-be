"""Recognizing a file by its first bytes, never by its name or declared type."""

from dataclasses import dataclass

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
SNIFF_BYTES = 16


@dataclass(frozen=True)
class ImageKind:
    mime: str
    extension: str


JPEG = ImageKind("image/jpeg", "jpg")
PNG = ImageKind("image/png", "png")
WEBP = ImageKind("image/webp", "webp")
MP4 = ImageKind("video/mp4", "mp4")
WEBM = ImageKind("video/webm", "webm")


def detect_image(head: bytes) -> ImageKind | None:
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    return None


def detect_video(head: bytes) -> ImageKind | None:
    if head[4:8] == b"ftyp":
        return MP4
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return WEBM
    return None


def is_video(mime: str | None) -> bool:
    return mime is not None and mime.startswith("video/")
