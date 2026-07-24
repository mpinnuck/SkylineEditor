"""Import options dialog: delimiter, column order, header row (REQ-01)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional


class ImportOptionsDialog(tk.Toplevel):
    """Modal dialog letting the user override auto-detected delimiter/column
    order/header row, or leave everything on Auto-detect (REQ-01)."""

    @classmethod
    def ask(cls, parent) -> Optional[dict]:
        dialog = cls(parent)
        parent.wait_window(dialog)
        return dialog.result

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Import options")
        self.result: Optional[dict] = None
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.delimiter_var = tk.StringVar(value="auto")
        self.order_var = tk.StringVar(value="az_alt")
        self.header_var = tk.StringVar(value="auto")

        frame = ttk.Frame(self, padding=12)
        frame.pack()

        ttk.Label(frame, text="Delimiter:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Combobox(frame, textvariable=self.delimiter_var, state="readonly",
                     values=["auto", "comma", "tab", "whitespace"], width=14).grid(row=0, column=1)

        ttk.Label(frame, text="Column order:").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Combobox(frame, textvariable=self.order_var, state="readonly",
                     values=["az_alt", "alt_az"], width=14).grid(row=1, column=1)

        ttk.Label(frame, text="Header row:").grid(row=2, column=0, sticky="w", pady=2)
        ttk.Combobox(frame, textvariable=self.header_var, state="readonly",
                     values=["auto", "yes", "no"], width=14).grid(row=2, column=1)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(button_row, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=4)
        ttk.Button(button_row, text="Import", command=self._ok).pack(side=tk.LEFT, padx=4)

    def _ok(self) -> None:
        delimiter_map = {"auto": None, "comma": ",", "tab": "\t", "whitespace": "whitespace"}
        header_map = {"auto": None, "yes": True, "no": False}
        self.result = {
            "delimiter": delimiter_map[self.delimiter_var.get()],
            "column_order": self.order_var.get(),
            "has_header": header_map[self.header_var.get()],
        }
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
