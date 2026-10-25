#!/usr/bin/env python3
"""Convert the DIN 46228 T4 ferrule CSV into the plugin JSON library."""

import argparse
import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = PROJECT_ROOT / "wire_end_sleeves_DIN_46228_T4_complete.csv"
DEFAULT_JSON = (
    PROJECT_ROOT
    / "freecad"
    / "WirePlugin"
    / "Resources"
    / "Data"
    / "ferrules_DIN46228_T4.json"
)

COLOR_PALETTE = {
    "BK": {"name": "black", "hex": "#000000"},
    "BN": {"name": "brown", "hex": "#8B4513"},
    "BU": {"name": "blue", "hex": "#0000FF"},
    "BE": {"name": "beige", "hex": "#F5F5DC"},
    "GN": {"name": "green", "hex": "#008000"},
    "GY": {"name": "grey", "hex": "#808080"},
    "IV": {"name": "ivory", "hex": "#FFFFF0"},
    "OG": {"name": "orange", "hex": "#FFA500"},
    "OL": {"name": "olive", "hex": "#808000"},
    "PK": {"name": "pink", "hex": "#FF69B4"},
    "RD": {"name": "red", "hex": "#FF0000"},
    "TQ": {"name": "turquoise", "hex": "#40E0D0"},
    "VT": {"name": "violet", "hex": "#800080"},
    "WH": {"name": "white", "hex": "#FFFFFF"},
    "YE": {"name": "yellow", "hex": "#FFD700"},
}


def _clean_row(row):
    return {
        (key or "").strip(): (value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _float(row, name, row_number):
    try:
        return float(row[name])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"Row {row_number}: invalid numeric value for {name!r}: "
            f"{row.get(name)!r}"
        ) from error


def _required(row, name, row_number):
    value = row.get(name, "").strip()
    if not value:
        raise ValueError(f"Row {row_number}: missing required value {name!r}")
    return value


def convert(csv_path):
    cross_sections = {}

    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        for row_number, raw_row in enumerate(reader, start=2):
            row = _clean_row(raw_row)

            cross_section = _float(row, "cross_section_mm2", row_number)
            awg = _required(row, "AWG", row_number)
            color_codes = {
                "DIN": _required(row, "color_code_DIN", row_number),
                "T": _required(row, "color_code_T", row_number),
                "W": _required(row, "color_code_W", row_number),
            }
            for code in color_codes.values():
                if code not in COLOR_PALETTE:
                    raise ValueError(
                        f"Row {row_number}: unknown color code {code!r}"
                    )

            note = row.get("Not according to norm", "").strip()
            variant = {
                "l1_mm": _float(row, "total_legnth_l1_mm", row_number),
                "l2_mm": _float(row, "l2_mm", row_number),
                "d1_mm": _float(row, "d1_mm", row_number),
                "s1_mm": _float(row, "s1_mm", row_number),
                "d2_mm": _float(row, "d2_mm", row_number),
                "s2_mm": _float(row, "s2_mm", row_number),
                "conforming": not bool(note),
            }
            if note:
                variant["note"] = note

            if variant["l1_mm"] <= variant["l2_mm"]:
                raise ValueError(
                    f"Row {row_number}: L1 must be greater than L2"
                )
            if min(
                variant["d1_mm"],
                variant["l1_mm"],
                variant["l2_mm"],
                variant["d2_mm"],
                variant["s1_mm"],
                variant["s2_mm"],
            ) <= 0:
                raise ValueError(
                    f"Row {row_number}: ferrule dimensions must be positive"
                )

            ferrule_type = "tube"
            standard = _required(row, "standard", row_number)

            key = round(cross_section, 6)
            entry = cross_sections.setdefault(
                key,
                {
                    "cross_section_mm2": cross_section,
                    "awg": awg,
                    "color_codes": color_codes,
                    "cable_diameter_mm": None,
                    "ferrules": [],
                    "_ferrules": {},
                },
            )
            if entry["awg"] != awg:
                raise ValueError(
                    f"Row {row_number}: AWG {awg!r} does not match "
                    f"{entry['awg']!r} for cross-section {cross_section:g} mm²"
                )
            if entry["color_codes"] != color_codes:
                raise ValueError(
                    f"Row {row_number}: color codes do not match other "
                    f"variants for cross-section {cross_section:g} mm²"
                )

            group_key = (ferrule_type, standard)
            group = entry["_ferrules"].setdefault(
                group_key,
                {
                    "type": ferrule_type,
                    "standard": standard,
                    "variants": [],
                    "_variant_keys": set(),
                },
            )
            variant_key = (
                variant["l1_mm"],
                variant["l2_mm"],
                variant["d1_mm"],
                variant["s1_mm"],
                variant["d2_mm"],
                variant["s2_mm"],
            )
            if variant_key in group["_variant_keys"]:
                raise ValueError(
                    f"Row {row_number}: duplicate {ferrule_type} variant "
                    f"for cross-section {cross_section:g} mm² "
                    f"under {standard!r}"
                )
            group["_variant_keys"].add(variant_key)
            group["variants"].append(variant)

    if not cross_sections:
        raise ValueError(f"No data rows found in {csv_path}")

    for entry in cross_sections.values():
        ferrules = []
        d2_values = set()
        for group in entry.pop("_ferrules").values():
            group.pop("_variant_keys", None)
            group["variants"].sort(
                key=lambda item: (item["l1_mm"], item["l2_mm"])
            )
            d2_values.update(
                variant["d2_mm"] for variant in group["variants"]
            )
            ferrules.append(group)

        if len(d2_values) != 1:
            raise ValueError(
                "Sleeve inner diameter d2 varies within cross-section "
                f"{entry['cross_section_mm2']:g} mm²: {sorted(d2_values)}"
            )
        entry["cable_diameter_mm"] = round(d2_values.pop() - 1.0, 6)
        entry["ferrules"] = sorted(
            ferrules,
            key=lambda item: (item["type"], item["standard"]),
        )

    result = {
        "schema_version": 2,
        "source_csv": csv_path.name,
        "units": "mm",
        "color_palette": {
            code: COLOR_PALETTE[code]
            for code in sorted(
                {
                    code
                    for entry in cross_sections.values()
                    for code in entry["color_codes"].values()
                }
            )
        },
        "cross_sections": [
            cross_sections[key] for key in sorted(cross_sections)
        ],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "csv",
        nargs="?",
        type=Path,
        default=DEFAULT_CSV,
        help=f"source CSV (default: {DEFAULT_CSV})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_JSON,
        help=f"output JSON (default: {DEFAULT_JSON})",
    )
    args = parser.parse_args()

    data = convert(args.csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(data['cross_sections'])} cross-sections to {args.output}"
    )


if __name__ == "__main__":
    main()
