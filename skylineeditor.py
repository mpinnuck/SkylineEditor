#!/usr/bin/env python3
"""SkylineEditor -- entry point.

A horizon-curve editor for astrophotography site planning: edit an Alt/Az
horizon profile by hand, table, Alt/Az file, Stellarium .hrz, or a Theodolite
app export, and export a Stellarium-compatible .hrz for use in Stellarium and
in the TonightSky shoot-time calculator.
"""
from __future__ import annotations

from config import load_config
from views.main_window import MainWindow

VERSION = "0.1.0"


def main() -> None:
    config = load_config()
    app = MainWindow(config, VERSION)
    app.mainloop()


if __name__ == "__main__":
    main()
