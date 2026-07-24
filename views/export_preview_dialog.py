"""Popup preview dialog for exported Stellarium .hrz files."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from fileio import hrz_importer
from fileio.errors import ImportFileError
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


class ExportPreviewDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, hrz_path: Path):
        super().__init__(parent)
        self.title(f"Export Preview - {hrz_path.name}")
        self.geometry("760x360")
        self._center_on_screen(760, 360)

        try:
            points, result, _comments = hrz_importer.import_hrz_file(hrz_path)
        except ImportFileError as exc:
            ttk.Label(self, text=f"Could not preview exported file:\n{exc}").pack(
                fill=tk.BOTH, expand=True, padx=12, pady=12
            )
            ttk.Button(self, text="Close", command=self.destroy).pack(pady=(0, 10))
            return

        figure = Figure(figsize=(7.5, 3.0))
        ax = figure.add_subplot(111)
        figure.subplots_adjust(left=0.10, right=0.98, top=0.90, bottom=0.20)

        sorted_points = sorted(points, key=lambda p: p.normalized_azimuth())
        azimuths = [p.azimuth_deg for p in sorted_points]
        altitudes = [p.altitude_deg for p in sorted_points]
        ax.plot(azimuths, altitudes, "o-", linewidth=1.5, markersize=3)
        ax.set_xlim(0, 360)
        ax.set_xlabel("Azimuth (deg)")
        ax.set_ylabel("Altitude (deg)")
        ax.set_title("Exported .hrz Sampled Curve")
        ax.grid(True, alpha=0.3)

        canvas = FigureCanvasTkAgg(figure, master=self)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        footer = ttk.Frame(self)
        footer.pack(fill=tk.X, padx=8, pady=(0, 8))
        warning_suffix = f" | warnings: {len(result.warnings)}" if result.warnings else ""
        ttk.Label(footer, text=f"{hrz_path}{warning_suffix}").pack(side=tk.LEFT)
        ttk.Button(footer, text="Close", command=self.destroy).pack(side=tk.RIGHT)

    def _center_on_screen(self, width: int, height: int) -> None:
        self.update_idletasks()
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")
