"""Left-hand skyline list panel (REQ-22): add/remove/rename skylines (REQ-23)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog

from models.skyline_registry import SkylineNameError


class SkylineListView(tk.Frame):
    def __init__(self, parent, viewmodel, on_select):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.on_select = on_select

        self.listbox = tk.Listbox(self, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.listbox.bind("<<ListboxSelect>>", self._on_listbox_select)

        button_row = tk.Frame(self)
        button_row.pack(fill=tk.X, padx=4, pady=(0, 4))
        tk.Button(button_row, text="Add", command=self._add).pack(side=tk.LEFT)
        tk.Button(button_row, text="Rename", command=self._rename).pack(side=tk.LEFT)
        tk.Button(button_row, text="Remove", command=self._remove).pack(side=tk.LEFT)

        self.refresh()

    def refresh(self) -> None:
        self.listbox.delete(0, tk.END)
        for skyline in self.viewmodel.registry.skylines:
            self.listbox.insert(tk.END, skyline.name)

    def select_by_name(self, name: str) -> bool:
        for idx, skyline in enumerate(self.viewmodel.registry.skylines):
            if skyline.name == name:
                self.listbox.selection_clear(0, tk.END)
                self.listbox.selection_set(idx)
                self.listbox.activate(idx)
                self.listbox.see(idx)
                self.on_select(skyline)
                return True
        return False

    def _selected_skyline(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self.viewmodel.registry.skylines[selection[0]]

    def _on_listbox_select(self, _event) -> None:
        skyline = self._selected_skyline()
        if skyline is not None:
            self.on_select(skyline)

    def _add(self) -> None:
        name = simpledialog.askstring("Add skyline", "Skyline name:", parent=self)
        if not name:
            return
        try:
            self.viewmodel.add_skyline(name)
        except SkylineNameError as exc:
            messagebox.showerror("Cannot add skyline", str(exc))
            return
        self.refresh()

    def _rename(self) -> None:
        skyline = self._selected_skyline()
        if skyline is None:
            return
        new_name = simpledialog.askstring(
            "Rename skyline", "New name:", initialvalue=skyline.name, parent=self
        )
        if not new_name or new_name == skyline.name:
            return
        try:
            self.viewmodel.rename_skyline(skyline, new_name)
        except SkylineNameError as exc:
            messagebox.showerror("Cannot rename skyline", str(exc))
            return
        self.refresh()

    def _remove(self) -> None:
        skyline = self._selected_skyline()
        if skyline is None:
            return
        if not messagebox.askyesno(
            "Remove skyline",
            f"Remove '{skyline.name}' from the list?\n(Its folder on disk will not be deleted.)",
        ):
            return
        self.viewmodel.remove_skyline(skyline, delete_folder=False)
        self.refresh()
