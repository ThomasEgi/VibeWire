"""M3 segment -> point test: solution 4 with reversed inputs.

Solution 4 handles point -> segment. A segment -> point connection is the
same problem with the direction reversed:

1. start at the target point with the reversed arrival tangent,
2. target the source segment with its direction reversed,
3. run solution 4,
4. reverse the resulting path.

The reversed path starts on the source segment, leaves it tangentially, and
ends at the target point with the requested arrival tangent.

This test uses the same stem-end -> angled-duct geometry as the s1..s4
comparison, but reversed: the angled duct is the source (B -> A) and the
stem end is the target point.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_segment_to_point.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_segment_to_point.py
"""

import math
import os
import sys

import FreeCAD as App
import Part

V = App.Vector

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
if SNIPPET_DIR not in sys.path:
    sys.path.insert(0, SNIPPET_DIR)

import m3_open_duct_shortest_path as m3

DOC_NAME = "M3_SegmentToPointTest"
EPS = 1e-9

SOURCE_NAME = "angled (reversed)"
SOURCE = (
    m3.SEGMENTS["angled"][1],
    m3.SEGMENTS["angled"][0],
)
TARGET_POINT = m3.SEGMENTS["stem"][1]
TARGET_TANGENT = -m3.unit_vector(
    m3.SEGMENTS["stem"][1] - m3.SEGMENTS["stem"][0]
)
RADIUS = m3.ARC_RADIUS
COLOR = (1.0, 0.30, 0.70)


def reverse_edge(edge):
    if isinstance(edge.Curve, Part.Circle):
        start = edge.valueAt(edge.LastParameter)
        end = edge.valueAt(edge.FirstParameter)
        tangent = -edge.tangentAt(edge.LastParameter)
        reversed_edge, _, _ = m3.arc_from_start_tangent(
            edge.Curve.Center,
            start,
            end,
            tangent,
        )
        return reversed_edge
    return Part.makeLine(
        edge.valueAt(edge.LastParameter),
        edge.valueAt(edge.FirstParameter),
    )


def solve_segment_to_point(source_start, source_end, target_point, target_tangent, radius):
    source_direction = m3.unit_vector(source_end - source_start)
    point_tangent = m3.unit_vector(target_tangent)

    transition = m3.solve_perpendicular_line_arc(
        target_point,
        -point_tangent,
        source_end,
        source_start,
        radius,
    )

    forward_pieces = list(transition["pieces"])
    forward_target_run = Part.makeLine(transition["q"], source_start)
    if forward_target_run.Length > EPS:
        forward_pieces.append(
            {
                "kind": "duct",
                "name": "target run",
                "edge": forward_target_run,
                "length": forward_target_run.Length,
                "start": transition["q"],
                "end": source_start,
            }
        )

    forward_wire = m3.build_wire(forward_pieces)
    forward_cable = m3.build_cable(forward_wire)

    reversed_pieces = []
    for piece in reversed(forward_pieces):
        reversed_edge = reverse_edge(piece["edge"])
        reversed_pieces.append(
            {
                "kind": piece["kind"],
                "name": piece["name"],
                "edge": reversed_edge,
                "length": reversed_edge.Length,
                "start": piece["end"],
                "end": piece["start"],
            }
        )

    wire = m3.build_wire(reversed_pieces)
    cable = m3.build_cable(wire)
    total_length = sum(piece["length"] for piece in reversed_pieces)
    departure = transition["q"]

    return {
        "source_start": source_start,
        "source_end": source_end,
        "source_direction": source_direction,
        "source_departure": departure,
        "source_departure_param": m3.raw_segment_param(
            (source_start, source_end),
            departure,
        ),
        "source_run_length": (departure - source_start).Length,
        "target_point": target_point,
        "target_tangent": point_tangent,
        "transition": transition,
        "forward_pieces": forward_pieces,
        "forward_wire": forward_wire,
        "forward_cable": forward_cable,
        "forward_total": sum(piece["length"] for piece in forward_pieces),
        "pieces": reversed_pieces,
        "wire": wire,
        "cable": cable,
        "total_length": total_length,
    }


