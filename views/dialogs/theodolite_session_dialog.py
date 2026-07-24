"""Session/date picker for Theodolite exports (REQ-31/REQ-36).

A log file may contain multiple capture sessions concatenated together, so
the user selects which one to import rather than blending all rows together.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List, Optional


class TheodoliteSessionDialog(tk.Toplevel):
    @classmethod
    def ask(cls, parent, sessions: List[str]) -> Optional[str]:
        dialog = cls(parent, sessions)
        parent.wait_window(dialog)
        return dialog.result

    def __init__(self, parent, sessions: List[str]):
        super().__init__(parent)
        self.title("Select Theodolite session")
        self.result: Optional[str] = None
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ttk.Frame(self, padding=12)
        frame.pack()
        ttk.Label(frame, text="This file contains multiple sessions. Choose one:").pack(anchor="w")

        self.listbox = tk.Listbox(frame, height=min(10, len(sessions)), exportselection=False)
        for session in sessions:
            self.listbox.insert(tk.END, session)
        self.listbox.selection_set(0)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

        button_row = ttk.Frame(frame)
        button_row.pack()
        ttk.Button(button_row, text="Cancel", command=self._cancel).pack(side=tk.LEFT, padx=4)
        ttk.Button(button_row, text="Import", command=self._ok).pack(side=tk.LEFT, padx=4)

    def _ok(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            self.result = self.listbox.get(selection[0])
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()
