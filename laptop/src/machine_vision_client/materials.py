"""Load and query the material reference table.

The xlsx has 23 rows whose `Label` column matches the 23 labels of
prithivMLmods/Minc-Materials-23 exactly. Each row carries the
flammability classification and (for combustibles) an auto-ignition
temperature range in Celsius.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl


XLSX_PATH = Path(__file__).parent / "재료별_불연성_가연성_발화점_참고표.xlsx"
SHEET = "재료별 발화점"

_RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)")
_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class Material:
    label: str
    flammable: bool
    is_material: bool
    ignition_c: tuple[float, float] | None
    classification_raw: str
    note: str


def _parse_ignition(cell) -> tuple[float, float] | None:
    if cell is None:
        return None
    s = str(cell)
    if "해당 없음" in s or "부적절" in s:
        return None
    m = _RANGE_RE.search(s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = _SINGLE_RE.search(s)
    if m:
        v = float(m.group(1))
        return v, v
    return None


def _parse_class(raw: str) -> tuple[bool, bool]:
    s = (raw or "").strip()
    if "재료 아님" in s:
        return False, False
    if "가연성" in s:
        return True, True
    return False, True


def load_materials(path: Path = XLSX_PATH) -> dict[str, Material]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[SHEET]
    out: dict[str, Material] = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        if len(row) < 6:
            continue
        _idx, label, classification, _desc, ignition, note = row[:6]
        if not isinstance(label, str) or not label.strip():
            continue
        flammable, is_material = _parse_class(classification or "")
        out[label.strip()] = Material(
            label=label.strip(),
            flammable=flammable,
            is_material=is_material,
            ignition_c=_parse_ignition(ignition),
            classification_raw=(classification or "").strip(),
            note=(note or "").strip(),
        )
    return out


if __name__ == "__main__":
    mats = load_materials()
    print(f"Loaded {len(mats)} materials")
    for m in mats.values():
        print(f"  {m.label:15s}  flammable={m.flammable!s:5s}  AIT={m.ignition_c}  ({m.classification_raw})")
