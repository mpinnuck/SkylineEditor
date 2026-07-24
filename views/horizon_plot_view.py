"""Interactive Alt/Az plot.

REQ-24: plot centered on North or South depending on config.
REQ-26: add/move/delete points directly on the plot (click/drag), not just
via the table.
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from models.horizon_curve import HorizonValidationError  # noqa: E402
from models.horizon_point import HorizonPoint  # noqa: E402


class HorizonPlotView(tk.Frame):
    def __init__(self, parent, viewmodel, on_change):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.on_change = on_change
        self._dragging_point: Optional[HorizonPoint] = None
        self._drag_start = (0.0, 0.0)

        self.figure = Figure(figsize=(6, 3))
        self.ax = self.figure.add_subplot(111)
        self.figure.subplots_adjust(left=0.10, right=0.98, top=0.95, bottom=0.18)
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)

        self.refresh()

    def refresh(self) -> None:
        self.ax.clear()
        skyline = self.viewmodel.current_skyline
        center_on = "S" if str(self.viewmodel.config.center_on).strip().upper().startswith("S") else "N"

        self.ax.set_xlim(-180, 180)
        if center_on == "S":
            tick_labels = {-180: "N", -90: "E", 0: "S", 90: "W", 180: "N"}
        else:
            tick_labels = {-180: "S", -90: "W", 0: "N", 90: "E", 180: "S"}
        self.ax.set_xticks(list(tick_labels.keys()))
        self.ax.set_xticklabels(list(tick_labels.values()))
        self.ax.set_xlabel("Azimuth")
        self.ax.set_ylabel("Altitude (deg)")
        self.ax.grid(True, alpha=0.3)

        if skyline is not None and skyline.curve.points:
            points = sorted(skyline.curve.points, key=lambda p: p.normalized_azimuth())
            azimuths = [self._display_azimuth(p.azimuth_deg, center_on) for p in points]
            altitudes = [p.altitude_deg for p in points]
            order = sorted(range(len(azimuths)), key=lambda i: azimuths[i])
            azimuths = [azimuths[i] for i in order]
            altitudes = [altitudes[i] for i in order]
            self.ax.plot(azimuths, altitudes, "o-")

        self.figure.subplots_adjust(left=0.10, right=0.98, top=0.95, bottom=0.18)
        self.canvas.draw_idle()

    @staticmethod
    def _display_azimuth(azimuth_deg: float, center_on: str) -> float:
        az = azimuth_deg % 360.0
        if center_on == "S":
            return ((az - 180.0 + 180.0) % 360.0) - 180.0
        return ((az + 180.0) % 360.0) - 180.0

    @staticmethod
    def _model_azimuth(display_azimuth: float, center_on: str) -> float:
        if center_on == "S":
            return (display_azimuth + 180.0) % 360.0
        return (display_azimuth + 360.0) % 360.0

    def _nearest_point(self, event) -> Optional[HorizonPoint]:
        skyline = self.viewmodel.current_skyline
        if skyline is None or event.xdata is None:
            return None
        center_on = "S" if str(self.viewmodel.config.center_on).strip().upper().startswith("S") else "N"
        best_point, best_dist = None, None
        for point in skyline.curve.points:
            dx = self._display_azimuth(point.azimuth_deg, center_on) - event.xdata
            dy = point.altitude_deg - (event.ydata or 0.0)
            dist = dx * dx + dy * dy
            if best_dist is None or dist < best_dist:
                best_point, best_dist = point, dist
        return best_point

    def _on_press(self, event) -> None:
        if self.viewmodel.current_skyline is None or event.xdata is None:
            return
        center_on = "S" if str(self.viewmodel.config.center_on).strip().upper().startswith("S") else "N"

        if event.dblclick:
            azimuth = self._model_azimuth(event.xdata, center_on)
            self.viewmodel.add_point(azimuth, event.ydata or 0.0)
            self.refresh()
            self.on_change()
            return

        if event.button == 3:  # right-click: delete nearest point
            point = self._nearest_point(event)
            if point is not None:
                self.viewmodel.delete_point_object(point)
                self.refresh()
                self.on_change()
            return

        self._dragging_point = self._nearest_point(event)
        if self._dragging_point is not None:
            self._drag_start = (self._dragging_point.azimuth_deg, self._dragging_point.altitude_deg)

    def _on_motion(self, event) -> None:
        if self._dragging_point is None or event.xdata is None:
            return
        center_on = "S" if str(self.viewmodel.config.center_on).strip().upper().startswith("S") else "N"
        azimuth = self._model_azimuth(event.xdata, center_on)
        try:
            self.viewmodel.preview_move_point(self._dragging_point, azimuth, event.ydata or 0.0)
        except HorizonValidationError:
            return
        self.refresh()

    def _on_release(self, _event) -> None:
        if self._dragging_point is not None:
            self.viewmodel.commit_drag(self._dragging_point, *self._drag_start)
            self.on_change()
        self._dragging_point = None
