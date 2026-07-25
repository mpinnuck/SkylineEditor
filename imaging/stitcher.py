"""Panorama stitching engine (REQ-11) for a skyline's image pool.

Two-phase approach:

  1. Match-graph analysis, via OpenCV's low-level `cv2.detail` API, finds
     which images belong to the single largest connected group of pairwise
     feature matches, and which don't. This exists specifically for REQ-11's
     "identify [unmatched images] and prompt the user to reshoot/replace
     those specific images" clause -- the high-level `cv2.Stitcher` used in
     phase 2 only reports whole-batch pass/fail, not which image is the
     problem, so it can't satisfy that clause on its own.
  2. The matched subset is handed to `cv2.Stitcher` (PANORAMA mode) for the
     actual feature-based warp/blend into a single panorama. Every input
     image is treated as raw, unprojected data by this pipeline (SIFT
     features + homography estimation from scratch), regardless of whether
     it's a single frame or a phone's own multi-shot panorama -- consistent
     with REQ-11's "does not assume a panorama input is already in the
     target projection".

Deferred to a later pass: REQ-09/REQ-10 calibration (north-marking, altitude
scale) and the equirectangular azimuth-0-at-both-edges output convention --
this module currently returns whatever composition `cv2.Stitcher` produces,
uncalibrated. Fitting the stitched result to the horizon plot depends on
that calibration step and is explicitly out of scope for this pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import cv2
import numpy as np

ProgressFn = Callable[[str], None]


def _report(on_progress: Optional[ProgressFn], message: str) -> None:
    if on_progress is not None:
        on_progress(message)

MATCH_CONFIDENCE_THRESHOLD = 0.3  # OpenCV's own stitching_detailed sample default


class StitchError(Exception):
    """Raised when stitching cannot proceed at all (too few usable images,
    an unreadable file, or the high-level Stitcher itself failing on the
    matched subset)."""


_STATUS_MESSAGES = {
    cv2.Stitcher_ERR_NEED_MORE_IMGS: "Not enough overlap between the matched images to stitch them.",
    cv2.Stitcher_ERR_HOMOGRAPHY_EST_FAIL: "Could not align the matched images (homography estimation failed).",
    cv2.Stitcher_ERR_CAMERA_PARAMS_ADJUST_FAIL: "Could not reconcile camera parameters across the matched images.",
}

_STITCHER_MODES = (
    (cv2.Stitcher_PANORAMA, "PANORAMA"),
    (cv2.Stitcher_SCANS, "SCANS"),
)


@dataclass
class StitchResult:
    image: np.ndarray                              # BGR, as read/written by OpenCV
    matched_paths: List[Path] = field(default_factory=list)
    orphan_paths: List[Path] = field(default_factory=list)


def _load_images(image_paths: List[Path], on_progress: Optional[ProgressFn] = None) -> List[np.ndarray]:
    images = []
    total = len(image_paths)
    for index, path in enumerate(image_paths, start=1):
        _report(on_progress, f"Loading image {index}/{total}: {path.name}")
        img = cv2.imread(str(path))
        if img is None:
            raise StitchError(f"Could not read image file: {path.name}")
        images.append(img)
    return images


def _try_stitch_modes(images: List[np.ndarray]):
    """Try OpenCV stitcher modes in order, returning first success.

    Returns:
        (panorama, mode_name, status_codes, used_indices)
        - panorama is None if no mode succeeds.
        - status_codes maps mode_name -> OpenCV status code.
        - used_indices are the positions (into `images`) that the Stitcher
          actually composited into `panorama`. cv2.Stitcher_OK does NOT mean
          every input image made it into the result -- the Stitcher silently
          drops images whose matches fall below its confidence threshold, and
          `.component()` (populated by `.stitch()` itself) is the only way to
          find out which ones survived.
    """
    status_codes = {}
    for mode_value, mode_name in _STITCHER_MODES:
        stitcher = cv2.Stitcher_create(mode_value)
        # OpenCV's own default (1.0) rejects real-world overlaps too eagerly --
        # e.g. low-texture sky segments -- and silently drops those images
        # from the composite while still reporting Stitcher_OK. Align with
        # the same confidence threshold used by the low-level matcher below.
        stitcher.setPanoConfidenceThresh(MATCH_CONFIDENCE_THRESHOLD)
        status, panorama = stitcher.stitch(images)
        status_codes[mode_name] = int(status)
        if status == cv2.Stitcher_OK:
            used_indices = {int(i) for i in stitcher.component()}
            return panorama, mode_name, status_codes, used_indices
    return None, None, status_codes, set()


def _format_mode_failures(status_codes: dict) -> str:
    parts = []
    for _mode_value, mode_name in _STITCHER_MODES:
        status = status_codes.get(mode_name)
        if status is None:
            continue
        parts.append(f"{mode_name}: {_STATUS_MESSAGES.get(status, f'status {status}')}")
    return "; ".join(parts)


def find_orphan_images(
    image_paths: List[Path], on_progress: Optional[ProgressFn] = None
) -> List[Path]:
    """
    Return the subset of image_paths that do NOT belong to the single
    largest connected group of pairwise feature matches (REQ-11).

    Fewer than 2 images can't produce a match graph at all, so the caller
    is expected to have already checked for that (see stitch()).
    """
    images = _load_images(image_paths, on_progress)

    finder = cv2.SIFT_create()
    total = len(images)
    features = []
    for index, img in enumerate(images, start=1):
        _report(on_progress, f"Analyzing overlap {index}/{total}")
        features.append(cv2.detail.computeImageFeatures2(finder, img))

    _report(on_progress, "Matching images against each other...")
    matcher = cv2.detail_BestOf2NearestMatcher(False, MATCH_CONFIDENCE_THRESHOLD)
    pairwise_matches = matcher.apply2(features)
    matcher.collectGarbage()

    kept_indices = {
        int(i) for i in np.asarray(
            cv2.detail.leaveBiggestComponent(features, pairwise_matches, MATCH_CONFIDENCE_THRESHOLD)
        ).flatten()
    }
    return [p for i, p in enumerate(image_paths) if i not in kept_indices]


def stitch(
    image_paths: List[Path], on_progress: Optional[ProgressFn] = None
) -> StitchResult:
    """
    Stitch the given images into a single panorama (REQ-11).

    Raises StitchError if fewer than 2 images are given, any file can't be
    read, or the high-level Stitcher fails outright on the matched subset.
    Orphan images (identified via find_orphan_images) are excluded from the
    stitch and reported on the returned StitchResult rather than raising --
    a partial, reduced-set stitch is still useful, and the caller can prompt
    for reshoots based on `orphan_paths` (REQ-11).

    If given, on_progress is called with a short human-readable status
    string as each stage starts. There's no callback *during* the
    cv2.Stitcher.stitch() calls themselves -- OpenCV's high-level API
    doesn't expose one -- so those stages report a single "starting" message
    and the caller should treat them as indeterminate.
    """
    if len(image_paths) < 2:
        raise StitchError("At least 2 images are needed to stitch a panorama.")

    # First try the full batch directly. The low-level connected-component
    # prefilter can sometimes be too strict on long real-world sequences,
    # causing unnecessary image drops.
    all_images = _load_images(image_paths, on_progress)
    _report(on_progress, f"Looking for a single panorama across all {len(all_images)} image(s)...")
    panorama, _mode_name, full_statuses, used_indices = _try_stitch_modes(all_images)
    if panorama is not None:
        if len(used_indices) == len(image_paths):
            return StitchResult(image=panorama, matched_paths=image_paths, orphan_paths=[])
        # cv2.Stitcher_OK doesn't mean every image was used -- report the
        # ones it silently dropped as orphans instead of claiming full
        # coverage (REQ-11).
        matched_paths = [p for i, p in enumerate(image_paths) if i in used_indices]
        orphan_paths = [p for i, p in enumerate(image_paths) if i not in used_indices]
        return StitchResult(image=panorama, matched_paths=matched_paths, orphan_paths=orphan_paths)

    orphan_paths = find_orphan_images(image_paths, on_progress)
    matched_paths = [p for p in image_paths if p not in orphan_paths]

    if len(matched_paths) < 2:
        raise StitchError(
            "Fewer than 2 images share enough overlap to stitch -- "
            f"{len(orphan_paths)} image(s) could not be matched to the rest."
        )

    matched_images = _load_images(matched_paths, on_progress)
    _report(on_progress, f"Stitching matched subset ({len(matched_images)} image(s))...")
    panorama, _mode_name, matched_statuses, subset_used_indices = _try_stitch_modes(matched_images)
    if panorama is None:
        full_message = _format_mode_failures(full_statuses)
        matched_message = _format_mode_failures(matched_statuses)
        raise StitchError(
            "Stitching failed for both the full set and matched subset. "
            f"Full set: {full_message}. Matched subset: {matched_message}."
        )

    if len(subset_used_indices) < len(matched_paths):
        # Same silent-drop possibility applies to the matched-subset attempt.
        orphan_paths = orphan_paths + [
            p for i, p in enumerate(matched_paths) if i not in subset_used_indices
        ]
        matched_paths = [p for i, p in enumerate(matched_paths) if i in subset_used_indices]

    return StitchResult(image=panorama, matched_paths=matched_paths, orphan_paths=orphan_paths)


def save_stitched_image(result: StitchResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), result.image)
    if not ok:
        raise StitchError(f"Could not write stitched image to: {path}")
