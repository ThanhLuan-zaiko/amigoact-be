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

MEDIA_MIMES = {**IMAGE_MIMES, **VIDEO_MIMES}


def media_kind(mime: str) -> str | None:
    """Classify a mime as image/video, or None when unsupported."""
    clean = mime.split(";")[0].strip().lower()
    if clean in IMAGE_MIMES:
        return "image"
    if clean in VIDEO_MIMES:
        return "video"
    return None


def extension_for(mime: str, filename: str) -> str | None:
    """Prefer the mime-mapped extension, fall back to the filename suffix."""
    clean = mime.split(";")[0].strip().lower()
    if clean in MEDIA_MIMES:
        return MEDIA_MIMES[clean]
    suffix = Path(filename).suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return ".jpg"
    if suffix in MEDIA_MIMES.values():
        return suffix
    return None


def normalize_image(content: bytes, mime: str) -> tuple[str, bytes]:
    """Transcode non-web-safe images (HEIC, TIFF, BMP...) to jpeg/png bytes.

    Browser-safe formats pass through untouched (keeps GIF animation,
    avoids recompressing jpeg). Decode failure returns the input so the
    upload still succeeds and stores the original bytes."""
    clean = mime.split(";")[0].strip().lower()
    if clean in _WEB_SAFE_IMAGES:
        return clean, content
    try:
        from io import BytesIO

        import pillow_heif
        from PIL import Image, ImageOps

        pillow_heif.register_heif_opener()
        img = ImageOps.exif_transpose(Image.open(BytesIO(content)))
        has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
        out = BytesIO()
        if has_alpha:
            img.save(out, "PNG")
            return "image/png", out.getvalue()
        img.convert("RGB").save(out, "JPEG", quality=90)
        return "image/jpeg", out.getvalue()
    except Exception:
        return clean, content


class MediaStore(ABC):
    """Binary storage port. ScyllaDB keeps metadata, this keeps bytes."""

    @abstractmethod
    def save(self, org_id: UUID, media_id: UUID, filename: str, content: bytes) -> str:
        """Persist bytes, return the relative path (orgs/<org_id>/...)."""

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


class LocalMediaStore(MediaStore):
    """Local-disk backend rooted at MEDIA_ROOT (never committed to git)."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _org_dir(self, org_id: UUID) -> Path:
        return self._root / "orgs" / str(org_id)

    def save(self, org_id: UUID, media_id: UUID, filename: str, content: bytes) -> str:
        ext = extension_for("application/octet-stream", filename)
        target = self._org_dir(org_id) / f"{media_id}{ext or ''}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"orgs/{org_id}/{target.name}"

    def save_typed(
        self, org_id: UUID, media_id: UUID, mime: str, filename: str, content: bytes
    ) -> str:
        """Save with the mime-mapped extension (jpg for jpeg, etc)."""
        ext = extension_for(mime, filename) or Path(filename).suffix.lower()
        target = self._org_dir(org_id) / f"{media_id}{ext}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"orgs/{org_id}/{target.name}"

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
