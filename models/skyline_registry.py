"""SkylineRegistry: manages the set of skylines under a configurable root folder."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

from models.skyline import Skyline

# Characters disallowed cross-platform (Windows is the most restrictive of the
# supported OSes) so that "any operating-system-valid folder name" (REQ-21)
# is enforced consistently regardless of which OS is actually running.
_INVALID_NAME_CHARS = set('<>:"/\\|?*')


class SkylineNameError(Exception):
    """Raised for invalid or duplicate skyline names."""


class SkylineRegistry:
    def __init__(self, root_folder: Path):
        self.root_folder = Path(root_folder)
        self.skylines: List[Skyline] = []

    def set_root_folder(self, new_root: Path) -> None:
        """
        Change the root folder (REQ-19). Existing skyline folders are left in
        their original location -- they are NOT moved. Call discover()
        afterwards to (re)populate the list from the new root.
        """
        self.root_folder = Path(new_root)

    def discover(self) -> None:
        """Populate self.skylines by scanning root_folder for skyline subfolders."""
        self.skylines.clear()
        if not self.root_folder.exists():
            return
        for entry in sorted(self.root_folder.iterdir()):
            if entry.is_dir():
                self.skylines.append(Skyline(name=entry.name, folder=entry))

    def add(self, name: str) -> Skyline:
        self._validate_name(name)
        folder = self.root_folder / name
        if folder.exists():
            raise SkylineNameError(f"A skyline folder named '{name}' already exists.")
        skyline = Skyline(name=name, folder=folder)
        skyline.ensure_folders()
        self.skylines.append(skyline)
        return skyline

    def remove(self, skyline: Skyline, delete_folder: bool = False) -> None:
        self.skylines.remove(skyline)
        if delete_folder and skyline.folder.exists():
            shutil.rmtree(skyline.folder)

    def rename(self, skyline: Skyline, new_name: str) -> None:
        """Renames the existing folder in place (REQ-23) -- not a move/recreate."""
        self._validate_name(new_name)
        new_folder = self.root_folder / new_name
        if new_folder.exists():
            raise SkylineNameError(f"A skyline folder named '{new_name}' already exists.")
        skyline.folder.rename(new_folder)
        skyline.folder = new_folder
        skyline.name = new_name

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name or not name.strip():
            raise SkylineNameError("Skyline name cannot be empty.")
        if any(ch in _INVALID_NAME_CHARS for ch in name):
            raise SkylineNameError(f"'{name}' contains characters not valid in a folder name.")
