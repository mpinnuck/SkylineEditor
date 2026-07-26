"""Row-based panorama stitching using known image adjacency (REQ-11).

Rather than discovering which images overlap -- fragile on real outdoor
content with repetitive texture (see project notes: both a hand-rolled
OpenCV pipeline and Hugin's automatic matching struggled on the same
gum-tree-canopy content) -- this module trusts the user-confirmed grid
arrangement (REQ-40, REQ-41) for topology entirely. It only has to solve
the geometric alignment between each already-known-adjacent pair, which is
a much more constrained and reliable problem: there's nothing left for
feature matching to get confused about once there's exactly one candidate
pair being compared, not 34.

Two things were tried and rejected for the pairwise alignment itself
(verified against real photos, not assumed):

  - Pure 2D translation (phase correlation / template matching): fails
    outright (near-zero confidence) because handheld photos of a real 3D
    scene have genuine parallax -- near and far content shift by different
    amounts, which a single rigid shift cannot represent.
  - Full projective homography (8 DOF) per pair, chained sequentially:
    individual pairwise homographies were well-supported (hundreds of
    inliers), but chaining them through several images compounded into
    catastrophic distortion -- a canvas tens of thousands of pixels wide
    from 7 images. This is a known failure mode of naive sequential
    homography stitching, which is exactly why mature tools use
    rotation-constrained bundle adjustment instead of raw homography
    chains.

A similarity transform (rotation + uniform scale + translation, 4 DOF) per
pair, chained sequentially, is the resolution: numerically stable to chain
(no perspective terms to blow up) while still capturing real rotation,
unlike pure translation. Verified end-to-end on real deck photos: a 6-pair
chain produced a coherent, correctly-scaled composite with no ghosting or
warping.

Cross-row (altitude) placement: horizontal position uses the grid's
confirmed column positions (REQ-41) -- the user's manual alignment, not
auto-detected. Vertical position between rows IS auto-computed, using the
sky/tree boundary as a shared reference feature: adjacent rows genuinely
photograph the same treetops from a different tilt angle, so the boundary
between sky and canopy is a natural, reliably-detectable feature common to
both. Each row is aligned to the one below it by matching their sky/tree
boundary over their shared (overlapping) columns, rather than a blind
fixed-percentage overlap -- verified this fixes a real problem: a fixed
overlap doesn't know how much of a row is genuinely redundant with its
neighbor, so it either hides too much real content or leaves a visible
misalignment where the same treetops don't line up between rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from imaging.arrangement import ImageGrid

MATCH_DOWNSCALE_DIM = 1200       # resolution used for feature matching (speed)
COMPOSITE_MAX_DIM = 2200         # resolution used for the actual output composite -- full
                                  # original resolution (4000px+ per source photo) allocates
                                  # several GB for a 14+ image row and gets OOM-killed; this
                                  # is still detailed enough for a Stellarium landscape image
OVERLAP_FRACTION = 0.5          # portion of each image treated as the overlap-candidate region
RATIO_TEST_THRESHOLD = 0.75     # Lowe's ratio test for SIFT matches
RANSAC_REPROJ_THRESHOLD = 4.0
MIN_GOOD_MATCHES = 10           # below this, the pair is treated as unalignable
MAX_CANVAS_PIXELS = 400_000_000  # sanity guard against a runaway canvas from a bad alignment

ProgressFn = Callable[[str], None]

_finder = None  # lazily created -- SIFT_create() is not free


def _get_finder():
    global _finder
    if _finder is None:
        _finder = cv2.SIFT_create()
    return _finder


class StitchError(Exception):
    """Raised when a row (or the whole grid) cannot be stitched -- e.g. a
    known-adjacent pair has too few matches to align confidently, or an
    image file can't be read. A failure here means the confirmed
    arrangement doesn't match reality for that pair (wrong grid position,
    corrupt file, or the images genuinely don't overlap) -- it's surfaced
    as an error rather than silently dropping the pair, since every image
    in the grid was declared adjacent to something on purpose."""


@dataclass
class RowStitchResult:
    image: np.ndarray            # BGR composite for this row
    row_index: int
    image_count: int
    grid_column_span: Tuple[int, int]  # (first, last) column index this row's real images occupy in the grid
    placed_x: int = 0            # this row's actual final canvas position (post-automatic,
    placed_y: int = 0            # post-manual-override) -- what a UI would show/drag from


@dataclass
class StitchResult:
    image: np.ndarray                       # final composited BGR panorama (all rows placed)
    row_results: List[RowStitchResult] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return sum(r.image_count for r in self.row_results)


def _downscale(image: np.ndarray, max_dimension: int) -> Tuple[np.ndarray, float]:
    h, w = image.shape[:2]
    scale = max_dimension / max(h, w)
    if scale >= 1.0:
        return image, 1.0
    resized = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


def _rescale_transform(transform: np.ndarray, scale: float) -> np.ndarray:
    """Convert a transform computed in downscaled-image pixel space to the
    equivalent transform in full-resolution pixel space."""
    to_small = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]])
    to_full = np.array([[1 / scale, 0, 0], [0, 1 / scale, 0], [0, 0, 1]])
    return to_full @ transform @ to_small


@dataclass
class PairwiseMatch:
    points_a: np.ndarray  # inlier points, in image_a's full-frame coordinates
    points_b: np.ndarray  # the same inlier points, in image_b's full-frame coordinates
    angle_deg: float      # rotation of the initial (uncorrected) RANSAC fit
    scale: float


def _pairwise_similarity_match(image_a: np.ndarray, image_b: np.ndarray, pair_label: str) -> PairwiseMatch:
    """
    Find the inlier point correspondences between image_a and image_b's
    known-overlapping edge regions (SIFT + ratio test + RANSAC), and the
    rotation/scale of the resulting fit. Returns the raw inlier points
    (not just the fitted transform) so a corrected transform can be
    re-derived later -- e.g. after removing a systematic rotation bias
    across a whole row (see _detrend_rotation) -- without reusing a
    translation that was only valid for the original, uncorrected rotation.
    """
    h, w = image_a.shape[:2]
    gray_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2GRAY)

    finder = _get_finder()
    kp_a, des_a = finder.detectAndCompute(gray_a[:, int(w * (1 - OVERLAP_FRACTION)):], None)
    kp_b, des_b = finder.detectAndCompute(gray_b[:, : int(w * OVERLAP_FRACTION)], None)

    if des_a is None or des_b is None or len(kp_a) < 2 or len(kp_b) < 2:
        raise StitchError(f"Not enough distinct features to align {pair_label}.")

    matcher = cv2.BFMatcher()
    raw_matches = matcher.knnMatch(des_a, des_b, k=2)
    good = [m for m, n in raw_matches if m.distance < RATIO_TEST_THRESHOLD * n.distance]

    if len(good) < MIN_GOOD_MATCHES:
        raise StitchError(
            f"Only {len(good)} confident match(es) found for {pair_label} "
            f"(need at least {MIN_GOOD_MATCHES}) -- check they're really adjacent in the grid."
        )

    points_a = np.float32([kp_a[m.queryIdx].pt for m in good])
    points_a[:, 0] += w * (1 - OVERLAP_FRACTION)  # restore full-frame A coordinates
    points_b = np.float32([kp_b[m.trainIdx].pt for m in good])

    matrix, inlier_mask = cv2.estimateAffinePartial2D(
        points_b, points_a, method=cv2.RANSAC, ransacReprojThreshold=RANSAC_REPROJ_THRESHOLD
    )
    if matrix is None:
        raise StitchError(f"Could not estimate a stable alignment for {pair_label}.")

    inlier_indices = inlier_mask.ravel().astype(bool)
    inliers_a = points_a[inlier_indices]
    inliers_b = points_b[inlier_indices]
    if len(inliers_a) < MIN_GOOD_MATCHES:
        raise StitchError(
            f"Only {len(inliers_a)} inlier match(es) survived for {pair_label} -- alignment is unreliable."
        )

    angle_deg = float(np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0])))
    scale = float(np.sqrt(matrix[0, 0] ** 2 + matrix[1, 0] ** 2))
    return PairwiseMatch(points_a=inliers_a, points_b=inliers_b, angle_deg=angle_deg, scale=scale)


def _transform_from_rotation_and_points(match: PairwiseMatch, angle_deg: float) -> np.ndarray:
    """
    Build the similarity transform for a given (possibly corrected)
    rotation angle and this match's scale, solving for the translation
    that best aligns the actual matched points under that rotation --
    rather than reusing whatever translation was fit alongside a
    *different* (e.g. pre-drift-correction) rotation, which would leave
    the points misaligned again.
    """
    angle_rad = np.radians(angle_deg)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    rotation_scale = np.array([[match.scale * cos_a, -match.scale * sin_a],
                                [match.scale * sin_a, match.scale * cos_a]])
    centroid_a = match.points_a.mean(axis=0)
    centroid_b = match.points_b.mean(axis=0)
    translation = centroid_a - rotation_scale @ centroid_b
    return np.array([
        [rotation_scale[0, 0], rotation_scale[0, 1], translation[0]],
        [rotation_scale[1, 0], rotation_scale[1, 1], translation[1]],
        [0.0, 0.0, 1.0],
    ])


def _composite(images: List[np.ndarray], transforms: List[np.ndarray]) -> np.ndarray:
    """
    Warp every image into a shared canvas per its transform and blend
    overlaps with distance-to-edge feathering, so seams aren't a hard cut.
    Returns a BGRA image: alpha is 255 wherever some image's warped
    footprint actually reached, 0 elsewhere -- the areas outside any
    image's warped shape (inevitable once images are rotated; the union
    of several rotated rectangles isn't a rectangle) are properly
    transparent rather than opaque black, which also avoids relying on
    "this pixel happens to be pure black" as a stand-in for "no real
    content here" (wrong for any genuinely near-black photo content).

    Each image is warped only within its own bounding box, not the full
    canvas -- warping straight to canvas size was allocating a
    full-canvas-sized temporary per image even though a single image in a
    wide multi-image row only ever touches a small fraction of it. That
    was the dominant memory cost (verified: it's what pushed a 14-image
    row's compositing step to over 1GB of peak memory and contributed to
    an OOM kill on a 15-image row right after it).
    """
    corners_per_image = []
    for image, transform in zip(images, transforms):
        h, w = image.shape[:2]
        corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
        corners_per_image.append(cv2.perspectiveTransform(corners, transform))

    all_corners = np.concatenate(corners_per_image, axis=0)
    x_min, y_min = all_corners.min(axis=0).ravel()
    x_max, y_max = all_corners.max(axis=0).ravel()

    canvas_w = int(np.ceil(x_max - x_min))
    canvas_h = int(np.ceil(y_max - y_min))
    if canvas_w <= 0 or canvas_h <= 0 or canvas_w * canvas_h > MAX_CANVAS_PIXELS:
        raise StitchError(
            f"Computed an implausible canvas size ({canvas_w}x{canvas_h}) -- "
            f"alignment likely failed for one or more images in this row."
        )

    global_offset = np.array([[1, 0, -x_min], [0, 1, -y_min], [0, 0, 1]])

    weight_sum = np.zeros((canvas_h, canvas_w), dtype=np.float32)
    color_sum = np.zeros((canvas_h, canvas_w, 3), dtype=np.float32)

    for image, transform, corners in zip(images, transforms, corners_per_image):
        h, w = image.shape[:2]
        full_transform = global_offset @ transform

        # This image's own footprint within the canvas -- warp only that
        # region, not the whole canvas.
        local_corners = corners - [x_min, y_min]
        bx_min, by_min = local_corners.min(axis=0).ravel()
        bx_max, by_max = local_corners.max(axis=0).ravel()
        bx0, by0 = max(0, int(np.floor(bx_min))), max(0, int(np.floor(by_min)))
        bx1, by1 = min(canvas_w, int(np.ceil(bx_max))), min(canvas_h, int(np.ceil(by_max)))
        box_w, box_h = bx1 - bx0, by1 - by0
        if box_w <= 0 or box_h <= 0:
            continue

        local_transform = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1]]) @ full_transform

        # Only the BGR channels are blended -- the source alpha (uniformly
        # opaque for a real photo) isn't a color value, so weighting it
        # the same way as color doesn't mean anything. The OUTPUT alpha
        # is computed separately below, from where any weight landed.
        warped = cv2.warpPerspective(image[:, :, :3], local_transform, (box_w, box_h))

        source_mask = np.full((h, w), 255, dtype=np.uint8)
        weight = cv2.distanceTransform(source_mask, cv2.DIST_L2, 5).astype(np.float32)
        if weight.max() > 0:
            weight /= weight.max()
        warped_weight = cv2.warpPerspective(weight, local_transform, (box_w, box_h))

        color_sum[by0:by1, bx0:bx1] += warped.astype(np.float32) * warped_weight[:, :, None]
        weight_sum[by0:by1, bx0:bx1] += warped_weight

    weight_sum_safe = np.where(weight_sum > 1e-6, weight_sum, 1.0)
    color = (color_sum / weight_sum_safe[:, :, None]).astype(np.uint8)
    has_content = weight_sum > 1e-6
    color[~has_content] = 0
    alpha = np.where(has_content, 255, 0).astype(np.uint8)
    return cv2.merge([color[:, :, 0], color[:, :, 1], color[:, :, 2], alpha])


def _detrend_and_build_transforms(matches: List[PairwiseMatch]) -> List[np.ndarray]:
    """
    Remove the systematic per-step rotation bias across a row's pairwise
    matches, then build each pair's transform by re-solving for
    translation under the corrected rotation (via _transform_from_rotation_
    and_points) -- not by reusing the translation from the original,
    uncorrected fit.

    Verified on real data: every pairwise fit in one real 15-image row had
    a roll of -5 to -16 degrees, all the same sign -- plausibly from how
    the phone was tilted while panning for a higher-altitude row. That's
    not matching noise (each pair still had hundreds of inliers); it's a
    genuine, consistent per-shot bias. Chaining it uncorrected compounds to
    100+ degrees of rotation across the row, turning what should be a wide
    horizontal strip into a badly warped, nearly-vertical one.

    An earlier version of this fix corrected the rotation but kept each
    pair's originally-fit translation, which was only ever valid for the
    *original* rotation -- pairing a new rotation with a stale translation
    left the actual matched points misaligned again, producing visible
    ghosting at every seam and a diagonal drift across the row. Re-solving
    translation from the real inlier points under the corrected rotation
    (a standard centroid-alignment step, given known rotation and scale)
    fixes both.
    """
    mean_angle = float(np.mean([m.angle_deg for m in matches]))
    return [_transform_from_rotation_and_points(match, match.angle_deg - mean_angle) for match in matches]


def stitch_row(
    image_paths: List[Path], row_label: str, on_progress: Optional[ProgressFn] = None
) -> np.ndarray:
    """
    Stitch one row -- a full or partial azimuthal sweep (REQ-40) -- into a
    single composite, chaining known-adjacent pairwise similarity
    transforms (see module docstring for why this approach, not full
    homography or pure translation).
    """
    if not image_paths:
        raise StitchError(f"{row_label}: no images to stitch.")

    if len(image_paths) == 1:
        image, _ = _downscale(_read_image(image_paths[0]), COMPOSITE_MAX_DIM)
        return _to_bgra(image)

    # Images are loaded at COMPOSITE_MAX_DIM, not their true original
    # resolution -- compositing several 4000px+ photos at full size
    # allocates several GB for a 14+ image row (this was verified: it gets
    # OOM-killed). COMPOSITE_MAX_DIM is still detailed enough for a
    # Stellarium landscape image.
    images = []
    for i, path in enumerate(image_paths, start=1):
        if on_progress:
            on_progress(f"{row_label}: loading image {i}/{len(image_paths)} ({path.name})")
        image, _ = _downscale(_read_image(path), COMPOSITE_MAX_DIM)
        images.append(image)

    # Match at a further-downscaled, shared resolution (speed, and so every
    # pairwise transform in the chain is computed in the same coordinate
    # system) -- relative to the COMPOSITE_MAX_DIM images, not the
    # originals. Derived from the plain BGR images, before the alpha
    # channel is added below -- feature matching only needs 3 channels.
    match_scale = _downscale(images[0], MATCH_DOWNSCALE_DIM)[1]
    scaled = []
    for image in images:
        h, w = image.shape[:2]
        resized = cv2.resize(image, (int(w * match_scale), int(h * match_scale)), interpolation=cv2.INTER_AREA)
        scaled.append(resized)

    pairwise_matches = []
    for i in range(1, len(scaled)):
        if on_progress:
            on_progress(f"{row_label}: aligning image {i + 1}/{len(scaled)} ({image_paths[i].name})")
        pair_label = f"{image_paths[i - 1].name} -> {image_paths[i].name}"
        pairwise_matches.append(_pairwise_similarity_match(scaled[i - 1], scaled[i], pair_label))

    pairwise_transforms = _detrend_and_build_transforms(pairwise_matches)

    cumulative = [np.eye(3)]
    for transform in pairwise_transforms:
        cumulative.append(cumulative[-1] @ transform)

    full_transforms = [_rescale_transform(t, match_scale) for t in cumulative]

    if on_progress:
        on_progress(f"{row_label}: compositing {len(images)} image(s)...")

    return _composite([_to_bgra(image) for image in images], full_transforms)


def _read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path))
    if image is None:
        raise StitchError(f"Could not read image file: {path.name}")
    return image


def _to_bgra(image: np.ndarray) -> np.ndarray:
    """Add a fully-opaque alpha channel to a 3-channel BGR image (a no-op
    if it already has one). Used so the areas a warped/composited row
    doesn't actually cover -- currently solid black -- can be marked
    transparent (alpha=0) instead, rather than relying on "this pixel
    happens to be pure black" as a proxy for "no real content here",
    which is also wrong for any genuinely near-black photo content (deep
    shadow, a dark object, etc)."""
    if image.shape[2] == 4:
        return image
    b, g, r = cv2.split(image)
    alpha = np.full_like(b, 255)
    return cv2.merge([b, g, r, alpha])


def stitch_grid(
    grid: ImageGrid,
    on_progress: Optional[ProgressFn] = None,
    row_offsets: Optional[Dict[int, Tuple[int, int]]] = None,
) -> StitchResult:
    """
    Stitch every non-empty row in the grid, then place each row's
    composite into a shared canvas using the grid's confirmed column
    positions for horizontal placement (REQ-41) -- rows are stacked
    vertically in data order (row 0, the base/0-degree sweep, at the
    bottom; higher rows above it), matching how the arrangement view
    already displays them.

    row_offsets, if given, is a manual per-row (dx, dy) nudge applied on
    top of the automatic placement -- the automatic sky/tree boundary
    alignment is a good default but isn't always right (verified: it can
    be led astray by too little overlap data on a sparse row), so this is
    the user's override, not a replacement for the automatic pass.
    """
    if grid.row_count == 0:
        raise StitchError("No rows to stitch.")

    row_results: List[RowStitchResult] = []
    for row_index in range(grid.row_count):
        row = grid.rows[row_index]
        real_columns = [c for c, path in enumerate(row) if path is not None]
        if not real_columns:
            continue
        row_images = [row[c] for c in real_columns]

        if on_progress:
            on_progress(f"Stitching row {row_index} ({len(row_images)} image(s))...")
        row_label = f"row {row_index}"
        row_image = stitch_row(row_images, row_label, on_progress)
        row_results.append(
            RowStitchResult(
                image=row_image,
                row_index=row_index,
                image_count=len(row_images),
                grid_column_span=(real_columns[0], real_columns[-1]),
            )
        )

    if not row_results:
        raise StitchError("No non-empty rows to stitch.")

    composite = _place_rows(grid, row_results, row_offsets=row_offsets)
    return StitchResult(image=composite, row_results=row_results)


SKY_HUE_MIN, SKY_HUE_MAX = 90, 140  # OpenCV hue range (0-179) for clear blue sky
SKY_MIN_BRIGHTNESS = 120            # HSV value threshold
MIN_BOUNDARY_SAMPLES = 30           # below this many valid shared columns, fall back to a default overlap
FALLBACK_OVERLAP_FRACTION = 0.3     # used only when boundary-matching isn't possible for a pair


def _detect_sky_boundary(image: np.ndarray) -> np.ndarray:
    """
    For each column, find the y-position (within that column) where the
    image's real content transitions from sky to non-sky (canopy, roofline,
    etc), scanning downward from the topmost actual content -- not from
    pixel row 0, which is usually black padding given these composites are
    diagonal/wavy shapes, not clean rectangles. Returns an array of length
    `width`; -1 marks a column with no usable boundary (no content, its
    topmost content isn't sky, or it's sky all the way through with no
    transition found).
    """
    hsv = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2HSV)
    has_content = image[:, :, 3] > 0 if image.shape[2] == 4 else image.sum(axis=2) > 0
    hue = hsv[:, :, 0].astype(np.int32)
    value = hsv[:, :, 2].astype(np.int32)
    is_sky = (value > SKY_MIN_BRIGHTNESS) & (hue > SKY_HUE_MIN) & (hue < SKY_HUE_MAX) & has_content

    h, w = image.shape[:2]
    first_content_row = np.argmax(has_content, axis=0)
    top_is_sky = is_sky[first_content_row, np.arange(w)]

    row_indices = np.arange(h)[:, None]
    before_content = row_indices < first_content_row[None, :]
    not_sky_below_content = (~is_sky) & (~before_content)  # ignore padding above real content

    has_transition = not_sky_below_content.any(axis=0)
    first_non_sky = np.argmax(not_sky_below_content, axis=0)

    valid = has_content.any(axis=0) & top_is_sky & has_transition
    return np.where(valid, first_non_sky, -1)


def _shared_valid_boundary(
    front_boundary: np.ndarray, front_x: int,
    back_boundary: np.ndarray, back_x: int,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """The two boundary arrays' values over their shared/overlapping
    columns, restricted to columns valid in both. None if there's nothing
    usable to compare."""
    shared_x0 = max(front_x, back_x)
    shared_x1 = min(front_x + len(front_boundary), back_x + len(back_boundary))
    if shared_x1 <= shared_x0:
        return None
    front_vals = front_boundary[shared_x0 - front_x : shared_x1 - front_x]
    back_vals = back_boundary[shared_x0 - back_x : shared_x1 - back_x]
    valid = (front_vals >= 0) & (back_vals >= 0)
    if valid.sum() < MIN_BOUNDARY_SAMPLES:
        return None
    return front_vals[valid], back_vals[valid]


HORIZONTAL_SEARCH_RADIUS = 2000  # pixels either side of the grid-based guess to search
HORIZONTAL_SEARCH_STEP = 5       # coarse step -- this is a refinement search, not pixel-exact
MIN_SHAPE_CORRELATION = 0.5      # below this, the shape match isn't trustworthy enough to use
MIN_OVERLAP_FRACTION = 0.15      # ALSO require this fraction of the narrower row's width in
                                  # shared samples -- a shift can otherwise "win" on a spuriously
                                  # high correlation computed from too little real overlap to
                                  # trust. Verified this is a real failure mode, not theoretical:
                                  # on a sparse 3-image case, a 34-sample candidate scored higher
                                  # (0.86) than a 943-sample candidate (0.70) for the same pair --
                                  # the 34-sample "winner" was noise, the 943-sample one was real.


def _horizontal_shape_offset(
    front_boundary: np.ndarray, front_x: int,
    back_boundary: np.ndarray, back_x: int,
) -> Optional[int]:
    """
    Refine back_x by finding the horizontal shift that best matches the
    *shape* of back_boundary's sky/tree line against front_boundary's --
    not just their height (see _boundary_alignment_offset for that), but
    the actual silhouette profile, via normalized cross-correlation over a
    search range around the grid-based starting guess. This corrects for
    the grid arrangement being only roughly right horizontally (REQ-41 is
    a manual, approximate placement) using the treeline's own shape as a
    much more precise reference than column position alone.

    Only candidates with at least MIN_OVERLAP_FRACTION of the narrower
    row's width in valid shared samples are considered -- see
    MIN_OVERLAP_FRACTION's comment for why this matters. Returns None if
    no candidate clears both that and the correlation threshold, in which
    case the caller keeps the original grid-based position.
    """
    min_required_samples = max(
        MIN_BOUNDARY_SAMPLES,
        int(MIN_OVERLAP_FRACTION * min(len(front_boundary), len(back_boundary))),
    )

    best_shift, best_score = None, -np.inf
    for shift in range(-HORIZONTAL_SEARCH_RADIUS, HORIZONTAL_SEARCH_RADIUS + 1, HORIZONTAL_SEARCH_STEP):
        shared = _shared_valid_boundary(front_boundary, front_x, back_boundary, back_x + shift)
        if shared is None:
            continue
        f, b = shared
        if len(f) < min_required_samples:
            continue
        f = f.astype(np.float64) - f.mean()
        b = b.astype(np.float64) - b.mean()
        denom = np.sqrt((f**2).sum() * (b**2).sum())
        if denom < 1e-6:
            continue
        score = float((f * b).sum() / denom)
        if score > best_score:
            best_score, best_shift = score, shift

    if best_shift is None or best_score < MIN_SHAPE_CORRELATION:
        return None
    return back_x + best_shift


def _boundary_alignment_offset(
    front_boundary: np.ndarray, front_x: int, front_y: int,
    back_boundary: np.ndarray, back_x: int,
) -> Optional[int]:
    """
    Compute the canvas y-position for a row (whose boundary is
    back_boundary, already placed at back_x horizontally) so its sky/tree
    boundary's HEIGHT lines up with the row in front of it (front_boundary,
    placed at (front_x, front_y)), compared only over their shared/overlap
    columns. Returns None if there isn't enough shared, valid boundary
    data -- the caller falls back to a default overlap in that case.
    """
    shared = _shared_valid_boundary(front_boundary, front_x, back_boundary, back_x)
    if shared is None:
        return None
    front_vals, back_vals = shared

    front_boundary_canvas_y = front_y + np.median(front_vals)
    back_boundary_local_y = np.median(back_vals)
    return int(round(front_boundary_canvas_y - back_boundary_local_y))


def _place_rows(
    grid: ImageGrid,
    row_results: List[RowStitchResult],
    row_offsets: Optional[Dict[int, Tuple[int, int]]] = None,
) -> np.ndarray:
    """
    Combine each row's composite into one canvas.

    Horizontal placement starts from each row's confirmed grid-column span
    (REQ-41's manual arrangement) as an initial estimate, then refines it
    by cross-correlating the sky/tree boundary's SHAPE against the row
    below it -- the grid position is only ever approximately right, and
    the treeline's own silhouette is a far more precise reference than
    column position alone. Falls back to the grid-based estimate
    unrefined if no candidate shift gets a reliable correlation score.

    Vertical placement aligns each row to the one below it by matching
    their sky/tree boundary's HEIGHT (see module docstring) over their
    shared columns, evaluated at the horizontally-refined positions above.
    Falls back to a fixed overlap only when there isn't enough shared,
    valid boundary data (e.g. an overcast row, or rows that don't share
    much azimuthal range) to compute it reliably.

    row_offsets, if given, is a manual per-row (dx, dy) applied on top of
    the automatic placement above -- each row's own automatic position is
    computed exactly as before, then nudged by its override afterward.
    Overrides don't cascade: adjusting row 2 never moves row 1, since row
    1's placement was already finalized independently.

    Compositing is z-order, not a plain stack: row 0 (the base, 0-degree
    sweep) is drawn last so it always wins where it has content; each
    higher row is drawn first (further back), so only the part that
    extends above the row in front of it actually shows through.
    """
    if len(row_results) == 1:
        return row_results[0].image

    reference = max(row_results, key=lambda r: r.image.shape[1])
    reference_row = grid.rows[reference.row_index]
    reference_columns = [c for c, path in enumerate(reference_row) if path is not None]
    px_per_column = reference.image.shape[1] / max(len(reference_columns), 1)

    ordered = sorted(row_results, key=lambda r: r.row_index)  # row 0 (base) first

    x_offsets = {}
    for result in ordered:
        first_col, _ = result.grid_column_span
        x_offsets[result.row_index] = int(round(first_col * px_per_column))

    # Boundary arrays computed once per row and reused for both the
    # horizontal shape refinement and the vertical height alignment below.
    boundaries = {result.row_index: _detect_sky_boundary(result.image) for result in ordered}

    # Vertical placement, built top-down in canvas coordinates (y increases
    # downward, same as the final image) once each row's top edge is known.
    # Row 0 starts provisionally at y=0; every row's y may end up negative
    # at this stage since higher rows are pushed upward (negative y)
    # relative to it -- everything is shifted into valid canvas coordinates
    # afterward, once the true topmost extent is known.
    top_y = {ordered[0].row_index: 0}
    bottom_y = {ordered[0].row_index: ordered[0].image.shape[0]}

    for prev, current in zip(ordered, ordered[1:]):
        # Horizontal: refine the grid-column-based guess using the actual
        # treeline shape -- REQ-41's manual grid placement is only ever
        # roughly right, and the boundary shape is a far more precise
        # reference than column position alone.
        refined_x = _horizontal_shape_offset(
            front_boundary=boundaries[prev.row_index], front_x=x_offsets[prev.row_index],
            back_boundary=boundaries[current.row_index], back_x=x_offsets[current.row_index],
        )
        if refined_x is not None:
            x_offsets[current.row_index] = refined_x

        # Vertical: align the boundary's height, at the (now horizontally
        # refined) shared columns.
        offset = _boundary_alignment_offset(
            front_boundary=boundaries[prev.row_index], front_x=x_offsets[prev.row_index], front_y=top_y[prev.row_index],
            back_boundary=boundaries[current.row_index], back_x=x_offsets[current.row_index],
        )
        if offset is None:
            overlap = int(round(current.image.shape[0] * FALLBACK_OVERLAP_FRACTION))
            offset = top_y[prev.row_index] - (current.image.shape[0] - overlap)
        top_y[current.row_index] = offset
        bottom_y[current.row_index] = offset + current.image.shape[0]

    # Manual overrides (if any) are applied here, after the automatic
    # placement above has fully run -- each row's automatic position is
    # already finalized, so a nudge to one row can never cascade into
    # moving another.
    if row_offsets:
        for idx, (dx, dy) in row_offsets.items():
            if idx not in x_offsets:
                continue
            x_offsets[idx] += dx
            top_y[idx] += dy
            bottom_y[idx] += dy

    # Shift so the topmost row's top edge sits at canvas y=0, and the
    # leftmost row's left edge sits at canvas x=0 -- the horizontal shape
    # refinement above can push a row's offset negative (e.g. it needs to
    # sit further left than row 0's own x=0 start), which without this
    # normalization produces negative slice indices below.
    min_y = min(top_y.values())
    canvas_top = {idx: top_y[idx] - min_y for idx in top_y}

    min_x = min(x_offsets.values())
    x_offsets = {idx: x - min_x for idx, x in x_offsets.items()}

    total_width = max(x_offsets[r.row_index] + r.image.shape[1] for r in ordered)
    total_height = max(bottom_y[idx] - min_y for idx in bottom_y)
    if total_width * total_height > MAX_CANVAS_PIXELS:
        raise StitchError(f"Combined canvas ({total_width}x{total_height}) is implausibly large.")

    canvas = np.zeros((total_height, total_width, 4), dtype=np.uint8)  # transparent by default

    # Draw back-to-front: highest row first (furthest behind), row 0 last
    # (frontmost). Each row's own composite is a diagonal/wavy shape inside
    # a rectangular bounding box, not a clean rectangle -- a blind
    # full-rectangle assignment here would paint that row's own transparent
    # padding corners over real content from whatever row is behind it,
    # producing a visible gap even where the rows genuinely overlap.
    # Masking to only the row's actual content pixels (via its real alpha
    # channel) fixes that: wherever a row has nothing, whatever is already
    # on the canvas (from a row further back, or empty canvas) shows
    # through instead.
    for result in sorted(ordered, key=lambda r: -r.row_index):
        h, w = result.image.shape[:2]
        x0 = x_offsets[result.row_index]
        y0 = canvas_top[result.row_index]
        result.placed_x = x0
        result.placed_y = y0
        region = canvas[y0 : y0 + h, x0 : x0 + w]
        has_content = result.image[:, :, 3] > 0
        region[has_content] = result.image[has_content]

    return canvas


def save_stitched_image(result: StitchResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), result.image)
    if not ok:
        raise StitchError(f"Could not write stitched image to: {path}")
