"""Media storage port plus local-disk backend (cloud later via MediaStore).

Layout on disk is always ``<root>/orgs/<org_id>/<media_id><ext>`` so every
org owns exactly one folder. Hard org deletes remove the whole folder plus
a sweep for orphan folders. Swap to S3/GCS later by implementing MediaStore.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID

IMAGE_MIMES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/heic": ".heic",
    "image/heif": ".heif",
}

# Browsers decode these natively; anything else in IMAGE_MIMES gets
# transcoded on upload so galleries render everywhere.
_WEB_SAFE_IMAGES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/avif",
}

VIDEO_MIMES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}

# Generated documents (certificate PDFs) are stored through save_typed but
# never user-uploaded: media_kind() intentionally returns None for them.
DOCUMENT_MIMES = {
    "application/pdf": ".pdf",
}

MEDIA_MIMES = {**IMAGE_MIMES, **VIDEO_MIMES, **DOCUMENT_MIMES}

# Decompression-bomb guard: reject images above this pixel count.
MAX_IMAGE_PIXELS = 25_000_000
# Longest edge after transcode; larger images are downscaled.
MAX_IMAGE_EDGE = 4096

# Allowlisted on-disk suffixes. Anything else is rejected at save time.
ALLOWED_EXTENSIONS = frozenset({".jpg", ".png", ".webp", ".gif", ".avif",
    ".bmp", ".tiff", ".heic", ".heif", ".mp4", ".webm", ".mov", ".pdf"})


def media_kind(mime: str) -> str | None:
    """Classify a mime as image/video, or None when unsupported."""
    clean = mime.split(";")[0].strip().lower()
    if clean in IMAGE_MIMES:
        return "image"
    if clean in VIDEO_MIMES:
        return "video"
    return None


def sniff_mime(content: bytes) -> str | None:
    """Guess the mime from magic bytes. None when unknown."""
    if len(content) < 4:
        return None
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:2] == b"BM":
        return "image/bmp"
    if content[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand in (b"avif", b"avis"):
            return "image/avif"
        if brand in (b"heic", b"heix", b"hevc", b"hevw"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heif"):
            return "image/heif"
        return None
    if content[:4] == b"\x00\x00\x00\x18" or content[4:8] == b"ftyp":
        return None
    return None


def extension_for(mime: str, filename: str) -> str | None:
    """Prefer the mime-mapped extension, fall back to allowlisted suffix."""
    clean = mime.split(";")[0].strip().lower()
    if clean in MEDIA_MIMES:
        return MEDIA_MIMES[clean]
    suffix = Path(filename).suffix.lower()
    if suffix == ".jpeg":
        return ".jpg"
    if suffix in ALLOWED_EXTENSIONS:
        return suffix
    return None


def normalize_image(content: bytes, mime: str) -> tuple[str, bytes]:
    """Transcode non-web-safe images (HEIC, TIFF, BMP...) to jpeg/png bytes.

    Browser-safe formats pass through untouched (keeps GIF animation,
    avoids recompressing jpeg). Pixel bombs raise ValueError so the caller
    rejects the upload. Decode failure returns the input so the upload
    still succeeds and stores the original bytes. Runs in a worker thread
    via asyncio.to_thread at the router layer (stays sync here).
    """
    clean = mime.split(";")[0].strip().lower()
    if clean not in IMAGE_MIMES:
        sniffed = sniff_mime(content)
        if sniffed is not None and sniffed in IMAGE_MIMES:
            clean = sniffed
    if clean in _WEB_SAFE_IMAGES:
        return clean, content
    try:
        from io import BytesIO

        import pillow_heif
        from PIL import Image, ImageFile, ImageOps

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        ImageFile.LOAD_TRUNCATED_IMAGES = False
        pillow_heif.register_heif_opener()
        img = ImageOps.exif_transpose(Image.open(BytesIO(content)))
        width, height = img.size
        if width * height > MAX_IMAGE_PIXELS:
            raise ValueError("Image exceeds the pixel limit.")
        if max(width, height) > MAX_IMAGE_EDGE:
            img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
        has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        out = BytesIO()
        if has_alpha:
            img.save(out, "PNG")
            return "image/png", out.getvalue()
        img.convert("RGB").save(out, "JPEG", quality=90)
        return "image/jpeg", out.getvalue()
    except ValueError:
        raise
    except Exception:
        return clean, content


class MediaStore(ABC):
    """Binary storage port. ScyllaDB keeps metadata, this keeps bytes."""

    @abstractmethod
    def save(self, org_id: UUID, media_id: UUID, filename: str, content: bytes) -> str:
        """Persist bytes, return the relative path (orgs/<org_id>/...)."""

    @abstractmethod
    def save_typed(
        self, org_id: UUID, media_id: UUID, mime: str, filename: str, content: bytes
    ) -> str:
        """Persist bytes with the mime-mapped extension on disk."""

    @abstractmethod
    def resolve(self, relative_path: str) -> Path:
        """Map a stored relative path to an absolute file (guarded)."""

    @abstractmethod
    def delete_file(self, relative_path: str) -> bool:
        """Remove one file. True when something was deleted."""

    @abstractmethod
    def delete_org_dir(self, org_id: UUID) -> bool:
        """Remove the whole org folder. True when something was deleted."""

    @abstractmethod
    def sweep_orphans(self, known_org_ids: set[str]) -> int:
        """Delete org folders with no matching org. Returns removal count."""

    @abstractmethod
    def save_user_media(
        self,
        user_id: UUID,
        media_id: UUID,
        mime: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Persist bytes under users/<user_id>/ (avatars, documents)."""

    @abstractmethod
    def delete_user_dir(self, user_id: UUID) -> bool:
        """Remove the whole user folder. True when something was deleted."""


