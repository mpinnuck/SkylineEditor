"""Alt/Az table editor (REQ-25)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from models.horizon_curve import HorizonValidationError


class HorizonTableView(tk.Frame):
    def __init__(self, parent, viewmodel, on_change, on_save=None, on_import=None, on_export=None):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.on_change = on_change
        self.on_save = on_save
        self.on_import = on_import
        self.on_export = on_export

        columns = ("azimuth", "altitude")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("azimuth", text="Azimuth (deg)")
        self.tree.heading("altitude", text="Altitude (deg)")
        self.tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=4, pady=4)
        self.tree.bind("<Double-1>", self._on_double_click)

        scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scrollbar.set)

        button_col = tk.Frame(self)
        button_col.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        tk.Button(button_col, text="Add point", command=self._add_point).pack(fill=tk.X)
        tk.Button(button_col, text="Delete point", command=self._delete_point).pack(fill=tk.X, pady=(4, 0))
        tk.Button(button_col, text="Save", command=self._save).pack(fill=tk.X, pady=(10, 0))
        tk.Button(button_col, text="Import", command=self._import).pack(fill=tk.X, pady=(4, 0))
        tk.Button(button_col, text="Export", command=self._export).pack(fill=tk.X, pady=(4, 0))

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        skyline = self.viewmodel.current_skyline
        if skyline is None:
            return
        for i, point in enumerate(skyline.curve.points):
            self.tree.insert(
                "", tk.END, iid=str(i),
                values=(f"{point.azimuth_deg:.2f}", f"{point.altitude_deg:.2f}"),
            )

    def _selected_index(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _add_point(self) -> None:
        if self.viewmodel.current_skyline is None:
            return
        self.viewmodel.add_point(0.0, 0.0)
        self.refresh()
        self.on_change()

    def _delete_point(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        self.viewmodel.delete_point(index)
        self.refresh()
        self.on_change()

    def _save(self) -> None:
        if callable(self.on_save):
            self.on_save()

    def _import(self) -> None:
        if callable(self.on_import):
            self.on_import()

    def _export(self) -> None:
        if callable(self.on_export):
            self.on_export()

    def _on_double_click(self, event) -> None:
        index = self._selected_index()
        if index is None:
            return
        column = self.tree.identify_column(event.x)
        point = self.viewmodel.current_skyline.curve.points[index]

        field = "azimuth" if column == "#1" else "altitude"
        current = point.azimuth_deg if field == "azimuth" else point.altitude_deg
        new_value = simpledialog.askfloat(f"Edit {field}", f"New {field} (deg):",
                                           initialvalue=current, parent=self)
        if new_value is None:
            return

        azimuth = new_value if field == "azimuth" else point.azimuth_deg
        altitude = new_value if field == "altitude" else point.altitude_deg
        try:
            self.viewmodel.move_point(index, azimuth, altitude)
        except HorizonValidationError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        self.refresh()
        self.on_change()
