"""Generate Fusion Electronics-compatible EAGLE libraries from EasyEDA data."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from ..api.lcsc_api import LCSCAPIClient
from ..converters.model_3d_converter import ENDPOINT_3D_MODEL_STEP
from ..vendor.easyeda2kicad.easyeda.easyeda_importer import (
    EasyedaFootprintImporter,
    EasyedaSymbolImporter,
)
from ..vendor.easyeda2kicad.easyeda.svg_path_parser import (
    SvgPathClosePath,
    SvgPathEllipticalArc,
    SvgPathLineTo,
    SvgPathMoveTo,
    parse_svg_path,
)
from ..vendor.easyeda2kicad.kicad.export_kicad_footprint import (
    ExporterFootprintKicad,
    compute_arc,
)


_LAYERS = (
    (1, "Top", 4, 1, "yes"),
    (16, "Bottom", 1, 1, "yes"),
    (17, "Pads", 2, 1, "yes"),
    (18, "Vias", 2, 1, "yes"),
    (19, "Unrouted", 6, 1, "yes"),
    (20, "Dimension", 15, 1, "yes"),
    (21, "tPlace", 7, 1, "yes"),
    (22, "bPlace", 7, 1, "yes"),
    (23, "tOrigins", 15, 1, "yes"),
    (24, "bOrigins", 15, 1, "yes"),
    (25, "tNames", 7, 1, "yes"),
    (26, "bNames", 7, 1, "yes"),
    (27, "tValues", 7, 1, "yes"),
    (28, "bValues", 7, 1, "yes"),
    (29, "tStop", 7, 3, "no"),
    (30, "bStop", 7, 6, "no"),
    (31, "tCream", 7, 4, "no"),
    (32, "bCream", 7, 5, "no"),
    (35, "tGlue", 7, 4, "no"),
    (36, "bGlue", 7, 5, "no"),
    (39, "tKeepout", 4, 11, "no"),
    (40, "bKeepout", 1, 11, "no"),
    (41, "tRestrict", 4, 10, "no"),
    (42, "bRestrict", 1, 10, "no"),
    (43, "vRestrict", 2, 10, "no"),
    (44, "Drills", 7, 1, "yes"),
    (45, "Holes", 7, 1, "yes"),
    (46, "Milling", 3, 1, "no"),
    (47, "Measures", 7, 1, "no"),
    (48, "Document", 7, 1, "no"),
    (51, "tDocu", 7, 1, "yes"),
    (52, "bDocu", 7, 1, "no"),
    (91, "Nets", 2, 1, "yes"),
    (92, "Busses", 1, 1, "yes"),
    (93, "Pins", 2, 1, "yes"),
    (94, "Symbols", 4, 1, "yes"),
    (95, "Names", 7, 1, "yes"),
    (96, "Values", 7, 1, "yes"),
    (97, "Info", 7, 1, "yes"),
    (98, "Guide", 6, 1, "yes"),
)

_FP_LAYERS = {
    "F.Cu": 1,
    "B.Cu": 16,
    "F.SilkS": 21,
    "B.SilkS": 22,
    "F.Mask": 29,
    "B.Mask": 30,
    "F.Paste": 31,
    "B.Paste": 32,
    "Edge.Cuts": 20,
    "F.CrtYd": 39,
    "B.CrtYd": 40,
    "F.Fab": 51,
    "B.Fab": 52,
    "Cmts.User": 48,
    "Dwgs.User": 48,
}

_PIN_DIRECTIONS = {
    0: "pas",
    1: "in",
    2: "out",
    3: "io",
    4: "pwr",
}

_SYMBOL_SCALE = 1 / 3.937  # EasyEDA symbol coordinate to millimetres.


def _fmt(value: float) -> str:
    value = 0.0 if abs(value) < 0.0000005 else value
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _safe_name(value: Any, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_+.-]+", "_", str(value or "").strip())
    return text.strip("_") or fallback


def _pad_number(value: Any) -> str:
    value = str(value or "").strip()
    match = re.fullmatch(r"[^()]+\(([^()]+)\)", value)
    return match.group(1) if match else value


def _layer(name: str) -> int:
    return _FP_LAYERS.get(name, 48)


def _wire(
    parent: ET.Element,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    width: float = 0.254,
    layer: int = 94,
    curve: float | None = None,
) -> ET.Element:
    attrs = {
        "x1": _fmt(x1),
        "y1": _fmt(y1),
        "x2": _fmt(x2),
        "y2": _fmt(y2),
        "width": _fmt(max(width, 0.01)),
        "layer": str(layer),
    }
    if curve is not None and abs(curve) > 0.001:
        attrs["curve"] = _fmt(curve)
    return ET.SubElement(parent, "wire", attrs)


def _remove_named(parent: ET.Element, tag: str, names: Iterable[str]) -> None:
    names = set(names)
    for child in list(parent):
        if child.tag == tag and child.get("name") in names:
            parent.remove(child)


def _has_symbol_content(symbol: Any) -> bool:
    return any(
        getattr(symbol, field)
        for field in (
            "pins",
            "rectangles",
            "circles",
            "arcs",
            "ellipses",
            "polylines",
            "polygons",
            "paths",
            "texts",
        )
    )


class FusionLibraryManager:
    """Create or update one local ``.lbr`` file for Fusion Electronics."""

    def __init__(
        self,
        output_path: Path | str,
        api_client: LCSCAPIClient | None = None,
    ) -> None:
        self.output_path = Path(output_path).expanduser()
        if self.output_path.suffix.lower() != ".lbr":
            raise ValueError("Fusion library path must end in .lbr")
        self.api_client = api_client or LCSCAPIClient()

    def import_component(
        self,
        easyeda_data: dict[str, Any],
        component_info: dict[str, Any],
        *,
        import_symbol: bool = True,
        import_footprint: bool = True,
        import_3d: bool = True,
    ) -> dict[str, Any]:
        if not any((import_symbol, import_footprint, import_3d)):
            raise ValueError("Select at least one import option")

        lcsc_id = _safe_name(component_info.get("lcsc_id"), "UNKNOWN")
        component_name = _safe_name(
            component_info.get("name") or component_info.get("description"),
            "PART",
        )
        device_name = f"{lcsc_id}_{component_name}"
        package_name = f"{lcsc_id}_{_safe_name(component_info.get('package'), 'PACKAGE')}"
        notifications: list[str] = []

        root, library = self._load_library()
        packages = self._section(library, "packages")
        symbols = self._section(library, "symbols")
        devicesets = self._section(library, "devicesets")
        updated = any(
            node.get("name") in (device_name, package_name)
            for section, tag in (
                (packages, "package"),
                (symbols, "symbol"),
                (devicesets, "deviceset"),
            )
            for node in section.findall(tag)
        )

        footprint = None
        pad_map: dict[str, list[str]] = {}
        if import_footprint or import_3d:
            if "packageDetail" not in easyeda_data:
                if import_footprint:
                    raise ValueError(f"{lcsc_id} has no EasyEDA footprint")
            else:
                footprint = EasyedaFootprintImporter(easyeda_data).output

        if import_footprint and footprint is not None:
            package, pad_map, approximations = self._package_element(
                footprint, package_name, component_info
            )
            _remove_named(packages, "package", [package_name])
            packages.append(package)
            if approximations:
                notifications.append(
                    f"{approximations} custom or slotted pad(s) were approximated; verify them in Fusion."
                )
        else:
            existing_package = next(
                (p for p in packages.findall("package") if p.get("name") == package_name),
                None,
            )
            if existing_package is not None:
                pad_map = self._existing_pad_map(existing_package)

        symbol_names: list[str] = []
        gate_pins: list[tuple[str, list[tuple[str, str]]]] = []
        if import_symbol:
            parsed = EasyedaSymbolImporter(easyeda_data).output
            units = ([parsed] if _has_symbol_content(parsed) else []) + list(parsed.sub_symbols)
            if not units:
                raise ValueError(f"{lcsc_id} has no EasyEDA symbol")

            stale = [
                child.get("name", "")
                for child in symbols.findall("symbol")
                if child.get("name") == device_name
                or re.fullmatch(re.escape(device_name) + r"_\d+", child.get("name", ""))
            ]
            _remove_named(symbols, "symbol", stale)

            for index, unit in enumerate(units, start=1):
                symbol_name = device_name if len(units) == 1 else f"{device_name}_{index}"
                gate_name = f"G${index}"
                symbol, pins = self._symbol_element(unit, symbol_name)
                symbols.append(symbol)
                symbol_names.append(symbol_name)
                gate_pins.append((gate_name, pins))

            _remove_named(devicesets, "deviceset", [device_name])
            devicesets.append(
                self._deviceset_element(
                    device_name,
                    package_name,
                    component_info,
                    symbol_names,
                    gate_pins,
                    pad_map,
                )
            )

        step_path = None
        if import_3d:
            if footprint is None or footprint.model_3d is None:
                notifications.append("No STEP model is available for this component.")
            else:
                model_dir = self.output_path.parent / f"{self.output_path.stem}.3dmodels"
                step_path = model_dir / f"{lcsc_id}.step"
                url = ENDPOINT_3D_MODEL_STEP.format(uuid=footprint.model_3d.uuid)
                valid_step = False
                if self.api_client.download_file(url, step_path):
                    try:
                        with step_path.open("rb") as stream:
                            valid_step = b"ISO-10303-21;" in stream.read(256)
                    except OSError:
                        pass
                if not valid_step:
                    step_path.unlink(missing_ok=True)
                    step_path = None
                    notifications.append("No valid Fusion-compatible STEP model was downloaded.")
                else:
                    notifications.append(
                        "Fusion requires the downloaded STEP model to be attached in the package editor."
                    )

        if import_symbol or import_footprint:
            self._write_atomic(root)

        return {
            "library": str(self.output_path) if import_symbol or import_footprint else None,
            "device": device_name if import_symbol else None,
            "symbols": symbol_names,
            "package": package_name if import_footprint else None,
            "step": str(step_path) if step_path else None,
            "updated": updated,
            "notifications": notifications,
        }

    def _load_library(self) -> tuple[ET.Element, ET.Element]:
        if self.output_path.exists():
            try:
                root = ET.parse(self.output_path).getroot()
            except (ET.ParseError, OSError) as exc:
                raise ValueError(f"Cannot read existing Fusion library: {exc}") from exc
            library = root.find("./drawing/library")
            if root.tag != "eagle" or library is None:
                raise ValueError("Existing file is not an EAGLE/Fusion library")
            return root, library

        root = ET.Element("eagle", {"version": "9.6.2"})
        drawing = ET.SubElement(root, "drawing")
        settings = ET.SubElement(drawing, "settings")
        ET.SubElement(settings, "setting", {"alwaysvectorfont": "no"})
        ET.SubElement(settings, "setting", {"verticaltext": "up"})
        ET.SubElement(
            drawing,
            "grid",
            {
                "distance": "0.1",
                "unitdist": "inch",
                "unit": "inch",
                "style": "lines",
                "multiple": "1",
                "display": "no",
                "altdistance": "0.01",
                "altunitdist": "inch",
                "altunit": "inch",
            },
        )
        layers = ET.SubElement(drawing, "layers")
        for number, name, color, fill, visible in _LAYERS:
            ET.SubElement(
                layers,
                "layer",
                {
                    "number": str(number),
                    "name": name,
                    "color": str(color),
                    "fill": str(fill),
                    "visible": visible,
                    "active": "yes",
                },
            )
        library = ET.SubElement(drawing, "library")
        ET.SubElement(library, "description").text = (
            "LCSC/EasyEDA components generated by LCSC Manager for Fusion Electronics."
        )
        return root, library

    @staticmethod
    def _section(library: ET.Element, name: str) -> ET.Element:
        section = library.find(name)
        if section is None:
            section = ET.SubElement(library, name)
        return section

    def _write_atomic(self, root: ET.Element) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(ET, "indent"):
            ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
        content = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<!DOCTYPE eagle SYSTEM "eagle.dtd">\n'
            f"{body}\n"
        )
        temporary = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.output_path)

    def _symbol_element(
        self, symbol: Any, symbol_name: str
    ) -> tuple[ET.Element, list[tuple[str, str]]]:
        element = ET.Element("symbol", {"name": symbol_name})
        ET.SubElement(element, "description").text = symbol.info.description or symbol.info.name

        transform = lambda x, y: (
            (float(x) - symbol.bbox.x) * _SYMBOL_SCALE,
            -(float(y) - symbol.bbox.y) * _SYMBOL_SCALE,
        )

        for rectangle in symbol.rectangles:
            x1, y1 = transform(rectangle.pos_x, rectangle.pos_y)
            x2, y2 = transform(
                rectangle.pos_x + rectangle.width,
                rectangle.pos_y + rectangle.height,
            )
            _wire(element, x1, y1, x2, y1)
            _wire(element, x2, y1, x2, y2)
            _wire(element, x2, y2, x1, y2)
            _wire(element, x1, y2, x1, y1)

        for circle in symbol.circles:
            x, y = transform(circle.center_x, circle.center_y)
            ET.SubElement(
                element,
                "circle",
                {
                    "x": _fmt(x),
                    "y": _fmt(y),
                    "radius": _fmt(circle.radius * _SYMBOL_SCALE),
                    "width": "0.254",
                    "layer": "94",
                },
            )

        for ellipse in symbol.ellipses:
            cx, cy = transform(ellipse.center_x, ellipse.center_y)
            rx = ellipse.radius_x * _SYMBOL_SCALE
            ry = ellipse.radius_y * _SYMBOL_SCALE
            # ponytail: 24 segments are enough for schematic art; increase if visible faceting matters.
            points = [
                (
                    cx + rx * math.cos(2 * math.pi * i / 24),
                    cy + ry * math.sin(2 * math.pi * i / 24),
                )
                for i in range(25)
            ]
            for start, end in zip(points, points[1:]):
                _wire(element, *start, *end)

        for polyline in symbol.polylines:
            points = self._symbol_points(polyline.points, transform)
            for start, end in zip(points, points[1:]):
                _wire(element, *start, *end)

        for polygon in symbol.polygons:
            points = self._symbol_points(polygon.points, transform)
            if len(points) >= 3:
                poly = ET.SubElement(element, "polygon", {"width": "0.254", "layer": "94"})
                for x, y in points:
                    ET.SubElement(poly, "vertex", {"x": _fmt(x), "y": _fmt(y)})

        for arc in symbol.arcs:
            self._symbol_path(element, arc.path, transform)
        for path in symbol.paths:
            self._symbol_path(element, parse_svg_path(path.paths), transform)

        for text in symbol.texts:
            x, y = transform(text.pos_x, text.pos_y)
            node = ET.SubElement(
                element,
                "text",
                {
                    "x": _fmt(x),
                    "y": _fmt(y),
                    "size": _fmt(max(text.font_size, 1.27)),
                    "layer": "94",
                    "rot": f"R{int(text.rotation) % 360}",
                },
            )
            node.text = text.text

        half_height = max(float(symbol.bbox.height) * _SYMBOL_SCALE / 2, 2.54)
        name = ET.SubElement(
            element,
            "text",
            {"x": "0", "y": _fmt(half_height + 1.27), "size": "1.27", "layer": "95", "align": "bottom-center"},
        )
        name.text = ">NAME"
        value = ET.SubElement(
            element,
            "text",
            {"x": "0", "y": _fmt(-half_height - 1.27), "size": "1.27", "layer": "96", "align": "top-center"},
        )
        value.text = ">VALUE"

        pin_links: list[tuple[str, str]] = []
        used_names: defaultdict[str, int] = defaultdict(int)
        for index, pin in enumerate(symbol.pins, start=1):
            number = _pad_number(pin.settings.spice_pin_number)
            label = str(pin.name.text or f"P{number or index}").replace("@", "_")
            pin_name = f"{label}@{number or index}"
            used_names[pin_name] += 1
            if used_names[pin_name] > 1:
                pin_name += f"_{used_names[pin_name]}"
            x, y = transform(pin.settings.pos_x, pin.settings.pos_y)
            pin_type = getattr(pin.settings.type, "value", 0)
            attrs = {
                "name": pin_name,
                "x": _fmt(x),
                "y": _fmt(y),
                "visible": "both" if pin.name.is_displayed else "pad",
                "length": "short",
                "direction": _PIN_DIRECTIONS.get(pin_type, "pas"),
                "rot": f"R{(int(pin.settings.rotation) + 180) % 360}",
            }
            if pin.dot.is_displayed and pin.clock.is_displayed:
                attrs["function"] = "dotclk"
            elif pin.dot.is_displayed:
                attrs["function"] = "dot"
            elif pin.clock.is_displayed:
                attrs["function"] = "clk"
            ET.SubElement(element, "pin", attrs)
            if number:
                pin_links.append((pin_name, number))

        return element, pin_links

    @staticmethod
    def _symbol_points(points: str, transform: Any) -> list[tuple[float, float]]:
        values = [float(value) for value in re.split(r"[\s,]+", points.strip()) if value]
        return [transform(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]

    @staticmethod
    def _symbol_path(element: ET.Element, path: list[Any], transform: Any) -> None:
        start_raw: tuple[float, float] | None = None
        current_raw: tuple[float, float] | None = None
        for command in path:
            if isinstance(command, SvgPathMoveTo):
                current_raw = (float(command.start_x), float(command.start_y))
                start_raw = current_raw
            elif isinstance(command, SvgPathLineTo) and current_raw is not None:
                next_raw = (float(command.pos_x), float(command.pos_y))
                _wire(element, *transform(*current_raw), *transform(*next_raw))
                current_raw = next_raw
            elif isinstance(command, SvgPathEllipticalArc) and current_raw is not None:
                next_raw = (float(command.end_x), float(command.end_y))
                _, _, extent = compute_arc(
                    current_raw[0],
                    current_raw[1],
                    float(command.radius_x),
                    float(command.radius_y),
                    float(command.x_axis_rotation),
                    bool(command.flag_large_arc),
                    bool(command.flag_sweep),
                    next_raw[0],
                    next_raw[1],
                )
                _wire(
                    element,
                    *transform(*current_raw),
                    *transform(*next_raw),
                    curve=-extent,
                )
                current_raw = next_raw
            elif isinstance(command, SvgPathClosePath) and current_raw and start_raw:
                _wire(element, *transform(*current_raw), *transform(*start_raw))
                current_raw = start_raw

    def _package_element(
        self,
        footprint: Any,
        package_name: str,
        component_info: dict[str, Any],
    ) -> tuple[ET.Element, dict[str, list[str]], int]:
        package = ET.Element("package", {"name": package_name})
        ET.SubElement(package, "description").text = (
            f"{component_info.get('description') or component_info.get('name', '')} | "
            f"LCSC {component_info.get('lcsc_id', '')}"
        )
        converted = ExporterFootprintKicad(footprint=footprint).output
        pad_map: defaultdict[str, list[str]] = defaultdict(list)
        occurrences: defaultdict[str, int] = defaultdict(int)
        approximations = 0

        for index, (easyeda_pad, pad) in enumerate(zip(footprint.pads, converted.pads), start=1):
            canonical = _pad_number(pad.number) or f"P${index}"
            occurrences[canonical] += 1
            actual = canonical if occurrences[canonical] == 1 else f"{canonical}@{occurrences[canonical]}"
            pad_map[canonical].append(actual)
            x, y = pad.pos_x, -pad.pos_y
            rotation = f"R{int(round(pad.orientation)) % 360}"

            if pad.type == "smd":
                width, height = pad.width, pad.height
                if pad.shape == "custom":
                    approximations += 1
                    values = [float(value) for value in easyeda_pad.points.split() if value]
                    xs = values[0::2]
                    ys = values[1::2]
                    if xs and ys:
                        width = max(xs) - min(xs)
                        height = max(ys) - min(ys)
                        width *= 0.254
                        height *= 0.254
                    else:
                        width, height = easyeda_pad.width, easyeda_pad.height
                attrs = {
                    "name": actual,
                    "x": _fmt(x),
                    "y": _fmt(y),
                    "dx": _fmt(max(width, 0.01)),
                    "dy": _fmt(max(height, 0.01)),
                    "layer": "16" if "B.Cu" in pad.layers else "1",
                    "rot": rotation,
                }
                if pad.shape in ("circle", "oval"):
                    attrs["roundness"] = "100"
                ET.SubElement(package, "smd", attrs)
            else:
                drill = easyeda_pad.hole_radius * 2
                if easyeda_pad.hole_length:
                    approximations += 1
                    drill = max(drill, easyeda_pad.hole_length)
                shape = {
                    "rect": "square",
                    "circle": "round",
                    "oval": "long",
                }.get(pad.shape, "round")
                ET.SubElement(
                    package,
                    "pad",
                    {
                        "name": actual,
                        "x": _fmt(x),
                        "y": _fmt(y),
                        "drill": _fmt(max(drill, 0.01)),
                        "diameter": _fmt(max(pad.width, pad.height, drill + 0.2)),
                        "shape": shape,
                        "rot": rotation,
                    },
                )

        for track in converted.tracks:
            for x1, y1, x2, y2 in zip(
                track.points_start_x,
                track.points_start_y,
                track.points_end_x,
                track.points_end_y,
            ):
                _wire(
                    package,
                    x1,
                    -y1,
                    x2,
                    -y2,
                    width=track.stroke_width,
                    layer=_layer(track.layers),
                )

        for rectangle in converted.rectangles:
            for x1, y1, x2, y2 in zip(
                rectangle.points_start_x,
                rectangle.points_start_y,
                rectangle.points_end_x,
                rectangle.points_end_y,
            ):
                _wire(
                    package,
                    x1,
                    -y1,
                    x2,
                    -y2,
                    width=rectangle.stroke_width,
                    layer=_layer(rectangle.layers),
                )

        for circle in converted.circles:
            ET.SubElement(
                package,
                "circle",
                {
                    "x": _fmt(circle.cx),
                    "y": _fmt(-circle.cy),
                    "radius": _fmt(abs(circle.end_x - circle.cx)),
                    "width": _fmt(circle.stroke_width),
                    "layer": str(_layer(circle.layers)),
                },
            )

        for arc in converted.arcs:
            _wire(
                package,
                arc.start_x,
                -arc.start_y,
                arc.end_x,
                -arc.end_y,
                width=arc.stroke_width,
                layer=_layer(arc.layers),
                curve=-arc.angle,
            )

        for hole in converted.holes:
            ET.SubElement(
                package,
                "hole",
                {"x": _fmt(hole.pos_x), "y": _fmt(-hole.pos_y), "drill": _fmt(hole.size)},
            )

        for index, via in enumerate(converted.vias, start=1):
            ET.SubElement(
                package,
                "pad",
                {
                    "name": f"VIA${index}",
                    "x": _fmt(via.pos_x),
                    "y": _fmt(-via.pos_y),
                    "drill": _fmt(via.size),
                    "diameter": _fmt(max(via.diameter, via.size + 0.2)),
                    "shape": "round",
                },
            )

        for text in converted.texts:
            if "hide" in text.display:
                continue
            node = ET.SubElement(
                package,
                "text",
                {
                    "x": _fmt(text.pos_x),
                    "y": _fmt(-text.pos_y),
                    "size": _fmt(max(text.font_size, 0.5)),
                    "layer": str(_layer(text.layers)),
                    "rot": f"R{int(round(-text.orientation)) % 360}",
                },
            )
            node.text = text.text

        for region in converted.solid_regions:
            polygon = ET.SubElement(
                package,
                "polygon",
                {"width": "0", "layer": str(_layer(region.layer))},
            )
            for x, y in region.points:
                ET.SubElement(polygon, "vertex", {"x": _fmt(x), "y": _fmt(-y)})

        name = ET.SubElement(
            package,
            "text",
            {"x": "0", "y": "2.54", "size": "1.27", "layer": "25", "align": "bottom-center"},
        )
        name.text = ">NAME"
        value = ET.SubElement(
            package,
            "text",
            {"x": "0", "y": "-2.54", "size": "1.27", "layer": "27", "align": "top-center"},
        )
        value.text = ">VALUE"

        return package, dict(pad_map), approximations

    @staticmethod
    def _existing_pad_map(package: ET.Element) -> dict[str, list[str]]:
        result: defaultdict[str, list[str]] = defaultdict(list)
        for pad in [*package.findall("pad"), *package.findall("smd")]:
            actual = pad.get("name", "")
            if actual and not actual.startswith("VIA$"):
                result[actual.split("@", 1)[0]].append(actual)
        return dict(result)

    @staticmethod
    def _deviceset_element(
        device_name: str,
        package_name: str,
        component_info: dict[str, Any],
        symbol_names: list[str],
        gate_pins: list[tuple[str, list[tuple[str, str]]]],
        pad_map: dict[str, list[str]],
    ) -> ET.Element:
        prefix = _safe_name(str(component_info.get("prefix", "U")).replace("?", ""), "U")
        deviceset = ET.Element(
            "deviceset",
            {"name": device_name, "prefix": prefix, "uservalue": "yes"},
        )
        description = ET.SubElement(deviceset, "description")
        description.text = "\n".join(
            value
            for value in (
                str(component_info.get("description") or component_info.get("name") or ""),
                f"LCSC: {component_info.get('lcsc_id', '')}",
                f"Manufacturer: {component_info.get('manufacturer', '')}",
                f"MPN: {component_info.get('manufacturer_part', '')}",
                f"Datasheet: {component_info.get('datasheet', '')}",
            )
            if value.split(":", 1)[-1].strip()
        )

        gates = ET.SubElement(deviceset, "gates")
        for index, symbol_name in enumerate(symbol_names, start=1):
            ET.SubElement(
                gates,
                "gate",
                {"name": f"G${index}", "symbol": symbol_name, "x": "0", "y": "0"},
            )

        devices = ET.SubElement(deviceset, "devices")
        attrs = {"name": ""}
        if pad_map:
            attrs["package"] = package_name
        device = ET.SubElement(devices, "device", attrs)
        if pad_map:
            connects = ET.SubElement(device, "connects")
            connected_pads: set[str] = set()
            for gate_name, pins in gate_pins:
                for pin_name, number in pins:
                    pads = [pad for pad in pad_map.get(number, []) if pad not in connected_pads]
                    if not pads:
                        continue
                    ET.SubElement(
                        connects,
                        "connect",
                        {"gate": gate_name, "pin": pin_name, "pad": " ".join(pads)},
                    )
                    connected_pads.update(pads)

        technologies = ET.SubElement(device, "technologies")
        technology = ET.SubElement(technologies, "technology", {"name": ""})
        metadata = {
            "LCSC": component_info.get("lcsc_id"),
            "MANUFACTURER": component_info.get("manufacturer"),
            "MPN": component_info.get("manufacturer_part"),
            "DATASHEET": component_info.get("datasheet"),
            "JLCPCB_CLASS": component_info.get("jlcpcb_class"),
        }
        for name, value in metadata.items():
            if value not in (None, ""):
                ET.SubElement(
                    technology,
                    "attribute",
                    {"name": name, "value": str(value), "constant": "no"},
                )
        return deviceset