class LocalMediaStore(MediaStore):
    """Local-disk backend rooted at MEDIA_ROOT (never committed to git)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _org_dir(self, org_id: UUID) -> Path:
        return self._root / "orgs" / str(org_id)

    def _user_dir(self, user_id: UUID) -> Path:
        return self._root / "users" / str(user_id)

    def save(self, org_id: UUID, media_id: UUID, filename: str, content: bytes) -> str:
        """Legacy save keyed by filename suffix; only allowlisted exts."""
        ext = extension_for("application/octet-stream", filename)
        if ext is None:
            raise ValueError("Unsupported file extension.")
        target = self._org_dir(org_id) / f"{media_id}{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"orgs/{org_id}/{target.name}"

    def save_typed(
        self, org_id: UUID, media_id: UUID, mime: str, filename: str, content: bytes
    ) -> str:
        """Save with the mime-mapped extension (jpg for jpeg, etc)."""
        clean = mime.split(";")[0].strip().lower()
        ext = MEDIA_MIMES.get(clean)
        if ext is None:
            raise ValueError("Unsupported media mime.")
        target = self._org_dir(org_id) / f"{media_id}{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"orgs/{org_id}/{target.name}"

    def save_user_media(
        self,
        user_id: UUID,
        media_id: UUID,
        mime: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Save under users/<user_id>/ so orphan sweeps never touch it."""
        clean = mime.split(";")[0].strip().lower()
        ext = MEDIA_MIMES.get(clean)
        if ext is None:
            raise ValueError("Unsupported media mime.")
        target = self._user_dir(user_id) / f"{media_id}{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"users/{user_id}/{target.name}"

    def delete_user_dir(self, user_id: UUID) -> bool:
        import shutil

        target = self._user_dir(user_id)
        if target.is_dir():
            shutil.rmtree(target)
            return True
        return False

    def resolve(self, relative_path: str) -> Path:
        candidate = (self._root / Path(relative_path)).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError("Media path escapes the storage root.")
        return candidate

    def delete_file(self, relative_path: str) -> bool:
        try:
            target = self.resolve(relative_path)
        except ValueError:
            return False
        if target.is_file():
            target.unlink()
            return True
        return False

    def delete_org_dir(self, org_id: UUID) -> bool:
        import shutil

        target = self._org_dir(org_id)
        if target.is_dir():
            shutil.rmtree(target)
            return True
        return False

    def sweep_orphans(self, known_org_ids: set[str]) -> int:
        import shutil

        base = self._root / "orgs"
        if not base.is_dir():
            return 0
        removed = 0
        for child in base.iterdir():
            if child.is_dir() and child.name not in known_org_ids:
                shutil.rmtree(child)
                removed += 1
        return removed
