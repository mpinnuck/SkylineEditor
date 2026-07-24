"""Application configuration: JSON-backed load/save (REQ-29).

Persists UI preferences -- N/S plot centering, last-used directory, and the
configurable skyline root folder (REQ-19) -- across launches, via the
standard load_config()/save_config() pattern rather than scattered
reads/writes.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "SkylineEditor"
LEGACY_CONFIG_PATH = Path.home() / ".skylineeditor" / "config.json"


def get_config_path() -> Path:
    """Return the per-user OS config path for the app.

    macOS: ~/Library/Application Support/SkylineEditor/config.json
    Windows: %APPDATA%/SkylineEditor/config.json
    Linux/Unix: $XDG_CONFIG_HOME/SkylineEditor/config.json or ~/.config/... 
    """
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support"
    elif os.name == "nt":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
    else:
        xdg = os.getenv("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else home / ".config"
    return base / APP_NAME / "config.json"


DEFAULT_CONFIG_PATH = get_config_path()
DEFAULT_ROOT_FOLDER = Path.home() / "SkylineEditor" / "Skylines"


@dataclass
class AppConfig:
    root_folder: str = str(DEFAULT_ROOT_FOLDER)
    last_used_directory: str = str(Path.home())
    center_on: str = "N"  # "N" or "S" -- REQ-24
    current_skyline_name: str = ""
    window_width: int = 1100
    window_height: int = 700

    def __post_init__(self) -> None:
        self.center_on = _normalize_center_on(self.center_on)


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    """Load AppConfig from `path`, falling back to defaults if the file is
    missing, unreadable, or corrupt. Unknown keys in the file are ignored so
    older config files remain loadable after new fields are added."""
    candidate_paths = [path]
    # Backward compatibility for older installs that wrote config under
    # ~/.skylineeditor/config.json.
    if path == DEFAULT_CONFIG_PATH and LEGACY_CONFIG_PATH not in candidate_paths:
        candidate_paths.append(LEGACY_CONFIG_PATH)

    data = None
    for candidate in candidate_paths:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            break
        except (json.JSONDecodeError, OSError):
            continue

    if data is None:
        return AppConfig()

    known_fields = set(AppConfig.__dataclass_fields__.keys())
    filtered = {k: v for k, v in data.items() if k in known_fields}
    try:
        return AppConfig(**filtered)
    except TypeError:
        return AppConfig()


def save_config(config: AppConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")


def _normalize_center_on(value: str) -> str:
    text = (value or "").strip().upper()
    if text in {"S", "SOUTH"}:
        return "S"
    return "N"
