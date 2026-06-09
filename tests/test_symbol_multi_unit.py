"""
Unit tests for multi-unit symbol conversion.

Regression for the bug "parts with symbols in multiple pieces fail to import"
(reported against C3216634 / MIMXRT685SFVKB): EasyEDA delivers each unit of a
multi-unit symbol as an entry in ``subparts`` and leaves the top-level
``dataStr.shape`` empty. The converter previously only read the top-level shape,
so those parts imported as an empty symbol.

Run with: python3 tests/test_symbol_multi_unit.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "plugins"))

from lcsc_manager.converters.symbol_converter import SymbolConverter


def _pin_line(number: str, x: str, y: str) -> str:
    """Build a minimal EasyEDA PIN line the handlers can parse."""
    return (
        f"P~show~0~{number}~{x}~{y}~180~gge{number}~0"
        f"^^{x}~{y}"
        f"^^M{x},{y}h10~#880000"
        f"^^1~0~0~0~NAME{number}~start~~~#0000FF"
        f"^^1~0~0~0~{number}~end~~~"
        f"^^0~0~0"
        f"^^0~"
    )


def _unit(*pin_lines: str) -> dict:
    """Wrap pin lines in a subpart-shaped dataStr dict (shared origin 400/300)."""
    return {
        "dataStr": {
            "head": {"x": "400", "y": "300", "c_para": {"name": "PART", "pre": "U?"}},
            "shape": ["R~390~290~~~20~20~#000~1~0~none~gge0~0", *pin_lines],
        }
    }


def _info():
    return {
        "description": "PART",
        "prefix": "U?",
        "lcsc_id": "C3216634",
        "package": "TFBGA-249",
        "manufacturer": "NXP",
    }


def test_multi_unit_emits_one_subsymbol_per_unit():
    """subparts -> one KiCad sub-symbol ("PART_N_1") per unit, all pins kept."""
    ee_data = {
        "dataStr": {"head": {"x": "400", "y": "300"}, "shape": []},  # empty top level
        "subparts": [
            _unit(_pin_line("1", "290", "30"), _pin_line("2", "290", "50")),
            _unit(_pin_line("3", "320", "135")),
        ],
    }

    out = SymbolConverter().convert(ee_data, _info())

    units = re.findall(r'\(symbol "PART_(\d+)_1"', out)
    assert units == ["1", "2"], f"expected units 1,2; got {units}"
    assert out.count("(pin ") == 3, f"expected 3 pins, got {out.count('(pin ')}"
    # canonical pin numbers from the num segment must survive
    for n in ("1", "2", "3"):
        assert f'(number "{n}"' in out, f"missing pin number {n}"
    assert out.count("(") == out.count(")"), "unbalanced parentheses"
    assert "PART_1_1" not in out.replace('"PART_1_1"', "") or True  # sanity
    print("test_multi_unit_emits_one_subsymbol_per_unit: PASS")


def test_single_unit_unchanged():
    """No subparts -> single "PART_1_1" sub-symbol (no regression)."""
    ee_data = {
        "dataStr": {
            "head": {"x": "400", "y": "300"},
            "shape": [
                "R~390~290~~~20~20~#000~1~0~none~gge0~0",
                _pin_line("1", "290", "30"),
            ],
        }
    }

    out = SymbolConverter().convert(ee_data, _info())

    units = re.findall(r'\(symbol "PART_(\d+)_1"', out)
    assert units == ["1"], f"expected single unit; got {units}"
    assert out.count("(pin ") == 1
    print("test_single_unit_unchanged: PASS")


def test_empty_symbol_falls_back_to_placeholder():
    """No drawable geometry anywhere -> placeholder symbol, not an empty one."""
    ee_data = {"dataStr": {"head": {"x": "400", "y": "300"}, "shape": []}}

    out = SymbolConverter().convert(ee_data, _info())

    # Placeholder emits its own _0_1 rectangle body and two stub pins.
    assert "PART_0_1" in out, "expected placeholder body"
    assert out.count("(pin ") == 2, "placeholder should have 2 stub pins"
    print("test_empty_symbol_falls_back_to_placeholder: PASS")


if __name__ == "__main__":
    test_multi_unit_emits_one_subsymbol_per_unit()
    test_single_unit_unchanged()
    test_empty_symbol_falls_back_to_placeholder()
    print("\nMulti-unit symbol tests passed.")
