"""Row position adjustment view -- drag a row to correct automatic placement.

Shown after a stitch has run. The automatic sky/tree boundary alignment
(imaging/stitcher.py) is a good default but isn't always right -- verified
it can be led astray on a row with limited overlap data -- so this is the
user's manual override for whichever row needs it, applied on top of the
automatic placement rather than replacing it.

Dragging repositions a downscaled preview live, for responsiveness; the
actual full-resolution composite is only regenerated when the user clicks
Re-stitch, since re-running the full pipeline on every drag frame would be
far too slow.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional, Tuple

import cv2
from PIL import Image, ImageTk

DISPLAY_MAX_WIDTH = 900
DISPLAY_MAX_HEIGHT = 400


class RowAdjustView(tk.Frame):
    def __init__(self, parent, viewmodel, on_restitch_requested):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.on_restitch_requested = on_restitch_requested

        self._thumbnails: Dict[int, ImageTk.PhotoImage] = {}   # kept alive -- Tk drops GC'd images
        self._canvas_items: Dict[int, int] = {}                # row_index -> canvas item id
        self._display_scale = 1.0
        self._drag_row: Optional[int] = None
        self._drag_last_pos: Tuple[int, int] = (0, 0)
        self._drag_start_offset: Tuple[int, int] = (0, 0)
        self._drag_total_delta: Tuple[int, int] = (0, 0)

        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=4, pady=4)
        tk.Label(top, text="Drag a row to nudge its position. Changes apply on Re-stitch.").pack(side=tk.LEFT)
        tk.Button(top, text="Re-stitch", command=self._request_restitch).pack(side=tk.RIGHT)
        tk.Button(top, text="Reset all offsets", command=self._reset_all).pack(side=tk.RIGHT, padx=(0, 6))

        self.status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.status_var, fg="#a00", anchor="w").pack(fill=tk.X, padx=4)

        canvas_frame = tk.Frame(self)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Fixed initial size, deliberately not sized to fit full-resolution
        # content -- see image_arrangement_view.py's canvas for why an
        # unbounded canvas here would silently inflate the whole window.
        self._canvas = tk.Canvas(canvas_frame, bg="#222222", highlightthickness=0,
                                  width=DISPLAY_MAX_WIDTH, height=DISPLAY_MAX_HEIGHT)
        hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self._canvas.xview)
        vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        canvas_frame.grid_rowconfigure(0, weight=1)
        canvas_frame.grid_columnconfigure(0, weight=1)

        self.refresh()

    def refresh(self) -> None:
        """Call after a stitch completes, or on skyline/tab switch."""
        self._canvas.delete("all")
        self._thumbnails.clear()
        self._canvas_items.clear()
        self._drag_row = None

        result = self.viewmodel.last_result
        if result is None or not result.row_results:
            self.status_var.set("Run Stitch (Import tab) first to see rows here.")
            self._canvas.configure(scrollregion=(0, 0, 0, 0))
            return
        self.status_var.set("")

        # One shared display scale for every row, so their thumbnails and
        # positions stay mutually consistent with each other.
        max_x = max(r.placed_x + r.image.shape[1] for r in result.row_results)
        max_y = max(r.placed_y + r.image.shape[0] for r in result.row_results)
        self._display_scale = min(
            DISPLAY_MAX_WIDTH / max(max_x, 1),
            DISPLAY_MAX_HEIGHT / max(max_y, 1),
            1.0,  # never upscale a small composite
        )

        for row in result.row_results:
            thumbnail = self._make_thumbnail(row.image)
            self._thumbnails[row.row_index] = thumbnail
            x = int(row.placed_x * self._display_scale)
            y = int(row.placed_y * self._display_scale)
            tag = f"row{row.row_index}"
            item = self._canvas.create_image(x, y, anchor="nw", image=thumbnail, tags=(tag,))
            self._canvas_items[row.row_index] = item
            self._canvas.tag_bind(item, "<ButtonPress-1>", lambda e, idx=row.row_index: self._on_press(e, idx))
            self._canvas.tag_bind(item, "<B1-Motion>", lambda e, idx=row.row_index: self._on_drag(e, idx))
            self._canvas.tag_bind(item, "<ButtonRelease-1>", lambda e, idx=row.row_index: self._on_release(e, idx))

        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _make_thumbnail(self, cv_image) -> ImageTk.PhotoImage:
        h, w = cv_image.shape[:2]
        new_w = max(1, int(w * self._display_scale))
        new_h = max(1, int(h * self._display_scale))
        small = cv2.resize(cv_image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        # Row composites are BGRA (the transparent-border areas outside a
        # row's actual warped content) -- convert to matching RGBA so
        # PIL/Tk render that transparency, rather than misinterpreting
        # alpha as a 4th color channel.
        if small.shape[2] == 4:
            rgb = cv2.cvtColor(small, cv2.COLOR_BGRA2RGBA)
        else:
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        return ImageTk.PhotoImage(Image.fromarray(rgb))

    # -- Drag handling --------------------------------------------------------------------

    def _on_press(self, event, row_index: int) -> None:
        self._drag_row = row_index
        self._drag_last_pos = (event.x, event.y)
        self._drag_start_offset = self.viewmodel.get_row_offset(row_index)
        self._drag_total_delta = (0, 0)
        self._canvas.tag_raise(self._canvas_items[row_index])

    def _on_drag(self, event, row_index: int) -> None:
        if self._drag_row != row_index:
            return
        dx = event.x - self._drag_last_pos[0]
        dy = event.y - self._drag_last_pos[1]
        self._canvas.move(self._canvas_items[row_index], dx, dy)
        self._drag_last_pos = (event.x, event.y)
        total_dx, total_dy = self._drag_total_delta
        self._drag_total_delta = (total_dx + dx, total_dy + dy)

    def _on_release(self, _event, row_index: int) -> None:
        if self._drag_row != row_index:
            return
        self._drag_row = None
        total_dx, total_dy = self._drag_total_delta
        if total_dx == 0 and total_dy == 0:
            return
        # Convert the display-space drag back to full-resolution pixels --
        # the manual offset stitcher.py applies is in real image pixels,
        # not scaled-down preview pixels.
        full_dx = int(round(total_dx / self._display_scale))
        full_dy = int(round(total_dy / self._display_scale))
        start_dx, start_dy = self._drag_start_offset
        self.viewmodel.set_row_offset(row_index, start_dx + full_dx, start_dy + full_dy)
        self.status_var.set(
            f"Row {row_index} nudged -- click Re-stitch to apply to the full-resolution image."
        )

    # -- Actions ------------------------------------------------------------------------

    def _reset_all(self) -> None:
        result = self.viewmodel.last_result
        if result is None:
            return
        for row in result.row_results:
            self.viewmodel.reset_row_offset(row.row_index)
        self.refresh()

    def _request_restitch(self) -> None:
        self.status_var.set("Re-stitch requested...")
        started = bool(self.on_restitch_requested())
        if started:
            self.status_var.set("Re-stitching... progress is shown on the Import tab.")
        else:
            self.status_var.set("Could not start Re-stitch (it may already be running).")
