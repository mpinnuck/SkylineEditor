"""Stellarium .hrz importer (REQ-02).

Per landscape.ini's `polygonal_horizon_list` convention: space-delimited
Az/Alt pairs in decimal degrees, no header row.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from fileio.alt_az_importer import AZ_ALT, import_alt_az_file
from fileio.errors import ImportResult
from models.horizon_point import HorizonPoint


def import_hrz_file(path: Path) -> Tuple[List[HorizonPoint], ImportResult, List[str]]:
    return import_alt_az_file(path, delimiter="whitespace", column_order=AZ_ALT, has_header=False)
