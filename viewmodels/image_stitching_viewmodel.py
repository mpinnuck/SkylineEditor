"""ImageStitchingViewModel: mediates the Image tab's view and the imaging layer.

Image pool management and stitching are always scoped to whichever skyline
is currently selected in MainViewModel -- the same convention MainViewModel
itself uses for horizon-curve edits.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from imaging import arrangement, image_pool, stitcher
from imaging.arrangement import ImageGrid, Position
from models.skyline import Skyline
from viewmodels.main_viewmodel import MainViewModel


class ImageStitchingViewModel:
    def __init__(self, main_viewmodel: MainViewModel):
        self._main = main_viewmodel
        self.last_result: Optional[stitcher.StitchResult] = None
        self.grid: Optional[ImageGrid] = None

    @property
    def current_skyline(self) -> Optional[Skyline]:
        return self._main.current_skyline

    def on_skyline_changed(self) -> None:
        """Call when the selected skyline changes, so stale state from the
        previous skyline isn't attributed to the new one."""
        self.last_result = None
        self.grid = None

    def list_images(self) -> List[Path]:
        return image_pool.list_pool_images(self._require_skyline().images_folder)

    def import_images(self, source_paths: List[Path]) -> List[Path]:
        skyline = self._require_skyline()
        return image_pool.import_images(source_paths, skyline.images_folder)

    def remove_image(self, path: Path) -> None:
        image_pool.remove_pool_image(path)
        self.grid = None  # pool changed -- any existing arrangement is stale

    # -- Grid arrangement (REQ-40, REQ-41) --------------------------------------------

    def build_arrangement(self, row_sizes: List[int]) -> ImageGrid:
        """
        Populate the grid from the disciplined filename-order capture
        sequence (REQ-40) using explicit per-row image counts -- e.g.
        [14, 15, 5] for a base sweep plus two additional altitude rows. The
        user then confirms/corrects this via drag-and-drop (REQ-41) before
        stitching.
        """
        self.grid = arrangement.build_default_arrangement(self.list_images(), row_sizes)
        return self.grid

    def swap_in_grid(self, position_a: Position, position_b: Position) -> None:
        if self.grid is None:
            raise RuntimeError("No arrangement to edit -- call build_arrangement() first.")
        self.grid.swap(position_a, position_b)

    def clear_stitched_output(self) -> bool:
        """Delete the derived stitched image for the current skyline.

        Returns True if a file was deleted, False if no stitched output existed.
        """
        skyline = self._require_skyline()
        stitched = skyline.stitched_image_file
        if stitched.exists():
            stitched.unlink()
            self.last_result = None
            return True
        self.last_result = None
        return False

    def stitch(self, on_progress: Optional[Callable[[str], None]] = None) -> stitcher.StitchResult:
        """
        Stitch the current skyline's full image pool (REQ-11) and persist
        the result to its stitched_image_file. Raises StitchError on
        failure; the caller decides how to present any orphan_paths.

        If given, on_progress is called with a short status string as each
        stitching stage starts (see stitcher.stitch's docstring for what
        it can and can't report).
        """
        skyline = self._require_skyline()
        # Always start from a clean derived output, so each run is fully rebuilt.
        self.clear_stitched_output()
        images = self.list_images()
        result = stitcher.stitch(images, on_progress=on_progress)
        stitcher.save_stitched_image(result, skyline.stitched_image_file)
        self.last_result = result
        return result

    def _require_skyline(self) -> Skyline:
        if self.current_skyline is None:
            raise RuntimeError("No skyline selected.")
        return self.current_skyline
