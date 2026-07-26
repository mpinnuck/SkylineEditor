"""ImageStitchingViewModel: mediates the Image tab's view and the imaging layer.

Image pool management and stitching are always scoped to whichever skyline
is currently selected in MainViewModel -- the same convention MainViewModel
itself uses for horizon-curve edits.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from imaging import arrangement, image_pool, stitcher
from imaging.arrangement import ImageGrid, Position
from models.skyline import Skyline
from skyline_state import load_skyline_state, save_skyline_state
from viewmodels.main_viewmodel import MainViewModel


class ImageStitchingViewModel:
    def __init__(self, main_viewmodel: MainViewModel):
        self._main = main_viewmodel
        self.last_result: Optional[stitcher.StitchResult] = None
        self.grid: Optional[ImageGrid] = None
        self.row_offsets: Dict[int, Tuple[int, int]] = {}

    @property
    def current_skyline(self) -> Optional[Skyline]:
        return self._main.current_skyline

    def on_skyline_changed(self) -> None:
        """Call when the selected skyline changes -- drops stale state from
        the previous skyline and restores the new one's persisted grid
        arrangement (REQ-40, REQ-41) and row offsets, if it has any."""
        self.grid = self._load_grid()
        self.row_offsets = self._load_row_offsets()
        self.last_result = self._load_adjust_cache_result()

    def list_images(self) -> List[Path]:
        return image_pool.list_pool_images(self._require_skyline().images_folder)

    def import_images(self, source_paths: List[Path]) -> List[Path]:
        skyline = self._require_skyline()
        return image_pool.import_images(source_paths, skyline.images_folder)

    def remove_image(self, path: Path) -> None:
        image_pool.remove_pool_image(path)
        self.grid = None  # pool changed -- any existing arrangement is stale
        self._save_grid()

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
        self._save_grid()
        return self.grid

    def swap_in_grid(self, position_a: Position, position_b: Position) -> None:
        if self.grid is None:
            raise RuntimeError("No arrangement to edit -- call build_arrangement() first.")
        self.grid.swap(position_a, position_b)
        self._save_grid()

    def _load_grid(self) -> Optional[ImageGrid]:
        skyline = self.current_skyline
        if skyline is None:
            return None
        state = load_skyline_state(skyline.state_file)
        if not state.image_grid_rows:
            return None
        return arrangement.grid_from_state_rows(state.image_grid_rows, skyline.images_folder)

    def _save_grid(self) -> None:
        skyline = self.current_skyline
        if skyline is None:
            return
        state = load_skyline_state(skyline.state_file)
        state.image_grid_rows = arrangement.grid_to_state_rows(self.grid) if self.grid is not None else []
        save_skyline_state(state, skyline.state_file)

    # -- Manual row position overrides -----------------------------------------------

    def set_row_offset(self, row_index: int, dx: int, dy: int) -> None:
        """
        Manually nudge a row's stitched position by (dx, dy), on top of
        the automatic sky/tree boundary placement (see stitcher.py) --
        the automatic pass is a good default but isn't always right, so
        this is the user's override for the row(s) that need it.
        """
        self.row_offsets[row_index] = (dx, dy)
        self._save_row_offsets()

    def get_row_offset(self, row_index: int) -> Tuple[int, int]:
        return self.row_offsets.get(row_index, (0, 0))

    def reset_row_offset(self, row_index: int) -> None:
        if row_index in self.row_offsets:
            del self.row_offsets[row_index]
            self._save_row_offsets()

    def _load_row_offsets(self) -> Dict[int, Tuple[int, int]]:
        skyline = self.current_skyline
        if skyline is None:
            return {}
        state = load_skyline_state(skyline.state_file)
        return {int(idx): (dx, dy) for idx, (dx, dy) in state.row_offsets.items()}

    def _save_row_offsets(self) -> None:
        skyline = self.current_skyline
        if skyline is None:
            return
        state = load_skyline_state(skyline.state_file)
        state.row_offsets = {str(idx): [dx, dy] for idx, (dx, dy) in self.row_offsets.items()}
        save_skyline_state(state, skyline.state_file)

    def clear_stitched_output(self) -> bool:
        """Delete the derived stitched image for the current skyline.

        Returns True if a file was deleted, False if no stitched output existed.
        """
        skyline = self._require_skyline()
        stitched = skyline.stitched_image_file
        self._clear_adjust_cache()
        if stitched.exists():
            stitched.unlink()
            self.last_result = None
            return True
        self.last_result = None
        return False

    def stitch(self, on_progress: Optional[Callable[[str], None]] = None) -> stitcher.StitchResult:
        """
        Stitch the current skyline's confirmed grid arrangement (REQ-40,
        REQ-41) and persist the result to its stitched_image_file. Raises
        StitchError if there's no confirmed arrangement yet, or if any
        known-adjacent pair can't be aligned (which means the arrangement
        doesn't match reality for that pair -- wrong grid position,
        corrupt file, or genuinely non-overlapping images -- not something
        to silently work around).

        Any manual row offsets (set_row_offset) are applied on top of the
        automatic placement.

        If given, on_progress is called with a short status string as each
        stitching stage starts.
        """
        skyline = self._require_skyline()
        if self.grid is None:
            raise RuntimeError(
                "No confirmed arrangement -- arrange the images (Arrange tab) before stitching."
            )
        # Always start from a clean derived output, so each run is fully rebuilt.
        self.clear_stitched_output()
        result = stitcher.stitch_grid(self.grid, on_progress=on_progress, row_offsets=self.row_offsets)
        stitcher.save_stitched_image(result, skyline.stitched_image_file)
        self._save_adjust_cache(result)
        self.last_result = result
        return result

    # -- Persisted Adjust-tab cache -----------------------------------------------------

    def _adjust_cache_folder(self) -> Path:
        return self._require_skyline().data_folder / "adjust_cache"

    def _clear_adjust_cache(self) -> None:
        skyline = self._require_skyline()
        cache_dir = self._adjust_cache_folder()
        if cache_dir.exists():
            shutil.rmtree(cache_dir, ignore_errors=True)
        state = load_skyline_state(skyline.state_file)
        state.adjust_row_cache = []
        save_skyline_state(state, skyline.state_file)

    def _save_adjust_cache(self, result: stitcher.StitchResult) -> None:
        skyline = self._require_skyline()
        cache_dir = self._adjust_cache_folder()
        cache_dir.mkdir(parents=True, exist_ok=True)

        rows_state: List[dict] = []
        for row in result.row_results:
            filename = f"row_{row.row_index}.png"
            row_path = cache_dir / filename
            cv2.imwrite(str(row_path), row.image)
            rows_state.append(
                {
                    "row_index": int(row.row_index),
                    "image_count": int(row.image_count),
                    "grid_column_span": [int(row.grid_column_span[0]), int(row.grid_column_span[1])],
                    "placed_x": int(row.placed_x),
                    "placed_y": int(row.placed_y),
                    "cache_file": filename,
                }
            )

        state = load_skyline_state(skyline.state_file)
        state.adjust_row_cache = rows_state
        save_skyline_state(state, skyline.state_file)

    def _load_adjust_cache_result(self) -> Optional[stitcher.StitchResult]:
        skyline = self.current_skyline
        if skyline is None:
            return None

        state = load_skyline_state(skyline.state_file)
        rows_state = state.adjust_row_cache
        if not isinstance(rows_state, list) or not rows_state:
            return None

        if not skyline.stitched_image_file.exists():
            return None
        composite = cv2.imread(str(skyline.stitched_image_file), cv2.IMREAD_UNCHANGED)
        if composite is None:
            return None

        cache_dir = skyline.data_folder / "adjust_cache"
        row_results: List[stitcher.RowStitchResult] = []
        try:
            for row_state in rows_state:
                if not isinstance(row_state, dict):
                    return None
                filename = row_state.get("cache_file")
                if not isinstance(filename, str) or not filename:
                    return None
                row_image = cv2.imread(str(cache_dir / filename), cv2.IMREAD_UNCHANGED)
                if row_image is None:
                    return None
                if row_image.ndim != 3 or row_image.shape[2] not in (3, 4):
                    return None

                span = row_state.get("grid_column_span")
                if not isinstance(span, list) or len(span) != 2:
                    return None

                row_results.append(
                    stitcher.RowStitchResult(
                        image=row_image,
                        row_index=int(row_state.get("row_index", 0)),
                        image_count=int(row_state.get("image_count", 0)),
                        grid_column_span=(int(span[0]), int(span[1])),
                        placed_x=int(row_state.get("placed_x", 0)),
                        placed_y=int(row_state.get("placed_y", 0)),
                    )
                )
        except (TypeError, ValueError):
            return None

        # Keep deterministic row order for rendering and interactions.
        row_results.sort(key=lambda row: row.row_index)
        if composite.ndim == 2:
            composite = cv2.cvtColor(composite, cv2.COLOR_GRAY2BGRA)
        elif composite.ndim == 3 and composite.shape[2] == 3:
            composite = cv2.cvtColor(composite, cv2.COLOR_BGR2BGRA)
        elif composite.ndim != 3 or composite.shape[2] != 4:
            return None

        return stitcher.StitchResult(image=np.ascontiguousarray(composite), row_results=row_results)

    def _require_skyline(self) -> Skyline:
        if self.current_skyline is None:
            raise RuntimeError("No skyline selected.")
        return self.current_skyline
