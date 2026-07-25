"""Grid arrangement of the image pool (REQ-40, REQ-41).

Rather than discovering topology automatically from image content alone,
the app trusts a disciplined capture sequence (REQ-40): filename order
within a row gives azimuthal adjacency, and the user tells the app how many
rows there are and how many images are in each so it can split the
sequence accordingly. The user then visually confirms/corrects the result
(drag-and-drop) before stitching.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

Position = Tuple[int, int]  # (row, column)


class ArrangementError(Exception):
    pass


@dataclass
class ImageGrid:
    """
    A 2D arrangement of image paths: one row per altitude sweep (REQ-08),
    ordered left-to-right within each row (REQ-40). `None` marks an empty
    cell (e.g. a short trailing row, if the last sweep isn't a full row).
    """

    rows: List[List[Optional[Path]]] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def column_count(self) -> int:
        return max((len(row) for row in self.rows), default=0)

    def get(self, position: Position) -> Optional[Path]:
        row, col = position
        return self.rows[row][col]

    def swap(self, position_a: Position, position_b: Position) -> None:
        """Swap two cells -- the basic drag-and-drop correction operation
        (REQ-41). Either or both cells may be empty (None)."""
        ra, ca = position_a
        rb, cb = position_b
        self.rows[ra][ca], self.rows[rb][cb] = self.rows[rb][cb], self.rows[ra][ca]

    def row_images(self, row_index: int) -> List[Path]:
        """A row's images in order, with empty cells skipped."""
        return [p for p in self.rows[row_index] if p is not None]

    def all_images(self) -> List[Path]:
        return [p for row in self.rows for p in row if p is not None]

    def find(self, image_path: Path) -> Optional[Position]:
        for r, row in enumerate(self.rows):
            for c, p in enumerate(row):
                if p == image_path:
                    return (r, c)
        return None


def build_default_arrangement(image_paths: List[Path], row_sizes: List[int]) -> ImageGrid:
    """
    Split filename/capture-ordered images into rows (REQ-40, REQ-41) using
    explicit per-row image counts -- e.g. [14, 15, 5] for a base sweep plus
    two additional altitude rows, which need not match the base row's width
    or each other's (a higher sweep has no reason to use the same number of
    shots as the base). Rows are assigned in order: the first `row_sizes[0]`
    images form row 0 (the base, 0-degree sweep), the next `row_sizes[1]`
    form row 1, and so on. The row sizes must account for every image in
    the pool exactly -- a mismatch is reported rather than silently
    truncated or padded with the wrong images.
    """
    if not row_sizes:
        raise ArrangementError("At least one row size is required.")
    if any(size < 1 for size in row_sizes):
        raise ArrangementError("Each row must have at least 1 image.")
    if not image_paths:
        raise ArrangementError("No images to arrange.")

    ordered = sorted(image_paths, key=lambda p: p.name)
    total_expected = sum(row_sizes)
    if total_expected != len(ordered):
        raise ArrangementError(
            f"Row sizes add up to {total_expected}, but {len(ordered)} image(s) "
            f"are in the pool -- check the counts and try again."
        )

    rows: List[List[Optional[Path]]] = []
    index = 0
    for size in row_sizes:
        rows.append(list(ordered[index : index + size]))
        index += size

    width = max(len(row) for row in rows)
    for row in rows:
        while len(row) < width:
            row.append(None)

    return ImageGrid(rows=rows)
