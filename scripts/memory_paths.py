"""Shared data root for the bundled, offline memory commands."""
import os
from pathlib import Path
import runpy
import sys


def default_data():
    configured = os.environ.get("WATCH_AND_DO_DATA")
    if configured:
        return Path(configured).expanduser()
    config = Path.home() / ".config" / "watch-and-do" / "data-root.txt"
    if config.is_file():
        root = Path(config.read_text(encoding="utf-8-sig").strip()).expanduser()
        if not root.is_absolute():
            raise ValueError(f"Expected an absolute personal data directory in {config}")
        return root
    base = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "watch-and-do"


if __name__ == "__main__":
    # Launch the existing optional runtime with the same per-user storage default.
    # Keep its script arguments and sibling module lookup identical to direct execution.
    entry = Path(sys.argv.pop(1)).resolve()
    os.environ.setdefault("WATCH_AND_DO_DATA", str(default_data()))
    sys.argv[0] = str(entry)
    sys.path[0] = str(entry.parent)
    runpy.run_path(str(entry), run_name="__main__")
