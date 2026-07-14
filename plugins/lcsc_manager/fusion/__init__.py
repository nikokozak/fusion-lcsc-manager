"""Autodesk Fusion Electronics support."""

import os
from pathlib import Path

os.environ.setdefault("LCSC_MANAGER_HOME", str(Path.home() / ".fusion_lcsc_manager"))

from .library_manager import FusionLibraryManager

__all__ = ["FusionLibraryManager"]