def print_result(result):
    transition = result["transition"]
    print("VibeWire M3 segment -> point test (solution 4 reversed)")
    print("=" * 62)
    print(
        "Source: {}  {} -> {}".format(
            SOURCE_NAME,
            result["source_start"],
            result["source_end"],
        )
    )
    print(
        "Target point: ({:.3f}, {:.3f}, {:.3f})  arrival tangent=({:.3f}, {:.3f}, {:.3f})".format(
            result["target_point"].x,
            result["target_point"].y,
            result["target_point"].z,
            result["target_tangent"].x,
            result["target_tangent"].y,
            result["target_tangent"].z,
        )
    )
    print(
        "Source departure: t={:.4f} ({:8.3f}, {:8.3f}, {:8.3f})".format(
            result["source_departure_param"],
            result["source_departure"].x,
            result["source_departure"].y,
            result["source_departure"].z,
        )
    )
    print(
        "Reversed S4 transition: {} pieces, length={:.4f} mm".format(
            len(transition["pieces"]),
            transition["transition_length"],
        )
    )
    print(
        "Forward point->segment entry: t={:.4f}, q=({:.3f}, {:.3f}, {:.3f})".format(
            transition["entry_param"],
            transition["q"].x,
            transition["q"].y,
            transition["q"].z,
        )
    )
    print()
    print("Full reversed path:")
    for index, piece in enumerate(result["pieces"], start=1):
        print(
            "  {}. {:<20s} {:<6s} {:8.4f} mm".format(
                index,
                piece["name"],
                piece["kind"],
                piece["length"],
            )
        )
    print("  source run:  {:8.4f} mm".format(result["source_run_length"]))
    print("  total:       {:8.4f} mm".format(result["total_length"]))


def run_checks(result):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    check(
        "source departure lies on the source duct",
        0.0 <= result["source_departure_param"] <= 1.0,
        "t={:.6f}".format(result["source_departure_param"]),
    )
    check(
        "source run follows the source direction",
        (result["source_departure"] - result["source_start"]).dot(
            result["source_direction"]
        )
        >= -1e-6,
    )

    first_edge = result["pieces"][0]["edge"]
    last_edge = result["pieces"][-1]["edge"]
    check(
        "reversed path starts at the source start",
        (first_edge.valueAt(first_edge.FirstParameter) - result["source_start"]).Length
        < 1e-6,
    )
    check(
        "reversed path starts tangent to the source",
        first_edge.tangentAt(first_edge.FirstParameter).dot(
            result["source_direction"]
        )
        > 1.0 - 1e-6,
    )
    check(
        "reversed path ends at the target point",
        (last_edge.valueAt(last_edge.LastParameter) - result["target_point"]).Length
        < 1e-6,
    )
    check(
        "reversed path ends with the requested tangent",
        last_edge.tangentAt(last_edge.LastParameter).dot(result["target_tangent"])
        > 1.0 - 1e-6,
    )
    check(
        "reversed path total equals the forward total",
        abs(result["total_length"] - result["forward_total"]) < 1e-6,
        "{:.6f} mm".format(result["total_length"]),
    )

    continuity_error = 0.0
    for index in range(len(result["pieces"]) - 1):
        continuity_error = max(
            continuity_error,
            (
                result["pieces"][index]["end"]
                - result["pieces"][index + 1]["start"]
            ).Length,
        )
    check(
        "reversed path is continuous",
        continuity_error < 1e-6,
        "max gap={:.9f}".format(continuity_error),
    )

    arc_radii = []
    for piece in result["pieces"]:
        if piece["kind"] == "arc":
            arc_radii.append(piece["edge"].Curve.Radius)
    check(
        "all reversed arcs keep the fixed radius",
        bool(arc_radii)
        and max(arc_radii) - min(arc_radii) < 1e-6
        and abs(min(arc_radii) - RADIUS) < 1e-6,
        "radii={}".format(", ".join("{:.3f}".format(value) for value in arc_radii)),
    )
    check("reversed wire is valid", result["wire"] is not None and result["wire"].isValid())
    check(
        "reversed wire has the expected edge count",
        result["wire"] is not None
        and len(result["wire"].Edges) == len(result["pieces"]),
        "{} edges".format(
            len(result["wire"].Edges) if result["wire"] is not None else 0
        ),
    )
    check(
        "reversed cable sweep produces one solid",
        result["cable"] is not None
        and result["cable"].isValid()
        and len(result["cable"].Solids) == 1,
    )

    print()
    print("Forward S4 checks (point -> segment):")
    failures.extend(
        m3.run_perpendicular_line_arc_checks(
            result["transition"],
            result["forward_pieces"],
            result["forward_wire"],
            result["forward_cable"],
        )
    )
    return failures


