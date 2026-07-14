"""Fusion add-in entry point for LCSC Manager."""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
os.environ.setdefault("LCSC_MANAGER_HOME", str(Path.home() / ".fusion_lcsc_manager"))

# Packaged builds put both directories beside this file. The repository paths
# make the same folder linkable from Fusion while developing.
for candidate in (
    HERE / "lib",
    HERE,
    HERE.parent.parent / "plugins",
    *(HERE.parent.parent / ".venv" / "lib").glob("python*/site-packages"),
):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

import adsk.core  # type: ignore
import requests

from lcsc_manager.api.lcsc_api import LCSCAPIClient
from lcsc_manager.fusion.library_manager import FusionLibraryManager
from lcsc_manager.utils.config import Config
from lcsc_manager.utils.logger import get_logger


COMMAND_ID = "com_github_hulryung_lcsc_manager_fusion"
PALETTE_ID = f"{COMMAND_ID}_palette"
ASYNC_EVENT_ID = f"{COMMAND_ID}_async_result"
handlers: list[object] = []
app = None
ui = None
client = None
custom_event = None
component_cache = {}
logger = get_logger()


def _response(**values):
    return json.dumps({"ok": True, **values}, ensure_ascii=False)


def _error(message: str):
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def _default_output() -> Path:
    return Path.home() / "Documents" / "Fusion 360" / "LCSC" / "lcsc_imported.lbr"


def _search(payload: dict) -> str:
    query = str(payload.get("query", "")).strip()
    if not query:
        return _error("Enter a part number, name, or value.")
    results = client.advanced_search(
        component_name=query,
        package=str(payload.get("package", "")).strip(),
        page=max(1, int(payload.get("page", 1))),
    )
    return _response(
        results=[
            {
                "lcsc_id": item.get("lcsc", {}).get("number") or item.get("uuid"),
                "name": item.get("title", "Unknown"),
                "package": item.get("package", ""),
                "price": item.get("price", 0),
                "stock": item.get("stockCount", 0),
                "library_type": item.get("libraryType", ""),
                "manufacturer": item.get("manufacturer", ""),
                "manufacturer_part": item.get("manufacturer_part", ""),
                "description": item.get("description", ""),
                "datasheet": item.get("datasheet", ""),
                "url": item.get("url", ""),
                "image": item.get("image", ""),
            }
            for item in results
        ]
    )


def _preview(payload: dict) -> str:
    lcsc_id = str(payload.get("lcsc_id", "")).strip().upper()
    catalog = payload.get("component", {})
    if not isinstance(catalog, dict):
        catalog = {}
    if not lcsc_id:
        return _error("No LCSC part selected.")
    if not lcsc_id.startswith("C") or not lcsc_id[1:].isdigit():
        return _error("Invalid LCSC part number.")

    svgs = {}
    try:
        svg_response = requests.get(
            f"https://easyeda.com/api/products/{lcsc_id}/svgs",
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            },
        )
        svg_response.raise_for_status()
        svg_data = svg_response.json().get("result", [])
        svgs = {entry.get("docType"): entry.get("svg") for entry in svg_data}
    except (requests.RequestException, ValueError):
        logger.info(f"No EasyEDA preview available for {lcsc_id}")

    # The catalog search already supplies preview metadata. Only perform the
    # slower full lookup when EasyEDA returned no preview at all.
    component = None
    if not any(svgs.values()):
        component = client.search_component(lcsc_id)
        if not component:
            return _error(f"No EasyEDA CAD data found for {lcsc_id}.")
        component_cache.clear()
        component_cache[lcsc_id] = component

    info = component or catalog
    prices = info.get("price", [])
    if not isinstance(prices, list):
        prices = [{"qty": 1, "qty_max": None, "price": prices}] if prices else []
    image = info.get("image")
    if image:
        try:
            image_response = requests.get(image, timeout=10)
            image_response.raise_for_status()
            content = image_response.content
            mime = (
                "image/jpeg" if content.startswith(b"\xff\xd8\xff")
                else "image/png" if content.startswith(b"\x89PNG\r\n\x1a\n")
                else None
            )
            image = {"mime": mime, "hex": content.hex()} if mime else None
        except requests.RequestException:
            image = None
    return _response(
        symbol_svg=svgs.get(2),
        footprint_svg=svgs.get(4),
        component={
            "lcsc_id": info.get("lcsc_id") or lcsc_id,
            "name": info.get("name"),
            "manufacturer": info.get("manufacturer"),
            "manufacturer_part": info.get("manufacturer_part"),
            "package": info.get("package"),
            "description": info.get("description"),
            "stock": info.get("stock", 0),
            "price": prices,
            "jlcpcb_class": info.get("jlcpcb_class") or info.get("library_type"),
            "mounting": "SMT" if info.get("smt") else "",
            "datasheet": info.get("datasheet"),
            "url": info.get("url"),
            "image": image,
        },
    )


