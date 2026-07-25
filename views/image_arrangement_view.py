"""Thumbnail grid arrangement view (REQ-40, REQ-41).

Populates a grid from the disciplined capture sequence (REQ-40) -- the user
tells the app how many rows there are and how many images are in each --
then lets them drag-and-drop thumbnails to correct anything before
stitching.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from PIL import Image, ImageTk

from imaging.arrangement import ArrangementError, Position

THUMBNAIL_SIZE = (110, 82)


class ImageArrangementView(tk.Frame):
    def __init__(self, parent, viewmodel, on_change=None):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.on_change = on_change or (lambda: None)

        self._thumbnails: Dict[Position, ImageTk.PhotoImage] = {}  # keep refs alive -- Tk drops GC'd images
        self._cell_widgets: Dict[Position, tk.Label] = {}
        self._drag_start: Optional[Position] = None

        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=4, pady=4)
        tk.Label(top, text="Images per row, base row first (e.g. 14, 15, 5):").pack(side=tk.LEFT)
        self.row_sizes_var = tk.StringVar(value="")
        tk.Entry(top, textvariable=self.row_sizes_var, width=20).pack(side=tk.LEFT, padx=(4, 8))
        tk.Button(top, text="Arrange", command=self._on_arrange).pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Enter each row's image count and click Arrange.")
        tk.Label(self, textvariable=self.status_var, fg="#a00", anchor="w").pack(fill=tk.X, padx=4)

        # Scrollable grid area -- a full sweep's row can easily be wider
        # than the visible window (e.g. REQ-40's 14+ image base row).
        outer = tk.Frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._canvas = tk.Canvas(outer, highlightthickness=0)
        hbar = ttk.Scrollbar(outer, orient=tk.HORIZONTAL, command=self._canvas.xview)
        vbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self._grid_frame = tk.Frame(self._canvas)
        self._canvas.create_window((0, 0), window=self._grid_frame, anchor="nw")
        self._grid_frame.bind(
            "<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )

    # -- Building / refreshing the grid --------------------------------------------------

    def _on_arrange(self) -> None:
        if self.viewmodel.current_skyline is None:
            messagebox.showinfo("No skyline selected", "Select or create a skyline first.")
            return
        row_sizes = self._parse_row_sizes(self.row_sizes_var.get())
        if row_sizes is None:
            messagebox.showerror(
                "Invalid row sizes",
                "Enter one whole number per row, separated by commas -- e.g. 14, 15, 5.",
            )
            return
        try:
            self.viewmodel.build_arrangement(row_sizes)
        except ArrangementError as exc:
            messagebox.showerror("Cannot arrange", str(exc))
            return
        self.status_var.set("")
        self._render_grid()
        self.on_change()

    @staticmethod
    def _parse_row_sizes(text: str) -> Optional[List[int]]:
        """Parse "14, 15, 5" (commas and/or whitespace as separators) into
        [14, 15, 5]. Returns None on any malformed entry rather than
        guessing at a partial result."""
        pieces = [p for p in text.replace(",", " ").split() if p]
        if not pieces:
            return None
        try:
            return [int(p) for p in pieces]
        except ValueError:
            return None

    def refresh(self) -> None:
        """Call on skyline selection change / tab switch."""
        if self.viewmodel.grid is None:
            self._clear_grid()
            skyline = self.viewmodel.current_skyline
            self.status_var.set(
                "No skyline selected." if skyline is None
                else "Enter each row's image count and click Arrange."
            )
            return
        self._render_grid()

    def _clear_grid(self) -> None:
        for widget in self._grid_frame.winfo_children():
            widget.destroy()
        self._thumbnails.clear()
        self._cell_widgets.clear()

    def _render_grid(self) -> None:
        self._clear_grid()
        grid = self.viewmodel.grid
        if grid is None:
            return
        # Display order is reversed from data/storage order: row 0 in the
        # data (the base, 0-degree sweep, per REQ-40) is shown at the
        # BOTTOM, and higher-altitude rows are shown above it -- matching
        # how they actually sit relative to each other in the real scene.
        # Drag/swap logic still operates on the underlying data position
        # (row, col), unaffected by this display-only reordering.
        for row in range(grid.row_count):
            visual_row = (grid.row_count - 1) - row
            self._make_row_label(row).grid(
                row=visual_row, column=0, padx=(0, 6), pady=2, sticky="e"
            )
            for col in range(grid.column_count):
                path = grid.rows[row][col]
                position = (row, col)
                cell = self._make_cell(path, position)
                cell.grid(row=visual_row, column=col + 1, padx=2, pady=2)
                self._cell_widgets[position] = cell
        self.status_var.set(
            f"{grid.row_count} row(s), up to {grid.column_count} image(s) wide. "
            f"Drag a thumbnail onto another to swap positions."
        )

    def _make_row_label(self, row: int) -> tk.Label:
        text = "0\u00b0\n(base)" if row == 0 else f"Row {row}\n(upper)"
        return tk.Label(self._grid_frame, text=text, font=("TkDefaultFont", 7), fg="#666", justify=tk.RIGHT)

    def _make_cell(self, path: Optional[Path], position: Position) -> tk.Label:
        if path is not None:
            photo = self._load_thumbnail(path)
        else:
            photo = None

        if photo is not None:
            self._thumbnails[position] = photo
            label = tk.Label(
                self._grid_frame, image=photo, text=path.name, compound=tk.TOP,
                font=("TkDefaultFont", 7), wraplength=THUMBNAIL_SIZE[0],
                relief=tk.RIDGE, borderwidth=1,
            )
        elif path is not None:
            # Real path but unreadable as an image -- still show it (with a
            # visible problem marker) rather than silently treating it as empty.
            label = tk.Label(
                self._grid_frame, text=f"\u26a0 {path.name}\n(unreadable)", width=14, height=6,
                relief=tk.RIDGE, borderwidth=1, fg="#a00", wraplength=THUMBNAIL_SIZE[0],
            )
        else:
            label = tk.Label(
                self._grid_frame, text="(empty)", width=14, height=6,
                relief=tk.SUNKEN, borderwidth=1, fg="#999",
            )

        label.bind("<ButtonPress-1>", lambda _e, pos=position: self._on_drag_start(pos))
        label.bind("<ButtonRelease-1>", self._on_drag_release)
        return label

    @staticmethod
    def _load_thumbnail(path: Path) -> Optional[ImageTk.PhotoImage]:
        try:
            image = Image.open(path)
            image.thumbnail(THUMBNAIL_SIZE)
            return ImageTk.PhotoImage(image)
        except OSError:
            return None

    # -- Drag-and-drop (swap) ---------------------------------------------------------

    def _on_drag_start(self, position: Position) -> None:
        self._drag_start = position

    def _on_drag_release(self, event) -> None:
        if self._drag_start is None:
            return
        start = self._drag_start
        self._drag_start = None

        target_widget = self.winfo_containing(event.x_root, event.y_root)
        target_position = self._position_of(target_widget)
        if target_position is None or target_position == start:
            return

        self.viewmodel.swap_in_grid(start, target_position)
        self._render_grid()
        self.on_change()

    def _position_of(self, widget) -> Optional[Position]:
        for position, cell in self._cell_widgets.items():
            if cell is widget:
                return position
        return None
