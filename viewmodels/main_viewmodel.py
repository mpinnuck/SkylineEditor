"""MainViewModel: mediates between the views and the model layer.

Owns the SkylineRegistry, the currently-selected Skyline, and the undo
stack; wraps all import/export/edit operations so views never touch models
or fileio directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from commands.undo_stack import Command, UndoStack
from config import AppConfig
from fileio import alt_az_importer, horizon_exporter, hrz_importer, theodolite_importer
from fileio.alt_az_importer import AZ_ALT
from fileio.errors import ImportFileError
from fileio.errors import ImportResult
from models.horizon_curve import HorizonCurve, HorizonValidationError
from models.horizon_point import HorizonPoint
from models.skyline import Skyline
from models.skyline_registry import SkylineRegistry
from skyline_state import load_skyline_state, save_skyline_state


class MainViewModel:
    def __init__(self, config: AppConfig):
        self.config = config
        self.registry = SkylineRegistry(Path(config.root_folder))
        self.registry.discover()
        self.current_skyline: Optional[Skyline] = None
        self.undo_stack = UndoStack()

    # -- Skyline list operations (REQ-18, 19, 22, 23) -----------------------------------

    def add_skyline(self, name: str) -> Skyline:
        return self.registry.add(name)

    def remove_skyline(self, skyline: Skyline, delete_folder: bool = False) -> None:
        self.registry.remove(skyline, delete_folder=delete_folder)
        if self.current_skyline is skyline:
            self.current_skyline = None

    def rename_skyline(self, skyline: Skyline, new_name: str) -> None:
        self.registry.rename(skyline, new_name)

    def select_skyline(self, skyline: Skyline) -> None:
        self.current_skyline = skyline
        self.undo_stack.clear()

    def load_selected_skyline_state(self) -> Optional[str]:
        """Restore the selected skyline's plot from horizon.csv only."""
        return self.load_current_skyline_plot_data(force=True)

    def save_selected_skyline_state(self, last_import_file: Optional[Path] = None) -> None:
        skyline = self._require_skyline()
        state_path = self._state_file(skyline)
        state = load_skyline_state(state_path)
        if last_import_file is not None:
            state.last_import_file = str(last_import_file)
        save_skyline_state(state, state_path)

    def load_current_skyline_plot_data(self, force: bool = False) -> Optional[str]:
        """Load persisted plot data (horizon.csv) for the selected skyline.

        Returns an error message when loading fails; otherwise None.
        """
        skyline = self._require_skyline()
        if skyline.dirty and not force:
            return None
        if skyline.curve.points and not force:
            return None
        if not skyline.horizon_file.exists():
            return None
        try:
            points, _result, comments = alt_az_importer.import_alt_az_file(
                skyline.horizon_file,
                delimiter=",",
                column_order=AZ_ALT,
                has_header=True,
            )
            self._apply_imported_points(points, comments, mark_dirty=False)
            return None
        except (ImportFileError, HorizonValidationError) as exc:
            return f"Could not load saved plot data for '{skyline.name}': {exc}"

    @staticmethod
    def _state_file(skyline: Skyline) -> Path:
        return skyline.folder / "state.json"

    def set_root_folder(self, new_root: Path) -> None:
        self.registry.set_root_folder(new_root)
        self.registry.discover()
        self.config.root_folder = str(new_root)
        self.current_skyline = None
        self.undo_stack.clear()

    # -- Point editing (REQ-25, 26, 27) --------------------------------------------------

    def add_point(self, azimuth_deg: float, altitude_deg: float) -> None:
        curve = self._require_curve()
        state = {}

        def do():
            state["point"] = curve.add_point(azimuth_deg, altitude_deg)

        def undo():
            curve.remove_point_object(state["point"])

        self.undo_stack.do(Command(do, undo, "Add point"))
        self.current_skyline.mark_dirty()

    def delete_point(self, index: int) -> None:
        """Index-based delete, for the table view where the index is fresh
        at click time."""
        curve = self._require_curve()
        self.delete_point_object(curve.points[index])

    def delete_point_object(self, point: HorizonPoint) -> None:
        """Identity-based delete, for the plot view (right-click)."""
        curve = self._require_curve()
        state = {}

        def do():
            state["index"] = curve.remove_point_object(point)

        def undo():
            curve.insert_point_object(state["index"], point)

        self.undo_stack.do(Command(do, undo, "Delete point"))
        self.current_skyline.mark_dirty()

    def move_point(self, index: int, new_azimuth_deg: float, new_altitude_deg: float) -> None:
        """Index-based move, for the table view's edit-in-place."""
        curve = self._require_curve()
        point = curve.points[index]
        old_az, old_alt = point.azimuth_deg, point.altitude_deg
        new_az = new_azimuth_deg % 360.0

        def do():
            curve.set_point_values(point, new_az, new_altitude_deg)

        def undo():
            curve.set_point_values(point, old_az, old_alt)

        self.undo_stack.do(Command(do, undo, "Move point"))
        self.current_skyline.mark_dirty()

    def preview_move_point(self, point: HorizonPoint, azimuth_deg: float, altitude_deg: float) -> None:
        """Live drag feedback for the plot view -- direct mutation, NOT
        undo-tracked. Call commit_drag() on mouse release to register a
        single undo entry for the whole drag (REQ-26/REQ-27)."""
        curve = self._require_curve()
        curve.set_point_values(point, azimuth_deg, altitude_deg)

    def commit_drag(self, point: HorizonPoint, from_azimuth_deg: float, from_altitude_deg: float) -> None:
        curve = self._require_curve()
        to_az, to_alt = point.azimuth_deg, point.altitude_deg

        def do():
            curve.set_point_values(point, to_az, to_alt)

        def undo():
            curve.set_point_values(point, from_azimuth_deg, from_altitude_deg)

        self.undo_stack.do(Command(do, undo, "Move point"))
        self.current_skyline.mark_dirty()

    def undo(self) -> bool:
        return self.undo_stack.undo()

    def redo(self) -> bool:
        return self.undo_stack.redo()

    # -- Import (REQ-01, 02, 07, 15, 36) ----------------------------------------------------

    def import_alt_az(self, path: Path, **kwargs) -> ImportResult:
        points, result, comments = alt_az_importer.import_alt_az_file(path, **kwargs)
        self._apply_imported_points(points, comments)
        return result

    def import_hrz(self, path: Path) -> ImportResult:
        points, result, comments = hrz_importer.import_hrz_file(path)
        self._apply_imported_points(points, comments)
        return result

    def list_theodolite_sessions(self, path: Path) -> List[str]:
        return theodolite_importer.list_sessions(path)

    def import_theodolite(self, path: Path, session: str) -> ImportResult:
        """REQ-36: Theodolite-only workflow -- import a session directly as
        the working horizon curve, independent of the imaging pipeline."""
        points, result = theodolite_importer.import_theodolite_session(path, session)
        self._apply_imported_points(points, [])
        return result

    def _apply_imported_points(
        self,
        points: List[HorizonPoint],
        preserved_comments: List[str],
        mark_dirty: bool = True,
    ) -> None:
        curve = self._require_curve()
        curve.points = points
        curve.preserved_comments = preserved_comments
        curve.validate()
        self.undo_stack.clear()
        if mark_dirty:
            self.current_skyline.mark_dirty()
        else:
            self.current_skyline.mark_clean()

    # -- Export / Save (REQ-03, 04, 05, 06) --------------------------------------------------

    def save(self) -> None:
        """Save to the skyline's own horizon.csv (REQ-05)."""
        skyline = self._require_skyline()
        horizon_exporter.export_csv(skyline.horizon_file, skyline.curve)
        skyline.mark_clean()

    def save_as(self, path: Path) -> None:
        skyline = self._require_skyline()
        suffix = path.suffix.lower()
        if suffix == ".hrz":
            horizon_exporter.export_hrz(path, skyline.curve)
        elif suffix == ".txt":
            horizon_exporter.export_txt(path, skyline.curve)
        else:
            horizon_exporter.export_csv(path, skyline.curve)
        skyline.mark_clean()

    def export_hrz(self, path: Path) -> None:
        """REQ-04: standalone 36-point .hrz export, independent of Save/Save As."""
        horizon_exporter.export_hrz(path, self._require_curve())

    # -- Internal helpers --------------------------------------------------------------------

    def _require_skyline(self) -> Skyline:
        if self.current_skyline is None:
            raise RuntimeError("No skyline selected.")
        return self.current_skyline

    def _require_curve(self) -> HorizonCurve:
        return self._require_skyline().curve