def _import(payload: dict) -> str:
    lcsc_id = str(payload.get("lcsc_id", "")).strip().upper()
    output = Path(str(payload.get("output", ""))).expanduser()
    if not lcsc_id:
        return _error("No LCSC part selected.")
    if output.suffix.lower() != ".lbr":
        return _error("The output path must end in .lbr.")

    component = component_cache.get(lcsc_id) or client.search_component(lcsc_id)
    if not component or not component.get("easyeda_data"):
        return _error(f"No EasyEDA CAD data found for {lcsc_id}.")
    result = FusionLibraryManager(output, client).import_component(
        component["easyeda_data"],
        component,
        import_symbol=bool(payload.get("symbol", True)),
        import_footprint=bool(payload.get("footprint", True)),
        import_3d=bool(payload.get("model_3d", True)),
    )
    return _response(result=result)


def _run_async(action: str, payload: dict, request_id: str) -> None:
    try:
        if action == "search":
            raw = _search(payload)
        elif action == "preview":
            raw = _preview(payload)
        else:
            raw = _import(payload)
    except Exception as exc:
        logger.exception(f"Fusion {action} failed")
        raw = _error(str(exc))

    message = json.dumps(
        {"request_id": request_id, "response": json.loads(raw)},
        ensure_ascii=False,
    )
    if app:
        app.fireCustomEvent(ASYNC_EVENT_ID, message)


class AsyncResultHandler(adsk.core.CustomEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.sendInfoToHTML("response", args.additionalInfo)


class IncomingHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            payload = json.loads(args.data or "{}")
            if args.action == "init":
                args.returnData = _response(
                    output=str(_default_output()),
                    limitation=(
                        "STEP models are downloaded automatically when available. After importing "
                        "the .lbr, attach the STEP file to its footprint in Fusion's package editor."
                    ),
                )
            elif args.action in ("search", "preview", "import"):
                request_id = str(payload.pop("request_id", ""))
                if not request_id:
                    args.returnData = _error("Missing request ID.")
                    return
                threading.Thread(
                    target=_run_async,
                    args=(args.action, payload, request_id),
                    daemon=True,
                ).start()
                args.returnData = _response(pending=True)
            else:
                args.returnData = _error(f"Unknown action: {args.action}")
        except Exception as exc:
            app.log(traceback.format_exc())
            args.returnData = _error(str(exc))


def _show_palette():
    palette = ui.palettes.itemById(PALETTE_ID)
    if palette is None:
        palette = ui.palettes.add(
            PALETTE_ID,
            "LCSC Manager",
            (HERE / "index.html").as_uri(),
            True,
            True,
            True,
            1100,
            760,
            True,
        )
        incoming = IncomingHandler()
        palette.incomingFromHTML.add(incoming)
        handlers.append(incoming)
    else:
        palette.isVisible = True


class ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, _args):
        _show_palette()


class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        execute = ExecuteHandler()
        args.command.execute.add(execute)
        handlers.append(execute)


def run(_context):
    global app, ui, client, custom_event
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        config = Config(Path(os.environ["LCSC_MANAGER_HOME"]) / "config.json")
        client = LCSCAPIClient(config=config)

        custom_event = app.registerCustomEvent(ASYNC_EVENT_ID)
        async_result = AsyncResultHandler()
        custom_event.add(async_result)
        handlers.append(async_result)

        command = ui.commandDefinitions.itemById(COMMAND_ID)
        if command is None:
            command = ui.commandDefinitions.addButtonDefinition(
                COMMAND_ID,
                "LCSC Manager",
                "Search and import LCSC components for Fusion Electronics",
                "",
            )
        created = CreatedHandler()
        command.commandCreated.add(created)
        handlers.append(created)

        toolbar = ui.toolbars.itemById("QAT")
        if toolbar:
            control = toolbar.controls.itemById(COMMAND_ID) or toolbar.controls.addCommand(command)
            control.isVisible = True

        if not _context.get("IsApplicationStartup", False):
            _show_palette()
    except Exception:
        if ui:
            ui.messageBox(f"LCSC Manager failed to start:\n{traceback.format_exc()}")


def stop(_context):
    global custom_event
    try:
        if not ui:
            return
        palette = ui.palettes.itemById(PALETTE_ID)
        if palette:
            palette.deleteMe()
        if custom_event:
            app.unregisterCustomEvent(ASYNC_EVENT_ID)
            custom_event = None
        toolbar = ui.toolbars.itemById("QAT")
        control = toolbar.controls.itemById(COMMAND_ID) if toolbar else None
        if control:
            control.deleteMe()
        command = ui.commandDefinitions.itemById(COMMAND_ID)
        if command:
            command.deleteMe()
        component_cache.clear()
        handlers.clear()
    except Exception:
        if app:
            app.log(traceback.format_exc())
