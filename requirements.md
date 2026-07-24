# SkylineEditor — Requirements

Status: Draft v18

IDs are stable across revisions (traceability) — grouping/order may change, but a given ID always refers to the same requirement.

## Data

Alt/Az data model, validation, and file import/export.

| ID | Requirement |
|----|-------------|
| REQ-01 | Import Alt/Az pairs from a CSV or plain-text file. Delimiter (comma, tab, whitespace) and column order (Az,Alt vs Alt,Az) must be configurable or auto-detected; header row optional. Values are decimal degrees. |
| REQ-36 | The app shall support a Theodolite-only workflow: import a Theodolite dataset (column mapping and session/date selection per REQ-31) directly as the working horizon curve — independent of the image import/stitching pipeline (REQ-08–REQ-13), no photos or calibration required — and export it as a Stellarium-compatible 36-point `.hrz` file (REQ-04). |
| REQ-02 | Import a Stellarium `.hrz` file (space-delimited Az/Alt pairs, decimal degrees, per `landscape.ini` `polygonal_horizon_list` convention). |
| REQ-03 | Save horizon data back as `.txt`, `.csv`, or `.hrz`, via a Save As action that always prompts the user for a destination path and format. |
| REQ-04 | Export a 36-point Stellarium-compatible `.hrz` file, one point every 10° of azimuth (0–350°), sampled from the current horizon curve, via a dedicated Export .hrz action distinct from Save As (REQ-03). This action writes to a fixed default location — `<root folder>/<Skyline Name>/<Skyline Name>.hrz`, inside the skyline's own folder, named after the skyline — with no destination picker; an existing file at that path is overwritten without a confirmation prompt. The exported file opens with a `# Az Alt` header comment line for N.I.N.A. (Nighttime Imaging 'N' Astronomy) compatibility, confirmed not to interfere with Stellarium's own parser. Immediately after export, the app re-reads the written file and displays a preview — a plot of the sampled Az/Alt curve, the file path, and any import warning count — in a popup dialog. A `.hrz` file can also be produced via the general Save As action (REQ-03), which does prompt for a destination; the fixed-path, no-prompt behavior above applies only to this dedicated Export .hrz action. |
| REQ-37 | Export the stitched skyline image (REQ-11) as a Stellarium-compatible landscape ground image, aligned to the exported `.hrz` (REQ-04) using the same north/calibration reference (REQ-09/REQ-10), plus a minimal starter `landscape.ini`, so the photo and the horizon line up correctly when used together in Stellarium. |
| REQ-05 | Save vs. Save As, with an unsaved-changes indicator. Save (as distinct from Save As) always writes to a fixed default filename within the skyline's own folder — `horizon.csv` — regardless of what the skyline was originally imported from; Save As lets the user pick any destination path and format (.csv/.txt/.hrz). |
| REQ-06 | Round-trip fidelity: preserve comments/metadata present in an imported file across an edit-and-resave cycle, where the target format supports it. |
| REQ-07 | Import error reporting: user-facing message for malformed or corrupt files, rather than silent failure. |
| REQ-14 | Validate imported data: azimuth wraps 0–360°, altitude within a defined bound, minimum point count, explicit handling of duplicate azimuth values. All angles (azimuth and altitude) are decimal degrees throughout — no DMS support. |
| REQ-15 | Malformed rows on import: reject the whole file vs. skip-with-warning — behavior to be decided and applied consistently. |
| REQ-16 | Points sorted by azimuth; horizon loop closes at 360°/0°. |
| REQ-17 | Interpolation method between defined points defined for any downstream consumer of the horizon curve. |

## Skyline

Panorama image import/stitching, horizon extraction, and multi-skyline site management.

