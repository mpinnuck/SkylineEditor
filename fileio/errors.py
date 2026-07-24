"""Import/export error types (REQ-07) and warning collection."""
from __future__ import annotations

from typing import List, Optional

from models.horizon_curve import ValidationWarning


class ImportFileError(Exception):
    """A file could not be imported at all (unreadable, wrong format, corrupt,
    or yielding zero usable rows). This is the user-facing failure path
    required by REQ-07 -- import never fails silently."""


class ImportResult:
    """
    Result of a successful import: any row-level warnings collected along the
    way. REQ-15 decision: malformed rows are skipped with a warning rather
    than aborting the whole import; ImportFileError above is reserved for
    files that cannot be usefully parsed at all.
    """

    def __init__(self) -> None:
        self.warnings: List[ValidationWarning] = []

    def add_warning(self, message: str, row_index: Optional[int] = None) -> None:
        self.warnings.append(ValidationWarning(message, row_index))
