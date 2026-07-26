"""Main application window: overall layout shell and menu.

REQ-28: centered on the desktop at startup.
REQ-30: GUI-only (Tkinter); no CLI/headless mode.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import filedialog, messagebox, ttk

from config import AppConfig, save_config
from fileio.errors import ImportFileError
from models.horizon_curve import HorizonValidationError
from viewmodels.image_stitching_viewmodel import ImageStitchingViewModel
from viewmodels.main_viewmodel import MainViewModel
from views.dialogs.import_dialog import ImportOptionsDialog
from views.dialogs.theodolite_session_dialog import TheodoliteSessionDialog
from views.horizon_plot_view import HorizonPlotView
from views.horizon_table_view import HorizonTableView
from views.image_arrangement_view import ImageArrangementView
from views.image_stitching_view import ImageStitchingView
from views.row_adjust_view import RowAdjustView
from views.skyline_list_view import SkylineListView


class MainWindow(tk.Tk):
    def __init__(self, config: AppConfig, version: str = "dev"):
        super().__init__()
        self.app_config = config
        self.version = version
        self.viewmodel = MainViewModel(config)
        self._center_on_var = tk.StringVar(value=self.app_config.center_on)
        self.status_var = tk.StringVar(value="")

        self.title("SkylineEditor")
        self._build_layout()
        self._build_menu()
        self._build_version_label()
        self._restore_last_state()
        self._center_on_screen()  # REQ-28
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- Layout ------------------------------------------------------------------------

    def _build_layout(self) -> None:
        self.geometry(f"{self.app_config.window_width}x{self.app_config.window_height}")

        outer = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=4)
        outer.pack(fill=tk.BOTH, expand=True)

        # The skyline list is a single, persistent widget shared across every
        # tab -- not duplicated per tab -- so selection can never fall out of
        # sync between tabs (REQ-22).
        self.skyline_list = SkylineListView(outer, self.viewmodel, on_select=self._on_skyline_selected)
        outer.add(self.skyline_list, minsize=180, width=200)

        self.tabs = ttk.Notebook(outer)
        outer.add(self.tabs, minsize=500)

        skyline_tab = ttk.Frame(self.tabs)
        image_tab = ttk.Frame(self.tabs)
        config_tab = ttk.Frame(self.tabs)
        self.tabs.add(skyline_tab, text="Skyline")
        self.tabs.add(image_tab, text="Image")
        self.tabs.add(config_tab, text="Config")
        self._image_tab = image_tab

        self._build_skyline_tab(skyline_tab)
        self._build_image_tab(image_tab)
        self._build_config_tab(config_tab)

        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            anchor="w",
            relief=tk.SUNKEN,
            padx=8,
            pady=3,
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _build_version_label(self) -> None:
        small_font = tkfont.nametofont("TkDefaultFont").copy()
        small_font.configure(size=max(7, small_font.cget("size") - 2))
        self._version_label = tk.Label(self, text=f"v{self.version}", font=small_font, fg="#666")
        self._version_label.place(relx=1.0, x=-10, y=8, anchor="ne")

    def _build_skyline_tab(self, parent: tk.Widget) -> None:
        right = tk.PanedWindow(parent, orient=tk.VERTICAL, sashwidth=4)
        right.pack(fill=tk.BOTH, expand=True)

        self.plot_view = HorizonPlotView(right, self.viewmodel, on_change=self._on_edit)
        right.add(self.plot_view, minsize=250, height=350)

        self.table_view = HorizonTableView(
            right,
            self.viewmodel,
            on_change=self._on_edit,
            on_save=self._save,
            on_import=self._import_alt_az,
            on_export=self._export_hrz,
        )
        right.add(self.table_view, minsize=150, height=250)

    def _build_image_tab(self, parent: tk.Widget) -> None:
        """REQ-08/REQ-11: image import + stitching, scoped to whichever
        skyline is selected in the shared list on the left."""
        self.image_viewmodel = ImageStitchingViewModel(self.viewmodel)

        sub_tabs = ttk.Notebook(parent)
        sub_tabs.pack(fill=tk.BOTH, expand=True)
        self._image_sub_tabs = sub_tabs

        import_tab = ttk.Frame(sub_tabs)
        arrange_tab = ttk.Frame(sub_tabs)
        adjust_tab = ttk.Frame(sub_tabs)
        sub_tabs.add(import_tab, text="Import")
        sub_tabs.add(arrange_tab, text="Arrange")
        sub_tabs.add(adjust_tab, text="Adjust")
        self._image_import_tab = import_tab

        self.image_view = ImageStitchingView(
            import_tab,
            self.image_viewmodel,
            on_stitched=self._on_row_stitch_complete,
            on_status=self._set_status,
        )
        self.image_view.pack(fill=tk.BOTH, expand=True)

        self.image_arrangement_view = ImageArrangementView(arrange_tab, self.image_viewmodel)
        self.image_arrangement_view.pack(fill=tk.BOTH, expand=True)

        self.row_adjust_view = RowAdjustView(
            adjust_tab, self.image_viewmodel, on_restitch_requested=self._restitch_from_adjust
        )
        self.row_adjust_view.pack(fill=tk.BOTH, expand=True)

    def _restitch_from_adjust(self) -> bool:
        """When Re-stitch is clicked in Adjust, bring the user to Import
        so the stitch progress/status is immediately visible, then start."""
        self.tabs.select(self._image_tab)
        self._image_sub_tabs.select(self._image_import_tab)
        return self.image_view.trigger_stitch()

    def _on_row_stitch_complete(self) -> None:
        """A stitch just finished (from any trigger point) -- refresh the
        row-position adjustment view so it reflects the new result."""
        self.row_adjust_view.refresh()

    def _build_config_tab(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)

        self._cfg_root_var = tk.StringVar(value=self.app_config.root_folder)
        self._cfg_last_dir_var = tk.StringVar(value=self.app_config.last_used_directory)
        self._cfg_center_var = tk.StringVar(value=self.app_config.center_on)

        ttk.Label(parent, text="Root folder").grid(row=0, column=0, sticky="w", padx=10, pady=(12, 6))
        ttk.Entry(parent, textvariable=self._cfg_root_var).grid(row=0, column=1, sticky="ew", padx=10, pady=(12, 6))
        ttk.Button(parent, text="Browse...", command=self._browse_root_folder_config).grid(
            row=0, column=2, sticky="ew", padx=(0, 10), pady=(12, 6)
        )

        ttk.Label(parent, text="Last used directory").grid(row=1, column=0, sticky="w", padx=10, pady=6)
        ttk.Entry(parent, textvariable=self._cfg_last_dir_var).grid(row=1, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(parent, text="Browse...", command=self._browse_last_used_directory).grid(
            row=1, column=2, sticky="ew", padx=(0, 10), pady=6
        )

        ttk.Label(parent, text="Plot center").grid(row=2, column=0, sticky="w", padx=10, pady=6)
        center_row = ttk.Frame(parent)
        center_row.grid(row=2, column=1, columnspan=2, sticky="w", padx=10, pady=6)
        ttk.Radiobutton(center_row, text="North", variable=self._cfg_center_var, value="N").pack(side=tk.LEFT)
        ttk.Radiobutton(center_row, text="South", variable=self._cfg_center_var, value="S").pack(side=tk.LEFT, padx=(10, 0))

        actions = ttk.Frame(parent)
        actions.grid(row=3, column=0, columnspan=3, sticky="w", padx=10, pady=(12, 10))
        ttk.Button(actions, text="Apply", command=self._apply_config_from_tab).pack(side=tk.LEFT)
        ttk.Button(actions, text="Reset", command=self._reset_config_tab).pack(side=tk.LEFT, padx=(8, 0))

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Import Alt/Az file...", command=self._import_alt_az)
        file_menu.add_command(label="Import Stellarium .hrz...", command=self._import_hrz)
        file_menu.add_command(label="Import Theodolite session...", command=self._import_theodolite)
        file_menu.add_separator()
        file_menu.add_command(label="Save", command=self._save, accelerator="Ctrl/Cmd+S")
        file_menu.add_command(label="Save As...", command=self._save_as)
        file_menu.add_command(label="Export .hrz...", command=self._export_hrz)
        file_menu.add_separator()
        file_menu.add_command(label="Set root folder...", command=self._set_root_folder)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menubar, tearoff=False)
        edit_menu.add_command(label="Undo", command=self._undo, accelerator="Ctrl/Cmd+Z")
        edit_menu.add_command(label="Redo", command=self._redo, accelerator="Ctrl/Cmd+Shift+Z")
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_radiobutton(label="Center on North", variable=self._center_on_var,
                                   value="N", command=self._on_center_changed)
        view_menu.add_radiobutton(label="Center on South", variable=self._center_on_var,
                                   value="S", command=self._on_center_changed)
        menubar.add_cascade(label="View", menu=view_menu)

        self.config(menu=menubar)
        for seq in ("<Command-z>", "<Control-z>"):
            self.bind_all(seq, lambda _e: self._undo())
        for seq in ("<Command-s>", "<Control-s>"):
            self.bind_all(seq, lambda _e: self._save())

    def _center_on_screen(self) -> None:
        self.update_idletasks()
        width, height = self.app_config.window_width, self.app_config.window_height
        x = (self.winfo_screenwidth() - width) // 2
        y = (self.winfo_screenheight() - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    # -- Skyline selection ---------------------------------------------------------------

    def _on_skyline_selected(self, skyline) -> None:
        self.viewmodel.select_skyline(skyline)
        self.app_config.current_skyline_name = skyline.name
        save_config(self.app_config)
        error = self.viewmodel.load_selected_skyline_state()
        if error:
            messagebox.showwarning("Load warning", error)
        self.image_viewmodel.on_skyline_changed()
        self.image_view.refresh()
        self.image_arrangement_view.refresh()
        self.row_adjust_view.refresh()
        self._refresh_all()

    def _update_title(self) -> None:
        skyline = self.viewmodel.current_skyline
        if skyline is None:
            self.title("SkylineEditor")
            return
        star = "*" if skyline.dirty else ""
        self.title(f"SkylineEditor -- {skyline.name}{star}")

    def _refresh_all(self) -> None:
        self.table_view.refresh()
        self.plot_view.refresh()
        self._update_title()

    def _set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _on_edit(self) -> None:
        # Called by the plot/table views after an edit that originated on the
        # *other* view, so both stay in sync without re-triggering each other.
        self.table_view.refresh()
        self.plot_view.refresh()
        self.viewmodel.save_selected_skyline_state()
        self._update_title()

    # -- Import ------------------------------------------------------------------------

    def _import_alt_az(self) -> None:
        if not self._require_skyline():
            return
        path = filedialog.askopenfilename(
            initialdir=self.app_config.last_used_directory,
            filetypes=[("CSV/text", "*.csv *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        selected_path = Path(path)
        if self._maybe_import_as_theodolite(selected_path):
            return
        self.app_config.last_used_directory = str(Path(path).parent)
        options = ImportOptionsDialog.ask(self)
        if options is None:
            return
        try:
            result = self.viewmodel.import_alt_az(selected_path, **options)
        except (ImportFileError, HorizonValidationError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.viewmodel.save_selected_skyline_state(last_import_file=selected_path)
        self._report_import_warnings(result)
        self._refresh_all()

    def _import_hrz(self) -> None:
        if not self._require_skyline():
            return
        path = filedialog.askopenfilename(
            initialdir=self.app_config.last_used_directory, filetypes=[("Stellarium .hrz", "*.hrz")]
        )
        if not path:
            return
        try:
            result = self.viewmodel.import_hrz(Path(path))
        except (ImportFileError, HorizonValidationError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.viewmodel.save_selected_skyline_state(last_import_file=Path(path))
        self._report_import_warnings(result)
        self._refresh_all()

    def _import_theodolite(self) -> None:
        """REQ-36: Theodolite-only workflow, independent of the imaging pipeline."""
        if not self._require_skyline():
            return
        path = filedialog.askopenfilename(
            initialdir=self.app_config.last_used_directory,
            filetypes=[("Theodolite export", "*.csv *.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        self._import_theodolite_from_path(Path(path))

    def _import_theodolite_from_path(self, path: Path) -> None:
        try:
            sessions = self.viewmodel.list_theodolite_sessions(path)
        except ImportFileError as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        session = TheodoliteSessionDialog.ask(self, sessions)
        if session is None:
            return
        try:
            result = self.viewmodel.import_theodolite(path, session)
        except (ImportFileError, HorizonValidationError) as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        self.viewmodel.save_selected_skyline_state(last_import_file=path)
        self._report_import_warnings(result)
        self._refresh_all()

    def _maybe_import_as_theodolite(self, path: Path) -> bool:
        """Silently redirect to the dedicated Theodolite workflow when a
        Theodolite export was picked under generic Alt/Az import -- the
        generic importer can't parse a 14-column Theodolite file as
        2-column Alt/Az data, so this avoids that failure entirely rather
        than asking first."""
        from fileio import theodolite_importer

        if not theodolite_importer.is_theodolite_export(path):
            return False
        self._import_theodolite_from_path(path)
        return True

    def _report_import_warnings(self, result) -> None:
        if not result.warnings:
            return
        lines = "\n".join(str(w) for w in result.warnings[:20])
        more = "" if len(result.warnings) <= 20 else f"\n...and {len(result.warnings) - 20} more."
        messagebox.showwarning("Import completed with warnings", f"{lines}{more}")

    # -- Save / Export -------------------------------------------------------------------

    def _save(self) -> None:
        if not self._require_skyline():
            return
        try:
            self.viewmodel.save()
        except HorizonValidationError as exc:
            messagebox.showerror("Cannot save", str(exc))
            return
        self.viewmodel.save_selected_skyline_state()
        self._update_title()

    def _save_as(self) -> None:
        if not self._require_skyline():
            return
        path = filedialog.asksaveasfilename(
            initialdir=self.app_config.last_used_directory,
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Text", "*.txt"), ("Stellarium .hrz", "*.hrz")],
        )
        if not path:
            return
        self.app_config.last_used_directory = str(Path(path).parent)
        try:
            self.viewmodel.save_as(Path(path))
        except HorizonValidationError as exc:
            messagebox.showerror("Cannot save", str(exc))
            return
        self.viewmodel.save_selected_skyline_state()
        self._update_title()

    def _export_hrz(self) -> None:
        if not self._require_skyline():
            return
        skyline = self.viewmodel.current_skyline
        if skyline is None:
            return

        base_name = skyline.name
        if base_name.lower().endswith(".hrz"):
            base_name = base_name[:-4]
        export_path = skyline.folder / f"{base_name}.hrz"

        try:
            self.viewmodel.export_hrz(export_path)
        except HorizonValidationError as exc:
            self._set_status(f"Export failed: {exc}")
            messagebox.showerror("Cannot export", str(exc))
            return
        self.app_config.last_used_directory = str(export_path.parent)
        self._set_status(f"Exported .hrz to {export_path}")

    def _set_root_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.app_config.root_folder)
        if not folder:
            return
        self.viewmodel.set_root_folder(Path(folder))
        self.app_config.current_skyline_name = ""
        self._cfg_root_var.set(self.app_config.root_folder)
        self.skyline_list.refresh()
        self.image_viewmodel.on_skyline_changed()
        self.image_view.refresh()
        self.image_arrangement_view.refresh()
        self.row_adjust_view.refresh()
        self._refresh_all()

    def _restore_last_state(self) -> None:
        name = self.app_config.current_skyline_name.strip()
        if name:
            restored = self.skyline_list.select_by_name(name)
            if not restored:
                self.app_config.current_skyline_name = ""
                save_config(self.app_config)

    def _browse_root_folder_config(self) -> None:
        folder = filedialog.askdirectory(initialdir=self._cfg_root_var.get() or self.app_config.root_folder)
        if folder:
            self._cfg_root_var.set(folder)

    def _browse_last_used_directory(self) -> None:
        folder = filedialog.askdirectory(initialdir=self._cfg_last_dir_var.get() or self.app_config.last_used_directory)
        if folder:
            self._cfg_last_dir_var.set(folder)

    def _apply_config_from_tab(self) -> None:
        root_folder = self._cfg_root_var.get().strip()
        last_dir = self._cfg_last_dir_var.get().strip()
        center_on = self._cfg_center_var.get().strip().upper()

        if not root_folder:
            messagebox.showerror("Invalid config", "Root folder is required.")
            return
        if center_on not in ("N", "S"):
            messagebox.showerror("Invalid config", "Plot center must be N or S.")
            return
        current_root = Path(self.app_config.root_folder)
        new_root = Path(root_folder)
        if new_root != current_root:
            self.viewmodel.set_root_folder(new_root)
            self.app_config.current_skyline_name = ""
            self.skyline_list.refresh()
            self.image_viewmodel.on_skyline_changed()
            self.image_view.refresh()
            self.image_arrangement_view.refresh()
            self.row_adjust_view.refresh()
            self._refresh_all()

        self.app_config.last_used_directory = last_dir or str(Path.home())
        self.app_config.center_on = center_on
        self._center_on_var.set(center_on)
        save_config(self.app_config)
        self.plot_view.refresh()
        messagebox.showinfo("Config saved", "Configuration updated.")

    def _reset_config_tab(self) -> None:
        self._cfg_root_var.set(self.app_config.root_folder)
        self._cfg_last_dir_var.set(self.app_config.last_used_directory)
        self._cfg_center_var.set(self.app_config.center_on)

    # -- Undo/redo, view options, shutdown -------------------------------------------------

    def _undo(self) -> None:
        if self.viewmodel.undo():
            self.viewmodel.save_selected_skyline_state()
            self._refresh_all()

    def _redo(self) -> None:
        if self.viewmodel.redo():
            self.viewmodel.save_selected_skyline_state()
            self._refresh_all()

    def _on_center_changed(self) -> None:
        self.app_config.center_on = self._center_on_var.get()
        self._cfg_center_var.set(self.app_config.center_on)
        self.plot_view.refresh()

    def _require_skyline(self) -> bool:
        if self.viewmodel.current_skyline is None:
            messagebox.showinfo("No skyline selected", "Select or create a skyline first.")
            return False
        return True

    def _on_close(self) -> None:
        skyline = self.viewmodel.current_skyline
        if skyline is not None and skyline.dirty:
            if not messagebox.askyesno("Unsaved changes", "Discard unsaved changes and quit?"):
                return
        self.app_config.window_width = self.winfo_width()
        self.app_config.window_height = self.winfo_height()
        if self.viewmodel.current_skyline is not None:
            self.viewmodel.save_selected_skyline_state()
        save_config(self.app_config)
        self.destroy()
