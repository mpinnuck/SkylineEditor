"""Image import + stitching panel (REQ-08, REQ-11) -- the "Image" tab's main content.

Scoped to whichever skyline is currently selected, mirroring the convention
HorizonTableView/HorizonPlotView already use. Stitching runs in a worker
thread so the Tk message pump stays responsive during long panoramas.
"""
from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from imaging.image_pool import ImagePoolError
from imaging.stitcher import StitchError

_FILETYPES = [("Images", "*.jpg *.jpeg *.png *.tif *.tiff"), ("All files", "*.*")]


class ImageStitchingView(tk.Frame):
    def __init__(self, parent, viewmodel, on_stitched=None, on_status=None):
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.on_stitched = on_stitched or (lambda: None)
        self.on_status = on_status or (lambda _message: None)
        self._preview_photo = None       # kept to stop Tk garbage-collecting it
        self._current_pil_image = None   # full-res PIL image behind the current preview
        self._source_images = []
        self._source_popup = None
        self._source_popup_label = None
        self._source_popup_photo = None
        self._source_popup_image = None
        self._stitch_result_queue: Queue = Queue()
        self._stitch_in_progress = False
        self._stitch_target_name = ""

        left = tk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)

        tk.Label(left, text="Source images").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=32, exportselection=False)
        self.listbox.pack(fill=tk.BOTH, expand=True, pady=(2, 4))
        self.listbox.bind("<<ListboxSelect>>", self._on_source_selection_changed)
        self.listbox.bind("<Double-Button-1>", self._on_source_double_click)

        button_col = tk.Frame(left)
        button_col.pack(fill=tk.X)
        self.add_button = tk.Button(button_col, text="Add Images...", command=self._add_images)
        self.add_button.pack(fill=tk.X)
        self.remove_button = tk.Button(button_col, text="Remove Selected", command=self._remove_selected)
        self.remove_button.pack(fill=tk.X, pady=(4, 0))
        self.stitch_button = tk.Button(button_col, text="Stitch", command=self._stitch)
        self.stitch_button.pack(fill=tk.X, pady=(10, 0))
        self.clear_output_button = tk.Button(
            button_col,
            text="Clear Stitched Output",
            command=self._clear_stitched_output,
        )
        self.clear_output_button.pack(fill=tk.X, pady=(4, 0))

        self.stitch_progress = ttk.Progressbar(left, mode="indeterminate")
        self.stitch_progress.pack(fill=tk.X, pady=(8, 0))

        self.status_var = tk.StringVar(value="")
        tk.Label(left, textvariable=self.status_var, wraplength=220, justify=tk.LEFT, fg="#a00").pack(
            anchor="w", pady=(8, 0)
        )

        right = tk.Frame(self)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.preview_label = tk.Label(right, text="No stitched image yet", bg="#ddd")
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        self.preview_label.bind("<Configure>", lambda _e: self._redraw_preview())

        self.refresh()

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)
        self.on_status(message)

    # -- Refresh (call on skyline selection change / tab switch) ------------------------

    def refresh(self) -> None:
        self.listbox.delete(0, tk.END)
        self._source_images = []
        skyline = self.viewmodel.current_skyline
        if skyline is None:
            self._set_status("No skyline selected.")
            self._set_preview(None)
            self._set_source_popup_image(None)
            return

        self._set_status("")
        self._source_images = self.viewmodel.list_images()
        for path in self._source_images:
            self.listbox.insert(tk.END, path.name)

        if skyline.stitched_image_file.exists():
            self._load_preview_from_file(skyline.stitched_image_file)
        else:
            self._set_preview(None)

        self._update_source_popup_image_from_selection()

    # -- Actions ------------------------------------------------------------------------

    def _add_images(self) -> None:
        if self.viewmodel.current_skyline is None:
            messagebox.showinfo("No skyline selected", "Select or create a skyline first.")
            return
        paths = filedialog.askopenfilenames(filetypes=_FILETYPES)
        if not paths:
            return
        try:
            self.viewmodel.import_images([Path(p) for p in paths])
        except ImagePoolError as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.refresh()

    def _remove_selected(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        for index in selection:
            self.viewmodel.remove_image(self._source_images[index])
        self.refresh()

    def _clear_stitched_output(self) -> None:
        if self.viewmodel.current_skyline is None:
            messagebox.showinfo("No skyline selected", "Select or create a skyline first.")
            return
        if self._stitch_in_progress:
            return

        deleted = self.viewmodel.clear_stitched_output()
        self._set_preview(None)
        if deleted:
            self._set_status("Deleted stitched output. Ready to stitch again.")
        else:
            self._set_status("No stitched output file to delete.")

    def _on_source_selection_changed(self, _event=None) -> None:
        self._update_source_popup_image_from_selection()

    def _on_source_double_click(self, _event=None) -> None:
        if self._source_popup is None or not self._source_popup.winfo_exists():
            self._open_source_popup()
        self._update_source_popup_image_from_selection()

    def _open_source_popup(self) -> None:
        popup = tk.Toplevel(self)
        popup.title("Source Image")
        popup.minsize(400, 300)

        width = min(1200, int(popup.winfo_screenwidth() * 0.8))
        height = min(900, int(popup.winfo_screenheight() * 0.8))
        x = (popup.winfo_screenwidth() - width) // 2
        y = (popup.winfo_screenheight() - height) // 2
        popup.geometry(f"{width}x{height}+{x}+{y}")

        label = tk.Label(popup, text="No source image selected", bg="#222", fg="#eee")
        label.pack(fill=tk.BOTH, expand=True)

        popup.bind("<Configure>", lambda _e: self._redraw_source_popup_image())
        popup.protocol("WM_DELETE_WINDOW", self._close_source_popup)

        self._source_popup = popup
        self._source_popup_label = label

    def _close_source_popup(self) -> None:
        if self._source_popup is not None and self._source_popup.winfo_exists():
            self._source_popup.destroy()
        self._source_popup = None
        self._source_popup_label = None
        self._source_popup_photo = None
        self._source_popup_image = None

    def _selected_source_image_path(self):
        selection = self.listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if index < 0 or index >= len(self._source_images):
            return None
        return self._source_images[index]

    def _update_source_popup_image_from_selection(self) -> None:
        if self._source_popup is None or not self._source_popup.winfo_exists():
            return

        source_path = self._selected_source_image_path()
        if source_path is None:
            self._set_source_popup_image(None)
            return

        try:
            image = Image.open(source_path)
            image.load()
        except OSError as exc:
            self._set_source_popup_image(None, f"Could not open source image: {exc}")
            return
        self._set_source_popup_image(image)

    def _set_source_popup_image(self, pil_image, fallback_text: str = "No source image selected") -> None:
        self._source_popup_image = pil_image
        if self._source_popup_label is None:
            return
        if pil_image is None:
            self._source_popup_photo = None
            self._source_popup_label.config(image="", text=fallback_text)
            return
        self._redraw_source_popup_image()

    def _redraw_source_popup_image(self) -> None:
        if self._source_popup_label is None:
            return
        if self._source_popup_image is None:
            self._source_popup_label.config(image="", text="No source image selected")
            self._source_popup_photo = None
            return

        width = max(self._source_popup_label.winfo_width(), 100)
        height = max(self._source_popup_label.winfo_height(), 100)
        thumbnail = self._source_popup_image.copy()
        thumbnail.thumbnail((width, height))
        self._source_popup_photo = ImageTk.PhotoImage(thumbnail)
        self._source_popup_label.config(image=self._source_popup_photo, text="")

    def trigger_stitch(self) -> bool:
        """Public entry point for other views (e.g. the row-adjustment tab)
        to run the same threaded stitch this view's own Stitch button uses."""
        return self._stitch()

    def _stitch(self) -> bool:
        if self.viewmodel.current_skyline is None:
            messagebox.showinfo("No skyline selected", "Select or create a skyline first.")
            return False
        if self._stitch_in_progress:
            self._set_status("Stitch already in progress...")
            return False
        if self.viewmodel.grid is None:
            messagebox.showinfo(
                "No arrangement yet",
                "Arrange the images (Arrange tab) before stitching -- "
                "stitching now uses your confirmed row order, not raw import order.",
            )
            return False

        self._stitch_target_name = self.viewmodel.current_skyline.name
        self._stitch_in_progress = True
        self.add_button.config(state=tk.DISABLED)
        self.remove_button.config(state=tk.DISABLED)
        self.listbox.config(state=tk.DISABLED)
        self.stitch_button.config(state=tk.DISABLED)
        self.clear_output_button.config(state=tk.DISABLED)
        self.stitch_progress.start(12)
        self._set_status("Stitching... this can take a while.")
        self.update_idletasks()

        worker = threading.Thread(target=self._run_stitch_worker, daemon=True)
        worker.start()
        self.after(100, self._poll_stitch_result)
        return True

    def _run_stitch_worker(self) -> None:
        try:
            result = self.viewmodel.stitch(
                on_progress=lambda message: self._stitch_result_queue.put(("progress", message))
            )
            self._stitch_result_queue.put(("ok", result))
        except Exception as exc:
            self._stitch_result_queue.put(("error", exc))

    def _poll_stitch_result(self) -> None:
        try:
            outcome, payload = self._stitch_result_queue.get_nowait()
        except Empty:
            if self.winfo_exists():
                self.after(100, self._poll_stitch_result)
            return

        if outcome == "progress":
            self._set_status(payload)
            if self.winfo_exists():
                self.after(100, self._poll_stitch_result)
            return

        self._stitch_in_progress = False
        self.stitch_progress.stop()
        self.add_button.config(state=tk.NORMAL)
        self.remove_button.config(state=tk.NORMAL)
        self.listbox.config(state=tk.NORMAL)
        self.stitch_button.config(state=tk.NORMAL)
        self.clear_output_button.config(state=tk.NORMAL)

        if outcome == "error":
            err = payload
            self._set_status(str(err))
            title = "Stitching failed" if isinstance(err, StitchError) else "Stitching error"
            messagebox.showerror(title, str(err))
            return

        result = payload
        row_summary = ", ".join(f"row {r.row_index}: {r.image_count}" for r in result.row_results)
        self._set_status(f"Stitched {result.image_count} image(s) successfully ({row_summary}).")
        self.on_stitched()

        skyline = self.viewmodel.current_skyline
        if skyline is None:
            return
        if skyline.name != self._stitch_target_name:
            self._set_status(
                f"Stitched images for '{self._stitch_target_name}'. Re-select that skyline to view its preview."
            )
            return
        self._load_preview_from_file(skyline.stitched_image_file)

    # -- Preview rendering ----------------------------------------------------------------

    def _load_preview_from_file(self, path: Path) -> None:
        try:
            image = Image.open(path)
            image.load()
        except OSError as exc:
            self._set_status(f"Could not preview stitched image: {exc}")
            self._set_preview(None)
            return
        self._set_preview(image)

    def _set_preview(self, pil_image) -> None:
        self._current_pil_image = pil_image
        self._redraw_preview()

    def _redraw_preview(self) -> None:
        if self._current_pil_image is None:
            self.preview_label.config(image="", text="No stitched image yet")
            self._preview_photo = None
            return

        width = max(self.preview_label.winfo_width(), 100)
        height = max(self.preview_label.winfo_height(), 100)
        thumbnail = self._current_pil_image.copy()
        thumbnail.thumbnail((width, height))
        self._preview_photo = ImageTk.PhotoImage(thumbnail)
        self.preview_label.config(image=self._preview_photo, text="")
