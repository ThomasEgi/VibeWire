"""Test S5: fixed arc -> bi-arc -> fixed arc.

The old S2 used start -> bi-arc -> helper line -> fillet -> target. Its free
bi-arc radii could fall below the requested radius. S5 uses:

    start -> fixed-radius arc -> bi-arc -> fixed-radius arc -> target

The first fixed arc points its end tangent at the shortest-distance point on
the target segment. The last fixed arc is placed at that aim point and enters
the target at aim + radius along the target direction. A single deterministic
bi-arc connects the two fixed arcs; there is no candidate search.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_s5_fixed_arc_biarc_arc.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_s5_fixed_arc_biarc_arc.py
"""

import os
import sys

import FreeCAD as App
import Part

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
if SNIPPET_DIR not in sys.path:
    sys.path.insert(0, SNIPPET_DIR)

import m3_open_duct_shortest_path as m3

V = App.Vector
RADIUS = 16.0

CASES = [
    (
        "s1-s4 stem",
        V(0, 80, 0),
        V(0, 1, 0),
        V(-40, 0, 20),
        V(40, 80, 100),
    ),
    (
        "perpendicular",
        V(0, 0, 0),
        V(1, 0, 0),
        V(50, 0, 50),
        V(50, 100, 50),
    ),
    (
        "close start",
        V(-80, 2, 20),
        V(0, 0, -1),
        V(-100, 0, 0),
        V(100, 0, 0),
    ),
    (
        "above 3R",
        V(80, 0, 0),
        V(1, 0, 0),
        V(90, -30, 40),
        V(280, 160, 230),
    ),
]


def metrics(result):
    pieces = result["pieces"]
    radii = [
        piece["edge"].Curve.Radius
        for piece in pieces
        if isinstance(piece["edge"].Curve, Part.Circle)
    ]
    return {
        "length": sum(piece["length"] for piece in pieces),
        "min_radius": min(radii) if radii else None,
        "entry": result.get("entry_param"),
        "pieces": pieces,
        "mode": result.get("mode"),
    }


def check_result(name, result):
    info = metrics(result)
    failures = []

    def check(label, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, label, suffix))
        if not condition:
            failures.append(label)

    check(
        "entry lies on the target",
        0.0 <= float(info["entry"]) <= 1.0,
        "t={:.6f}".format(info["entry"]),
    )
    check(
        "minimum radius meets the fixed radius",
        info["min_radius"] is not None
        and info["min_radius"] >= RADIUS - 1e-6,
        "minR={:.4f}".format(info["min_radius"]),
    )
    check(
        "transition length positive",
        info["length"] > 1e-6,
        "{:.4f} mm".format(info["length"]),
    )
    entry_distance = (result["q"] - result["start_point"]).Length
    check(
        "start-to-entry clearance is at least 3R",
        entry_distance >= 3.0 * RADIUS - 1e-6,
        "{:.4f} mm".format(entry_distance),
    )
    expected_mode = (
        "direct_biarc"
        if entry_distance < 4.0 * RADIUS - 1e-6
        else "fixed_arcs"
    )
    check(
        "mode selection below/above 4R",
        result.get("mode") == expected_mode,
        "{} (expected {})".format(result.get("mode"), expected_mode),
    )

    pieces = info["pieces"]
    continuity = 0.0
    tangent_error = 0.0
    for index in range(len(pieces) - 1):
        first = pieces[index]["edge"]
        second = pieces[index + 1]["edge"]
        continuity = max(
            continuity,
            (first.valueAt(first.LastParameter) - second.valueAt(second.FirstParameter)).Length,
        )
        tangent_error = max(
            tangent_error,
            1.0
            - first.tangentAt(first.LastParameter).dot(
                second.tangentAt(second.FirstParameter)
            ),
        )
    check("pieces are continuous", continuity < 1e-6, "gap={:.9f}".format(continuity))
    check("pieces are tangent continuous", tangent_error < 1e-6, "err={:.9f}".format(tangent_error))
    try:
        wire = Part.Wire([piece["edge"] for piece in pieces])
        check("wire is valid", wire.isValid())
    except Exception as error:
        check("wire is valid", False, str(error))

    return info, failures


def main():
    print("VibeWire S5 test (fixed arc -> bi-arc -> fixed arc)")
    print("=" * 66)
    all_failures = []

    for name, start, tangent, target_start, target_end in CASES:
        print()
        print(name)
        try:
            old = m3.solve_biarc_line_arc(
                start,
                tangent,
                target_start,
                target_end,
                RADIUS,
                0.7,
                20.0,
            )
            old_info = metrics(old)
            print(
                "  old S2: length={:.4f}  minR={:.4f}  entry={:.6f}".format(
                    old_info["length"],
                    old_info["min_radius"],
                    old_info["entry"],
                )
            )
        except Exception as error:
            print("  old S2: FAIL {}".format(error))

        try:
            new = m3.solve_s5_fixed_arc_biarc_arc(
                start,
                tangent,
                target_start,
                target_end,
                RADIUS,
            )
            new_info, failures = check_result(name, new)
            print(
                "  S5: mode={}  length={:.4f}  minR={:.4f}  entry={:.6f}".format(
                    new_info["mode"],
                    new_info["length"],
                    new_info["min_radius"],
                    new_info["entry"],
                )
            )
            all_failures.extend(failures)
        except Exception as error:
            print("  S5: FAIL {}".format(error))
            all_failures.append("{} S5 exception".format(name))

    print()
    if all_failures:
        print("RESULT: {} check(s) failed".format(len(all_failures)))
        raise SystemExit(1)
    print("RESULT: all checks passed")


if __name__ == "__main__":
    main()
