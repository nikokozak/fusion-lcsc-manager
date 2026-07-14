"""Small command-line entry point for generating Fusion Electronics libraries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..api.lcsc_api import LCSCAPIClient
from ..utils.config import Config
from .library_manager import FusionLibraryManager


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import LCSC parts into a Fusion .lbr library")
    parser.add_argument("lcsc_ids", nargs="+", help="LCSC IDs such as C2040")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Documents" / "Fusion 360" / "LCSC" / "lcsc_imported.lbr",
    )
    parser.add_argument("--no-symbol", action="store_true")
    parser.add_argument("--no-footprint", action="store_true")
    parser.add_argument("--no-3d", action="store_true")
    args = parser.parse_args(argv)

    config = Config(Path.home() / ".fusion_lcsc_manager" / "config.json")
    client = LCSCAPIClient(config=config)
    manager = FusionLibraryManager(args.output, client)
    results = []
    for lcsc_id in args.lcsc_ids:
        component = client.search_component(lcsc_id.upper())
        if not component or not component.get("easyeda_data"):
            parser.error(f"No EasyEDA CAD data found for {lcsc_id}")
        results.append(
            manager.import_component(
                component["easyeda_data"],
                component,
                import_symbol=not args.no_symbol,
                import_footprint=not args.no_footprint,
                import_3d=not args.no_3d,
            )
        )
    print(json.dumps(results, indent=2))
    return 0