def prepare_document():
    document = App.listDocuments().get(DOC_NAME)
    if document is None:
        document = App.newDocument(DOC_NAME)
    else:
        for obj in reversed(list(document.Objects)):
            try:
                document.removeObject(obj.Name)
            except Exception:
                pass
        document.recompute()
    App.setActiveDocument(document.Name)
    return document


def build_document(result):
    document = prepare_document()
    group = document.addObject("App::DocumentObjectGroup", "M3_SegmentToPointTest")
    group.Label = "M3 Segment -> Point Test"

    display = {
        "left": m3.SEGMENTS["left"],
        "right": m3.SEGMENTS["right"],
        "stem": m3.SEGMENTS["stem"],
        "angled": m3.SEGMENTS["angled"],
    }
    for name, (start, end) in display.items():
        axis = end - start
        if axis.Length <= EPS:
            continue
        if name == "angled":
            role = "source"
        elif name == "stem":
            role = "target context"
        else:
            role = "context"
        duct = m3.add_feature(
            document,
            group,
            "M3_Duct_{}".format(name),
            "Duct {} ({})".format(name, role),
            Part.makeCylinder(m3.DUCT_RADIUS, axis.Length, start, axis.normalize()),
        )
        if role == "source":
            m3.view_property(duct, ShapeColor=(0.45, 0.47, 0.52), Transparency=85)
        elif role == "target context":
            m3.view_property(duct, ShapeColor=(0.70, 0.70, 0.72), Transparency=90)
        else:
            m3.view_property(duct, ShapeColor=(0.70, 0.70, 0.72), Transparency=90)

    target_marker = m3.add_feature(
        document,
        group,
        "M3_TargetPoint",
        "Target point",
        Part.makeSphere(m3.MARKER_RADIUS, result["target_point"]),
    )
    m3.view_property(target_marker, ShapeColor=(0.95, 0.15, 0.10), Transparency=0)

    combined = {
        "pieces": result["pieces"],
        "start_point": result["source_start"],
        "q": result["target_point"],
        "arc_centers": result["transition"]["arc_centers"],
    }
    m3.add_transition_objects(
        document,
        group,
        "M3_Seg2Point",
        "Segment -> point (S4 reversed)",
        combined,
        result["wire"],
        result["cable"],
        COLOR,
    )

    document.recompute()
    return document


def main():
    result = solve_segment_to_point(
        SOURCE[0],
        SOURCE[1],
        TARGET_POINT,
        TARGET_TANGENT,
        RADIUS,
    )
    print_result(result)
    document = build_document(result)

    print()
    print("Checks:")
    failures = run_checks(result)
    print()
    if failures:
        print("RESULT: {} check(s) failed".format(len(failures)))
    else:
        print("RESULT: all checks passed")
    print("Objects in '{}': {}".format(document.Name, len(document.Objects)))

    if getattr(App, "GuiUp", False):
        try:
            import FreeCADGui as Gui

            Gui.activeDocument().activeView().fitAll()
        except Exception:
            pass

    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
