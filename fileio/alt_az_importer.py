"""Generic Alt/Az CSV/plain-text importer (REQ-01)."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional, Tuple

from fileio.errors import ImportFileError, ImportResult
from models.horizon_point import HorizonPoint

AZ_ALT = "az_alt"
ALT_AZ = "alt_az"

_DELIMITER_CANDIDATES = [",", "\t"]  # whitespace is handled separately below


def detect_delimiter(sample_line: str) -> str:
    """Best-effort delimiter auto-detection for a data line (REQ-01)."""
    for delim in _DELIMITER_CANDIDATES:
        if delim in sample_line:
            return delim
    return "whitespace"


def _split_line(line: str, delimiter: str) -> List[str]:
    if delimiter == "whitespace":
        return line.split()
    return next(csv.reader([line], delimiter=delimiter))


def _looks_like_header(fields: List[str]) -> bool:
    for value in fields:
        try:
            float(value)
        except ValueError:
            return True
    return False


def import_alt_az_file(
    path: Path,
    delimiter: Optional[str] = None,
    column_order: Optional[str] = None,
    has_header: Optional[bool] = None,
) -> Tuple[List[HorizonPoint], ImportResult, List[str]]:
    """
    Import Alt/Az pairs from a CSV or plain-text file (REQ-01). Any of
    delimiter / column_order / has_header left as None is auto-detected.

    Returns (points, result, preserved_comment_lines): comment lines starting
    with '#' or ';' are captured separately for round-trip preservation
    (REQ-06) rather than treated as data or discarded.

    Malformed rows are skipped with a warning (REQ-15); a file that is
    unreadable or yields zero usable rows raises ImportFileError (REQ-07).
    """
    try:
        raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise ImportFileError(f"Could not read '{path.name}': {exc}") from exc

    result = ImportResult()
    preserved_comments: List[str] = []
    data_lines: List[Tuple[int, str]] = []

    for idx, line in enumerate(raw_lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith(";"):
            preserved_comments.append(line)
            continue
        data_lines.append((idx, line))

    if not data_lines:
        raise ImportFileError(f"'{path.name}' contains no data rows.")

    if delimiter is None:
        delimiter = detect_delimiter(data_lines[0][1])

    first_fields = _split_line(data_lines[0][1], delimiter)

    if has_header is None:
        has_header = _looks_like_header(first_fields)
    if has_header:
        data_lines = data_lines[1:]

    if column_order is None:
        column_order = AZ_ALT  # REQ-01 default when not specified/auto-detectable

    points: List[HorizonPoint] = []
    for row_num, line in data_lines:
        fields = _split_line(line, delimiter)
        if len(fields) < 2:
            result.add_warning(f"Expected 2 values, found {len(fields)} -- skipped.", row_num)
            continue
        try:
            first, second = float(fields[0]), float(fields[1])
        except ValueError:
            result.add_warning(f"Non-numeric value -- skipped: '{line.strip()}'", row_num)
            continue
        if column_order == AZ_ALT:
            az, alt = first, second
        else:
            alt, az = first, second
        points.append(HorizonPoint(az % 360.0, alt))

    if not points:
        raise ImportFileError(
            f"'{path.name}' contained no usable Alt/Az rows "
            f"({len(result.warnings)} row(s) skipped)."
        )

    return points, result, preserved_comments
