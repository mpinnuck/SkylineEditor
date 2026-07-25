"""Skyline: one named horizon profile plus its on-disk folder structure."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from models.horizon_curve import HorizonCurve

IMAGES_SUBFOLDER = "images"   # REQ-33
DATA_SUBFOLDER = "data"       # REQ-35
HORIZON_FILENAME = "horizon.csv"
STITCHED_IMAGE_FILENAME = "stitched_skyline.png"  # REQ-11 output -- a derived artifact,
                                                   # not a raw source image, so it sits
                                                   # at the skyline's own folder root
                                                   # alongside horizon.csv rather than in images/


@dataclass
class Skyline:
    name: str
    folder: Path
    curve: HorizonCurve = field(default_factory=HorizonCurve)
    dirty: bool = False  # unsaved-changes indicator (REQ-05)

    @property
    def images_folder(self) -> Path:
        return self.folder / IMAGES_SUBFOLDER

    @property
    def data_folder(self) -> Path:
        return self.folder / DATA_SUBFOLDER

    @property
    def horizon_file(self) -> Path:
        return self.folder / HORIZON_FILENAME

    @property
    def stitched_image_file(self) -> Path:
        return self.folder / STITCHED_IMAGE_FILENAME

    def ensure_folders(self) -> None:
        """Create the skyline's folder and its images/ and data/ subfolders
        (REQ-20, REQ-33, REQ-35)."""
        self.images_folder.mkdir(parents=True, exist_ok=True)
        self.data_folder.mkdir(parents=True, exist_ok=True)

    def mark_dirty(self) -> None:
        self.dirty = True

    def mark_clean(self) -> None:
        self.dirty = False
