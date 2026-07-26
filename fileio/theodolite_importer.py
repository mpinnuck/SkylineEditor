"""Theodolite (iPhone app) log importer.

Column mapping and session/date selection per REQ-31, used directly by
REQ-36's Theodolite-only workflow (import straight to the working horizon
curve, independent of the image-stitching pipeline).

Confirmed against real exports from the app (2026-07-24 deck capture):
  - Two file formats seen: comma-delimited `.csv` and space-delimited `.txt`,
    with identical columns and header. Both are supported here via delimiter
    auto-detection.
  - The `POS_STRING` column's value is double-quote-wrapped and contains an
    embedded " / " -- e.g. `"-033.713361d / +151.090082d"`. This is exactly
    what a quote-aware csv.DictReader with delimiter=" " already handles
    correctly (Python's csv module respects quotechar regardless of
    delimiter), so no space-vs-quoted-field special-casing was needed.
  - DATE_TIME's real format is `YYYY.MM.DD_HH.MM.SS` (dot-separated date,
    underscore, dot-separated time), e.g. `2026.07.24_10.04.48` -- there is
    no space in it at all. An earlier version of this importer assumed a
    space-separated "date time" string and used everything before the first
    space as the session key; against the real format that returned the
    entire timestamp unchanged, so every row was (wrongly) treated as its
    own session. Fixed below to split on the underscore instead.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional, Tuple

from fileio.errors import ImportFileError, ImportResult
from models.horizon_point import HorizonPoint

HEADING_COLUMN = "HDG_DEG"
VERTICAL_COLUMN = "VERT"    # angle -- NOT the 'ALT' column (GPS elevation in metres)
SESSION_COLUMN = "DATE_TIME"

_REQUIRED_COLUMNS = (HEADING_COLUMN, VERTICAL_COLUMN, SESSION_COLUMN)


def _detect_delimiter(path: Path) -> str:
    """Theodolite exports come as either comma-delimited .csv or
    space-delimited .txt with identical columns -- detect from the header
    line rather than trusting the file extension."""
    with path.open(encoding="utf-8-sig") as handle:
        header = handle.readline()
    return "," if "," in header else " "


def _open_reader(path: Path) -> csv.DictReader:
    delimiter = _detect_delimiter(path)
    handle = path.open(newline="", encoding="utf-8-sig")
    return csv.DictReader(handle, delimiter=delimiter), handle


def _session_key(date_time_value: str) -> str:
    """
    Reduce a per-row DATE_TIME value to a per-session key.

    DATE_TIME is a per-sample timestamp (distinct on almost every row within
    a single sweep), not a session ID -- grouping on the full value would
    treat every row as its own "session". The app's real format is
    'YYYY.MM.DD_HH.MM.SS' (see module docstring); the date portion before the
    underscore is the session/date key REQ-31 asks for. Falls back to
    splitting on the first space if no underscore is present, in case of a
    differently-formatted export.
    """
    value = date_time_value.strip()
    if "_" in value:
        return value.split("_", 1)[0]
    return value.split(" ", 1)[0]


def list_sessions(path: Path) -> List[str]:
    """
    Return the distinct session/date identifiers present in a Theodolite
    export, in file order, so the caller can present a session picker
    (REQ-31) -- a single log file may concatenate multiple capture sessions.
    """
    sessions: List[str] = []
    seen = set()
    reader, handle = _open_reader(path)
    try:
        _require_columns(reader.fieldnames, path)
        for row in reader:
            raw = (row.get(SESSION_COLUMN) or "").strip()
            if not raw:
                continue
            session = _session_key(raw)
            if session not in seen:
                seen.add(session)
                sessions.append(session)
    finally:
        handle.close()
    if not sessions:
        raise ImportFileError(f"'{path.name}' has no '{SESSION_COLUMN}' values to select a session from.")
    return sessions


def import_theodolite_session(path: Path, session: str) -> Tuple[List[HorizonPoint], ImportResult]:
    """
    Import a single session's rows as Alt/Az points: azimuth = HDG_DEG,
    altitude = VERT (REQ-31). Rows outside the requested session are skipped
    silently -- they belong to a different capture, not a malformed row.
    """
    result = ImportResult()
    points: List[HorizonPoint] = []
    reader, handle = _open_reader(path)
    try:
        _require_columns(reader.fieldnames, path)
        for row_num, row in enumerate(reader, start=2):  # header occupies row 1
            raw = (row.get(SESSION_COLUMN) or "").strip()
            if not raw or _session_key(raw) != session:
                continue
            try:
                azimuth = float(row[HEADING_COLUMN])
                altitude = float(row[VERTICAL_COLUMN])
            except (KeyError, ValueError, TypeError):
                result.add_warning(
                    f"Unreadable {HEADING_COLUMN}/{VERTICAL_COLUMN} value -- skipped.", row_num
                )
                continue
            points.append(HorizonPoint(azimuth % 360.0, altitude))
    finally:
        handle.close()

    if not points:
        raise ImportFileError(f"No usable rows found for session '{session}' in '{path.name}'.")
    return points, result


def _require_columns(fieldnames: Optional[List[str]], path: Path) -> None:
    if not fieldnames:
        raise ImportFileError(f"'{path.name}' has no header row -- cannot map Theodolite columns.")
    missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
    if missing:
        raise ImportFileError(
            f"'{path.name}' is missing expected Theodolite column(s): {', '.join(missing)}."
        )


def is_theodolite_export(path: Path) -> bool:
    """Best-effort header check used by the UI to route files to the
    Theodolite session workflow when users select the wrong import action."""
    try:
        reader, handle = _open_reader(path)
    except OSError:
        return False
    try:
        fieldnames = reader.fieldnames or []
        return all(column in fieldnames for column in _REQUIRED_COLUMNS)
    finally:
        handle.close()