| ID | Requirement |
|----|-------------|
| REQ-08 | Import a pool of one or more images via file-selection dialog or drag-and-drop: typically a base horizontal pano sweep covering the full 360° at ~0° altitude, plus optional additional sweeps/shots at higher altitude to cover tall foreground obstructions that don't fit in the base row. Each image may be a normal single-frame (1x) photo or a pre-existing multi-shot panorama (e.g. a phone's built-in panorama mode), in any mix — normal 1x shots with consistent overlap are the recommended input for best stitching accuracy; pre-existing panoramas are supported as a fallback but may carry their own baked-in blending/warping artifacts. Accepted formats: JPEG, PNG, TIFF. Any image size/resolution is accepted, no imposed limit. |
| REQ-11 | Stitch the imported image pool into a single skyline (panorama) image by matching overlapping features between images, in both the azimuth (horizontal) and altitude (vertical) directions — not assumed to be a single ordered ring. Every input image (single-frame or pre-existing panorama) is treated as raw, unprojected image data to be aligned and reprojected into the output; the app does not assume a "panorama" input is already in the target projection, so mixed focal lengths/zoom levels across the pool are acceptable. Output projection is equirectangular (linear azimuth and linear altitude mapping), with azimuth 0° at both the left and right edges. If any image(s) cannot be matched to the rest via overlapping features, the app shall identify them and prompt the user to reshoot/replace those specific images rather than guessing a seam. |
| REQ-09 | The user shall mark north (azimuth 0°) manually on the assembled (stitched) panorama image. No automatic detection of north (e.g. from EXIF) is required. |
| REQ-10 | The user shall calibrate the altitude scale on the assembled panorama by marking 0° and 30° altitude at two azimuths 180° apart (e.g. azimuth 0° and azimuth 180°). This gives an empirical pixels-per-degree scale and corrects for any tilt/level drift across the stitched image, with no dependency on lens EXIF/FOV data. |
| REQ-12 | Scan the stitched skyline image and plot a skyline (horizon) overlay derived from it. |
| REQ-13 | Overlay azimuth and altitude scale marks every 10° along the bottom, left, and right edges of the skyline image. |
| REQ-34 | The image pool shall be validated to confirm every azimuth has real captured coverage extending from the terrain/obstruction up through its local sky boundary (i.e. actual photographed sky immediately above the horizon transition at that azimuth). If any azimuth lacks this coverage, the app shall identify the gap and prompt the user to shoot additional images there — the set is incomplete until resolved. No synthetic sky-fill is used to paper over missing coverage; any leftover blank canvas space above a column's own real margin (present only because a taller feature elsewhere set the canvas height) carries no horizon information and needs no fill. |
| REQ-31 | The app shall be able to import a reference/comparison horizon dataset (e.g. exported from a device such as the iPhone Theodolite app, via the standard Alt/Az CSV/text import path — REQ-01) and render it as an overlay on the stitched skyline image alongside the app's own scanned overlay (REQ-12), so the user can visually compare the two. The reference overlay is read-only comparison data, distinct from the editable working horizon curve, and its visibility shall be toggleable independent of the scanned overlay. For Theodolite app exports specifically: azimuth is the `HDG_DEG` column, altitude is the `VERT` column (not the `ALT` column, which is GPS elevation in meters, not an angle). A Theodolite log may contain multiple capture sessions concatenated in one file (distinguished by `DATE_TIME`); the app shall let the user select which session/date to import as the reference rather than blending all rows together. |
| REQ-38 | Where both an auto-scanned curve (REQ-12) and a reference curve (REQ-31, e.g. Theodolite) exist for a skyline, the app shall compute and display a deviation metric between them (e.g. per-azimuth altitude error, mean/max error across the sweep). This turns the comparison from a visual-only aid into a measurable accuracy check — useful for tuning the auto-scan algorithm against ground-truth data, and for giving any user with a reference dataset a confidence figure on the auto-scan result. |
| REQ-32 | When a reference horizon (REQ-31) is loaded, the user shall be able to interactively align the stitched skyline image against the fixed reference-curve overlay by pan (azimuth/altitude offset), rotate (tilt fine-tune), and scale, then save the resulting alignment. Azimuth panning wraps circularly (consistent with azimuth 0° at both edges — REQ-11), not a crop. This is a refinement applied on top of the REQ-09/REQ-10 baseline calibration, not a replacement for it — rotate is a first-order approximation for small camera-roll error (true roll error in an equirectangular projection is a sinusoidal warp, not a linear rotation), so larger tilt drift should still be corrected via REQ-10's two-azimuth calibration. |
| REQ-18 | The app shall manage more than one skyline (each an independent horizon profile + source panorama/images). |
| REQ-19 | The app shall have a configurable root folder under which skyline data is stored. If the root folder is changed after skylines already exist, those existing skyline folders remain in their original location — they are not automatically moved. |
| REQ-20 | The app shall create one folder per skyline under the root folder. |
| REQ-33 | Within a skyline's folder, imported source images (REQ-08) shall be stored in an `images` subfolder. |
| REQ-35 | Within a skyline's folder, imported reference/comparison horizon data (e.g. Theodolite raw export — REQ-31) shall be stored in a `data` subfolder. |
| REQ-21 | Each skyline's folder shall be named after the skyline name (e.g. `BackDeck`, `FrontYard`). Any operating-system-valid folder name is accepted. |
| REQ-22 | A list of skylines shall be presented on the left side of the UI, within the main window's "Skyline" tab (see REQ-39 for the companion "Config" tab). |
| REQ-23 | The user shall be able to add, remove, and edit skylines from that list. Rename renames the existing folder in place (not a move/recreate). Edit includes re-importing/re-stitching source images and re-marking north/calibration, not just metadata changes. |

## UI

| ID | Requirement |
|----|-------------|
| REQ-24 | Plot of Altitude vs. Azimuth, centered on North or South depending on user config setting. |
| REQ-25 | Edit Alt/Az values from a table/list view in the UI. |
| REQ-26 | Interactive plot editing: add/move/delete points directly on the plot (click/drag), not just via the table. |
| REQ-27 | Undo/redo for edits. |
| REQ-28 | The main window shall be centered on the desktop at startup. |
| REQ-30 | The application is GUI-only (Tkinter). No CLI/headless mode is required. |

## Configuration

| ID | Requirement |
|----|-------------|
| REQ-29 | Persist UI preferences (N/S centering, last-used directory, root folder, and the last-selected skyline, etc.) via the standard `load_config()` / `save_config()` pattern rather than resetting each launch. The last-selected skyline is restored and re-selected automatically at startup. See REQ-39 for the in-app editing facility for these settings. |
| REQ-39 | The app shall provide an in-app "Config" tab (alongside the "Skyline" tab housing the skyline list, plot, and table — see REQ-22) for editing persisted settings directly: root folder (with a folder-browse control), last-used directory (with a folder-browse control), and N/S plot-centering, with Apply and Reset actions. Applying changes validates input (e.g. root folder must be non-empty) before committing and persisting via `save_config()`. |

## Open Questions

None outstanding.
