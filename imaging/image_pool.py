"""Image pool management for panorama stitching (REQ-08).

Handles importing source images into a skyline's `images/` folder (REQ-33)
and listing what's already there. Import is via file-selection dialog only
for now -- Tkinter has no built-in drag-and-drop support without a
third-party dependency (e.g. tkinterdnd2), so the drag-and-drop half of
REQ-08 is deferred rather than guessed at.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

import cv2

ACCEPTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}  # REQ-08: JPEG, PNG, TIFF


class ImagePoolError(Exception):
    """Raised when one or more selected files aren't usable images."""


def list_pool_images(images_folder: Path) -> List[Path]:
    """Images already imported into a skyline's images/ folder, sorted by name."""
    if not images_folder.exists():
        return []
    return sorted(
        p for p in images_folder.iterdir()
        if p.is_file() and p.suffix.lower() in ACCEPTED_EXTENSIONS
    )


def import_images(source_paths: List[Path], images_folder: Path) -> List[Path]:
    """
    Copy the given source image files into the skyline's images/ folder
    (REQ-33). Returns the destination paths in the same order as input.

    Rejects the whole batch up front (REQ-07's no-silent-failure principle,
    applied here the same way it is for the Alt/Az importers) if any file
    either has an unsupported extension (REQ-08: JPEG/PNG/TIFF only) or
    isn't actually a readable image -- an extension check alone would let a
    corrupt file through silently, with the failure only surfacing later at
    stitch time.
    """
    images_folder.mkdir(parents=True, exist_ok=True)

    bad_extension = [p for p in source_paths if p.suffix.lower() not in ACCEPTED_EXTENSIONS]
    if bad_extension:
        names = ", ".join(p.name for p in bad_extension)
        raise ImagePoolError(f"Unsupported image format (JPEG/PNG/TIFF only): {names}")

    unreadable = [p for p in source_paths if cv2.imread(str(p)) is None]
    if unreadable:
        names = ", ".join(p.name for p in unreadable)
        raise ImagePoolError(f"Could not read as an image (corrupt or invalid file): {names}")

    destinations = []
    for src in source_paths:
        dest = images_folder / src.name
        if dest.resolve() != src.resolve():
            shutil.copy2(src, dest)
        destinations.append(dest)
    return destinations


def remove_pool_image(path: Path) -> None:
    if path.exists():
        path.unlink()
