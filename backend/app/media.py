"""Local storage for uploaded images.

Images are the only uploads kept on disk — the memory list shows them, and the
original is the thing being remembered. They never leave this machine except
for the one-off vision call that describes them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("merror.media")

IMAGES_SUBDIR = "images"

# Magic bytes, checked because a browser's content type and a file's extension
# are both trivially wrong. A .png that is actually a PDF should not reach the
# vision API labelled as an image.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]


def sniff_media_type(data: bytes) -> str | None:
    """Identify an image from its magic bytes, or None if unrecognised."""
    for signature, media_type in _SIGNATURES:
        if data.startswith(signature):
            return media_type
    # WebP is RIFF-framed: "RIFF" <4-byte size> "WEBP".
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def images_dir() -> Path:
    """The directory holding stored images, created on first use."""
    path = get_settings().uploads_path / IMAGES_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_image(memory_id: str, extension: str, data: bytes) -> Path:
    """Write an image to local storage and return its path.

    The filename is derived from the memory id rather than the upload's own
    name, so a hostile or duplicate filename cannot escape the directory or
    overwrite another memory's image.
    """
    safe_extension = "." + extension.lstrip(".").lower()
    if not safe_extension[1:].isalnum():
        raise ValueError(f"Refusing to store an image with extension {extension!r}")

    destination = images_dir() / f"{memory_id}{safe_extension}"
    destination.write_bytes(data)
    logger.info("Stored image %s (%d bytes)", destination.name, len(data))
    return destination


def delete_image(file_path: str | Path) -> bool:
    """Remove a stored image. True if a file was deleted.

    Refuses to touch anything outside the images directory, so a corrupted or
    tampered-with stored path cannot turn a memory deletion into an arbitrary
    file deletion.
    """
    if not file_path:
        return False

    path = Path(file_path)
    root = images_dir().resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except (ValueError, OSError):
        logger.warning("Refusing to delete %s — outside the images directory", file_path)
        return False

    if not resolved.is_file():
        return False

    resolved.unlink()
    logger.info("Deleted image %s", resolved.name)
    return True
