"""HorizonCurve: the editable Alt/Az horizon dataset.

Covers REQ-14 (validation), REQ-16 (ordering/loop closure), and REQ-17
(interpolation for downstream consumers such as the .hrz exporter).

All angles are decimal degrees throughout -- no DMS support anywhere in the
app (REQ-14).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from models.horizon_point import HorizonPoint

ALTITUDE_MIN_DEG = -90.0
ALTITUDE_MAX_DEG = 90.0
MIN_POINT_COUNT = 3


class ValidationWarning:
    """A single non-fatal issue found while validating or importing a curve."""

    def __init__(self, message: str, row_index: Optional[int] = None):
        self.message = message
        self.row_index = row_index

    def __str__(self) -> str:
        if self.row_index is not None:
            return f"Row {self.row_index}: {self.message}"
        return self.message


class HorizonValidationError(Exception):
    """Raised when a curve fails a hard validation rule (not recoverable by a warning)."""


@dataclass
class HorizonCurve:
    """
    An Alt/Az horizon profile.

    Design decisions for REQ-14/REQ-15 (documented here since the requirements
    doc left them open):
      - Duplicate azimuth values: first occurrence wins, later ones are
        dropped during validate() and reported as a ValidationWarning rather
        than silently overwriting -- this keeps the curve a well-defined
        function of azimuth for REQ-17's interpolation.
      - Malformed import rows: skip-with-warning, not whole-file rejection
        (see fileio/errors.py and the importers) -- a file that is unreadable
        or yields zero usable rows still raises, so failure is never silent
        (REQ-07).
    """

    points: List[HorizonPoint] = field(default_factory=list)
    preserved_comments: List[str] = field(default_factory=list)  # REQ-06

    # -- Editing -------------------------------------------------------------------

    def add_point(self, azimuth_deg: float, altitude_deg: float) -> HorizonPoint:
        point = HorizonPoint(azimuth_deg % 360.0, altitude_deg)
        self.points.append(point)
        self.sort()
        return point

    def remove_point_object(self, point: HorizonPoint) -> int:
        """Remove a point by identity. Returns its index just before removal,
        so a caller (e.g. the undo stack) can re-insert it at the same spot."""
        index = self.points.index(point)
        del self.points[index]
        return index

    def insert_point_object(self, index: int, point: HorizonPoint) -> None:
        self.points.insert(min(index, len(self.points)), point)

    def set_point_values(self, point: HorizonPoint, azimuth_deg: float, altitude_deg: float) -> None:
        point.azimuth_deg = azimuth_deg % 360.0
        point.altitude_deg = altitude_deg
        self.sort()

    def sort(self) -> None:
        """Sort points by azimuth (REQ-16)."""
        self.points.sort(key=lambda p: p.normalized_azimuth())

    # -- Validation ------------------------------------------------------------------

    def validate(self, min_point_count: int = MIN_POINT_COUNT) -> List[ValidationWarning]:
        """
        Normalize and validate the curve in place. Returns non-fatal warnings
        (e.g. dropped duplicate azimuths). Raises HorizonValidationError for
        conditions that make the curve unusable (too few points, altitude out
        of bounds).
        """
        warnings: List[ValidationWarning] = []

        for p in self.points:
            p.azimuth_deg = p.normalized_azimuth()
            if not (ALTITUDE_MIN_DEG <= p.altitude_deg <= ALTITUDE_MAX_DEG):
                raise HorizonValidationError(
                    f"Altitude {p.altitude_deg}\u00b0 at azimuth {p.azimuth_deg}\u00b0 is "
                    f"outside the valid range [{ALTITUDE_MIN_DEG}, {ALTITUDE_MAX_DEG}]."
                )

        self.sort()

        deduped: List[HorizonPoint] = []
        seen_azimuths = set()
        for p in self.points:
            key = round(p.azimuth_deg, 6)
            if key in seen_azimuths:
                warnings.append(ValidationWarning(
                    f"Duplicate azimuth {p.azimuth_deg}\u00b0 -- kept the first "
                    f"occurrence, dropped this one."
                ))
                continue
            seen_azimuths.add(key)
            deduped.append(p)
        self.points = deduped

        if len(self.points) < min_point_count:
            raise HorizonValidationError(
                f"Horizon curve has {len(self.points)} point(s); at least "
                f"{min_point_count} are required."
            )

        return warnings

    # -- Interpolation / resampling (REQ-17) --------------------------------------------

    def interpolate(self, azimuth_deg: float) -> float:
        """
        Altitude at an arbitrary azimuth: piecewise-linear interpolation
        between the two nearest defined points, wrapping circularly so the
        loop closes at 360deg/0deg (REQ-16). This is the interpolation method
        REQ-17 asks be defined for any downstream consumer of the curve (the
        .hrz exporter's 36-point resample below, and eventually the horizon
        scanner/deviation-metric work in the imaging pipeline).
        """
        if len(self.points) < 2:
            raise HorizonValidationError("Need at least 2 points to interpolate.")

        az = azimuth_deg % 360.0
        pts = sorted(self.points, key=lambda p: p.normalized_azimuth())
        n = len(pts)

        for i in range(n):
            az_a = pts[i].normalized_azimuth()
            az_b = pts[(i + 1) % n].normalized_azimuth()
            span = (az_b - az_a) % 360.0
            if span == 0.0:
                span = 360.0
            offset = (az - az_a) % 360.0
            if offset < span or math.isclose(offset, span, abs_tol=1e-9):
                frac = min(offset, span) / span
                alt_a, alt_b = pts[i].altitude_deg, pts[(i + 1) % n].altitude_deg
                return alt_a + frac * (alt_b - alt_a)

        return pts[-1].altitude_deg  # unreachable safeguard

    def resample(self, step_deg: float = 10.0, start_deg: float = 0.0) -> List[HorizonPoint]:
        """Sample the curve at fixed azimuth steps -- used for REQ-04's
        36-point .hrz export (0-350 deg in 10 deg steps)."""
        count = int(round(360.0 / step_deg))
        return [
            HorizonPoint(
                (start_deg + i * step_deg) % 360.0,
                self.interpolate(start_deg + i * step_deg),
            )
            for i in range(count)
        ]
