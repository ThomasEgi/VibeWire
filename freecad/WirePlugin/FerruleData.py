"""Access to the bundled DIN 46228 T4 ferrule library."""

import json
from pathlib import Path

_DATA_PATH = (
    Path(__file__).resolve().parent
    / "Resources"
    / "Data"
    / "ferrules_DIN46228_T4.json"
)
_LIBRARY = None


def library():
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _LIBRARY


def cross_sections():
    return library().get("cross_sections", [])


def cross_section_for_size(size_mm2):
    if size_mm2 is None:
        return None
    try:
        target = float(size_mm2)
    except (TypeError, ValueError):
        return None
    for entry in cross_sections():
        if abs(entry["cross_section_mm2"] - target) < 1e-6:
            return entry
    return None


def size_label(entry):
    return f"{entry['cross_section_mm2']:g} mm² (AWG {entry['awg']})"


def ferrule_types(entry):
    return entry.get("ferrules", [])


def ferrule_type(entry, type_name):
    for type_entry in ferrule_types(entry):
        if type_entry.get("type") == type_name:
            return type_entry
    return None


def ferrule_type_label(type_entry):
    return f"{type_entry['type']} ({type_entry['standard']})"


def variants(type_entry):
    return type_entry.get("variants", [])


def variant(type_entry, index):
    items = variants(type_entry)
    if not items:
        return None
    try:
        return items[int(index)]
    except (TypeError, ValueError, IndexError):
        return items[0]


def variant_label(variant_data):
    label = (
        f"L1 {variant_data['l1_mm']:g} / "
        f"L2 {variant_data['l2_mm']:g} mm"
    )
    if not variant_data.get("conforming", True):
        label += " (not conforming)"
    return label


def color_palette():
    return library().get("color_palette", {})


def color_info(code):
    return color_palette().get(code)


def color_code(entry, system):
    return entry.get("color_codes", {}).get(system)


def color_for_system(entry, system):
    code = color_code(entry, system)
    info = color_info(code) if code else None
    return info, code


def hex_to_rgb(value):
    text = str(value or "").lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    except ValueError:
        return None


def cone_length(variant_data):
    metal_outer = variant_data["d1_mm"] + 2.0 * variant_data["s1_mm"]
    sleeve_outer = variant_data["d2_mm"] + 2.0 * variant_data["s2_mm"]
    return max(0.0, (sleeve_outer - metal_outer) / 2.0)


def sleeve_length(variant_data):
    return max(
        0.0,
        variant_data["l1_mm"]
        - variant_data["l2_mm"]
        - cone_length(variant_data),
    )


def strip_length(variant_data):
    return variant_data["l2_mm"] + cone_length(variant_data)
