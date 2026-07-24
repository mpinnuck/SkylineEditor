"""Horizon curve exporters: .txt / .csv / Stellarium .hrz (REQ-03, REQ-04, REQ-06)."""
from __future__ import annotations

from pathlib import Path
from typing import List

from models.horizon_curve import HorizonCurve

HRZ_EXPORT_STEP_DEG = 10.0  # REQ-04: one point every 10 deg, 0-350 (36 points)


def _write_with_preserved_comments(path: Path, curve: HorizonCurve, data_lines: List[str]) -> None:
    """REQ-06 round-trip: comments/metadata captured on import are re-emitted
    at the top of the file on save, for formats that support comment lines."""
    lines = list(curve.preserved_comments) + data_lines
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_txt(path: Path, curve: HorizonCurve) -> None:
    lines = [f"{p.azimuth_deg:.3f} {p.altitude_deg:.3f}" for p in curve.points]
    _write_with_preserved_comments(path, curve, lines)


def export_csv(path: Path, curve: HorizonCurve) -> None:
    # CSV has no standard comment convention, so REQ-06 preservation does not
    # apply to this format -- documented decision, not an oversight.
    lines = ["azimuth_deg,altitude_deg"]
    lines += [f"{p.azimuth_deg:.3f},{p.altitude_deg:.3f}" for p in curve.points]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_hrz(path: Path, curve: HorizonCurve) -> None:
    """36-point Stellarium-compatible .hrz, sampled every 10 deg (REQ-04)."""
    sampled = curve.resample(step_deg=HRZ_EXPORT_STEP_DEG, start_deg=0.0)
    lines = [f"{p.azimuth_deg:.2f} {p.altitude_deg:.2f}" for p in sampled]
    # N.I.N.A. expects an Az/Alt marker comment line.
    comments = [c for c in curve.preserved_comments if c.strip().upper() not in {"# AZ ALT", "# AZ ALT".title()}]
    path.write_text("\n".join(["# Az Alt", *comments, *lines]) + "\n", encoding="utf-8")
