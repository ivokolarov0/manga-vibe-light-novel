"""Test setup for this plugin: runs the MangaVibe app with the plugin installed, like a real install.

The app is found next to this repo (../manga-vibe), or wherever MANGAVIBE_DIR points. Run the tests
with the app's Python, which has its packages:

    ..\\manga-vibe\\.venv\\Scripts\\python -m pytest        (Windows)
    ../manga-vibe/.venv/bin/python -m pytest              (Linux/macOS)

It uses the app's own test setup (tests/conftest.py: a temporary data folder and a small generated
library). The plugin (light_novel/) is copied into that data folder's plugins/ folder before the app
starts, so the app imports it exactly as an owner installs it.
"""
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "light_novel"  # the plugin folder, as it is installed
APP = Path(os.environ.get("MANGAVIBE_DIR") or REPO.parent / "manga-vibe").resolve()
if not (APP / "app" / "main.py").exists():
    raise RuntimeError(f"MangaVibe not found at {APP}. Set MANGAVIBE_DIR to its checkout.")
sys.path.insert(0, str(APP))

from tests.conftest import TMP, client  # noqa: E402,F401  (the app's: sets DATA_DIR to TMP / "data")

shutil.copytree(PLUGIN, TMP / "data" / "plugins" / "light_novel", ignore=shutil.ignore_patterns("__pycache__"))
