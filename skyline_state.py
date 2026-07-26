"""Per-skyline persisted state helpers.

This mirrors the config module pattern with explicit load/save functions so
state handling stays centralized and easy to evolve.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SkylineState:
    last_import_file: str = ""
    # One row per altitude sweep (REQ-40), each cell an image filename
    # (relative to the skyline's images/ folder) or None for an empty cell
    # (REQ-41) -- filenames rather than full paths so this stays valid
    # across root-folder changes and skyline renames.
    image_grid_rows: List[List[Optional[str]]] = field(default_factory=list)
    # Manual per-row stitch position nudge, applied on top of the
    # automatic sky/tree boundary placement -- {row_index_as_str: [dx, dy]}.
    # JSON object keys are always strings, hence the str row index rather
    # than int; converted back to int where this is actually used.
    row_offsets: Dict[str, List[int]] = field(default_factory=dict)
    # Persisted Adjust-tab row composites and placement metadata so the
    # adjustment view can be restored on project resume without re-stitching.
    # Each item is:
    # {
    #   "row_index": int,
    #   "image_count": int,
    #   "grid_column_span": [start_col, end_col],
    #   "placed_x": int,
    #   "placed_y": int,
    #   "cache_file": str
    # }
    adjust_row_cache: List[dict] = field(default_factory=list)


def load_skyline_state(path: Path) -> SkylineState:
    """Load skyline-local state from path, returning defaults on failure."""
    if not path.exists():
        return SkylineState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return SkylineState()
    if not isinstance(data, dict):
        return SkylineState()

    known_fields = set(SkylineState.__dataclass_fields__.keys())
    filtered = {k: v for k, v in data.items() if k in known_fields}
    try:
        return SkylineState(**filtered)
    except TypeError:
        return SkylineState()


def save_skyline_state(state: SkylineState, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
