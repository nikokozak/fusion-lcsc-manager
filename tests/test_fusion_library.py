"""Focused checks for the Fusion/EAGLE library writer."""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))

from lcsc_manager.fusion.library_manager import FusionLibraryManager


def _pin(number: str, name: str, x: str, y: str) -> str:
    return (
        f"P~show~3~{number}~{x}~{y}~180~gge{number}~0"
        f"^^{x}~{y}"
        f"^^M{x},{y}h10~#880000"
        f"^^1~0~0~0~{name}~start~~~#0000FF"
        f"^^1~0~0~0~{number}~end~~~"
        f"^^0~0~0"
        f"^^0~"
    )


def _unit(pin: str) -> dict:
    return {
        "dataStr": {
            "head": {
                "x": "400",
                "y": "300",
                "c_para": {"name": "TEST", "pre": "U?", "package": "SOIC-2"},
            },
            "BBox": {"x": "390", "y": "290", "width": "20", "height": "20"},
            "shape": ["R~390~290~~~20~20~#000~1~0~none~gge0~0", pin],
        }
    }


def _component() -> tuple[dict, dict]:
    easyeda = {
        "dataStr": {
            "head": {
                "x": "400",
                "y": "300",
                "c_para": {"name": "TEST", "pre": "U?", "package": "SOIC-2"},
            },
            "shape": [],
        },
        "subparts": [
            _unit(_pin("1", "IN", "390", "300")),
            _unit(_pin("2", "OUT", "410", "300")),
        ],
        "lcsc": {"number": "C123", "url": "https://example.com/C123"},
        "description": "Test component",
        "packageDetail": {
            "title": "SOIC-2",
            "dataStr": {
                "head": {
                    "x": "400",
                    "y": "300",
                    "c_para": {"package": "SOIC-2", "name": "TEST"},
                },
                "shape": [
                    "PAD~RECT~390~300~10~5~1~~1~0~~0~gge1~0~~1~0",
                    "PAD~RECT~410~300~10~5~1~~2~0~~0~gge2~0~~1~0",
                    "TRACK~1~3~~390 290 410 290~track1~0",
                ],
            },
        },
        "customData": {"jlcPara": {"assemblyProcess": "SMT"}},
        "SMT": True,
    }
    info = {
        "lcsc_id": "C123",
        "name": "TEST",
        "description": "Test component",
        "manufacturer": "Example",
        "manufacturer_part": "TEST-1",
        "package": "SOIC-2",
        "prefix": "U?",
        "datasheet": "https://example.com/test.pdf",
        "easyeda_data": easyeda,
    }
    return easyeda, info


def test_fusion_library_writes_and_overwrites_one_complete_device(tmp_path):
    output = tmp_path / "lcsc_imported.lbr"
    easyeda, info = _component()
    manager = FusionLibraryManager(output, api_client=object())

    results = []
    for _ in range(2):
        results.append(
            manager.import_component(
                easyeda,
                info,
                import_symbol=True,
                import_footprint=True,
                import_3d=False,
            )
        )

    root = ET.parse(output).getroot()
    assert root.get("version") == "9.6.2"
    assert len(root.findall(".//package")) == 1
    assert len(root.findall(".//symbol")) == 2
    assert len(root.findall(".//deviceset")) == 1
    assert len(root.findall(".//smd")) == 2

    gates = root.findall(".//deviceset/gates/gate")
    connects = root.findall(".//deviceset/devices/device/connects/connect")
    assert [gate.get("name") for gate in gates] == ["G$1", "G$2"]
    assert {(node.get("gate"), node.get("pad")) for node in connects} == {
        ("G$1", "1"),
        ("G$2", "2"),
    }
    assert root.find(".//attribute[@name='LCSC']").get("value") == "C123"
    assert [result["updated"] for result in results] == [False, True]
    assert results[-1]["device"] == "C123_TEST"
    assert not output.with_suffix(".lbr.tmp").exists()


def test_fusion_step_sidecar_rejects_non_step_downloads(tmp_path):
    easyeda, info = _component()
    easyeda["packageDetail"]["dataStr"]["head"]["c_para"]["3DModel"] = "TEST"
    easyeda["packageDetail"]["dataStr"]["shape"].append(
        "SVGNODE~" + json.dumps({"attrs": {
            "uuid": "0123456789abcdef0123456789abcdef",
            "title": "TEST",
            "c_origin": "0,0",
            "z": "0",
            "c_rotation": "0,0,0",
        }})
    )

    class Client:
        def __init__(self, content):
            self.content = content

        def download_file(self, _url, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.content)
            return True

    invalid = FusionLibraryManager(
        tmp_path / "invalid.lbr", Client(b"<html>not a model</html>")
    ).import_component(
        easyeda, info, import_symbol=False, import_footprint=False, import_3d=True
    )
    valid = FusionLibraryManager(
        tmp_path / "valid.lbr", Client(b"ISO-10303-21;\nEND-ISO-10303-21;")
    ).import_component(
        easyeda, info, import_symbol=False, import_footprint=False, import_3d=True
    )

    assert invalid["step"] is None
    assert not (tmp_path / "invalid.3dmodels" / "C123.step").exists()
    assert Path(valid["step"]).read_bytes().startswith(b"ISO-10303-21;")
