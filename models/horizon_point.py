"""A single Alt/Az horizon sample point."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HorizonPoint:
    azimuth_deg: float   # decimal degrees, wraps to [0, 360)
    altitude_deg: float  # decimal degrees

    def normalized_azimuth(self) -> float:
        """Azimuth wrapped into [0, 360)."""
        return self.azimuth_deg % 360.0
