"""M3 segment -> segment test: common perpendicular with two 90 degree fillets.

For two open duct centerlines the shortest connecting line is the common
perpendicular: it meets both segments at 90 degrees. Two fixed-radius quarter
circles can therefore be placed directly into the two corners, with a short
straight connector between them.

The target duct is shifted +20 mm along Y so the source-side fillet has room
before the stem start point. The source contact is no longer close to the
segment start.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_segment_to_segment.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/m3_segment_to_segment.py
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

DOC_NAME = "M3_SegmentToSegmentTest"
EPS = 1e-9

SOURCE_NAME = "stem"
TARGET_NAME = "angled"
TARGET_SHIFT_Y = 20.0

SOURCE = m3.SEGMENTS[SOURCE_NAME]
TARGET_BASE = m3.SEGMENTS[TARGET_NAME]
TARGET = (
    TARGET_BASE[0] + V(0.0, TARGET_SHIFT_Y, 0.0),
    TARGET_BASE[1] + V(0.0, TARGET_SHIFT_Y, 0.0),
)
RADIUS = m3.ARC_RADIUS
COLOR = (1.0, 0.30, 0.70)


def solve_segment_to_segment(source_start, source_end, target_start, target_end, radius):
    source_direction = m3.unit_vector(source_end - source_start)
    target_direction = m3.unit_vector(target_end - target_start)

    source_contact, target_contact = m3.closest_points_segments(
        source_start,
        source_end,
        target_start,
        target_end,
    )
    connector = target_contact - source_contact
    connector_length = connector.Length
    if connector_length <= 2.0 * radius + EPS:
        raise ValueError("Common perpendicular is too short for two fillets")
    connector_direction = m3.unit_vector(connector)

    source_tangent_segment = source_contact - source_direction * radius
    source_tangent_connector = source_contact + connector_direction * radius
    source_center = source_tangent_segment + connector_direction * radius

    target_tangent_connector = target_contact - connector_direction * radius
    target_tangent_segment = target_contact + target_direction * radius
    target_center = target_tangent_connector + target_direction * radius

    source_arc, source_angle, _ = m3.arc_from_start_tangent(
        source_center,
        source_tangent_segment,
        source_tangent_connector,
        source_direction,
    )
    connector_line = Part.makeLine(source_tangent_connector, target_tangent_connector)
    target_arc, target_angle, _ = m3.arc_from_start_tangent(
        target_center,
        target_tangent_connector,
        target_tangent_segment,
        connector_direction,
    )

    source_run = Part.makeLine(source_start, source_tangent_segment)
    target_run = Part.makeLine(target_tangent_segment, target_end)

    source_tangent_param = m3.raw_segment_param(
        (source_start, source_end),
        source_tangent_segment,
    )
    target_tangent_param = m3.raw_segment_param(
        (target_start, target_end),
        target_tangent_segment,
    )

    pieces = []
    if source_run.Length > EPS:
        pieces.append(
            {
                "kind": "duct",
                "name": "source run",
                "edge": source_run,
                "length": source_run.Length,
                "start": source_start,
                "end": source_tangent_segment,
            }
        )
    pieces.append(
        {
            "kind": "arc",
            "name": "source fillet",
            "edge": source_arc,
            "length": source_arc.Length,
            "start": source_tangent_segment,
            "end": source_tangent_connector,
        }
    )
    pieces.append(
        {
            "kind": "line",
            "name": "common perpendicular",
            "edge": connector_line,
            "length": connector_line.Length,
            "start": source_tangent_connector,
            "end": target_tangent_connector,
        }
    )
    pieces.append(
        {
            "kind": "arc",
            "name": "target fillet",
            "edge": target_arc,
            "length": target_arc.Length,
            "start": target_tangent_connector,
            "end": target_tangent_segment,
        }
    )
    if target_run.Length > EPS:
        pieces.append(
            {
                "kind": "duct",
                "name": "target run",
                "edge": target_run,
                "length": target_run.Length,
                "start": target_tangent_segment,
                "end": target_end,
            }
        )

    wire = m3.build_wire(pieces)
    cable = m3.build_cable(wire)
    total_length = sum(piece["length"] for piece in pieces)

    return {
        "source_start": source_start,
        "source_end": source_end,
        "source_direction": source_direction,
        "target_start": target_start,
        "target_end": target_end,
        "target_direction": target_direction,
        "source_contact": source_contact,
        "target_contact": target_contact,
        "connector_direction": connector_direction,
        "connector_length": connector_length,
        "source_tangent_segment": source_tangent_segment,
        "source_tangent_connector": source_tangent_connector,
        "target_tangent_connector": target_tangent_connector,
        "target_tangent_segment": target_tangent_segment,
        "source_center": source_center,
        "target_center": target_center,
        "source_arc": source_arc,
        "source_angle": source_angle,
        "target_arc": target_arc,
        "target_angle": target_angle,
        "connector_line": connector_line,
        "straight_length": connector_line.Length,
        "source_run": source_run,
        "target_run": target_run,
        "source_run_length": source_run.Length,
        "target_run_length": target_run.Length,
        "source_tangent_param": source_tangent_param,
        "target_tangent_param": target_tangent_param,
        "pieces": pieces,
        "wire": wire,
        "cable": cable,
        "transition_length": source_arc.Length + connector_line.Length + target_arc.Length,
        "total_length": total_length,
    }


def print_result(result):
    print("VibeWire M3 segment -> segment test (common perpendicular + fillets)")
    print("=" * 72)
    print("Target shift: {:+.1f} mm along Y".format(TARGET_SHIFT_Y))
    print(
        "Source: {}  {} -> {}".format(
            SOURCE_NAME,
            result["source_start"],
            result["source_end"],
        )
    )
    print(
        "Target: {}  {} -> {}".format(
            TARGET_NAME,
            result["target_start"],
            result["target_end"],
        )
    )
    print(
        "Shortest connection: source contact ({:8.3f}, {:8.3f}, {:8.3f})  target contact ({:8.3f}, {:8.3f}, {:8.3f})  length={:.4f} mm".format(
            result["source_contact"].x,
            result["source_contact"].y,
            result["source_contact"].z,
            result["target_contact"].x,
            result["target_contact"].y,
            result["target_contact"].z,
            result["connector_length"],
        )
    )
    print(
        "Connector: length={:.4f}  direction=({:.3f}, {:.3f}, {:.3f})  perpendicular source={:.6f}  target={:.6f}".format(
            result["connector_length"],
            result["connector_direction"].x,
            result["connector_direction"].y,
            result["connector_direction"].z,
            abs(result["connector_direction"].dot(result["source_direction"])),
            abs(result["connector_direction"].dot(result["target_direction"])),
        )
    )
    print()
    print("Fillets:")
    print(
        "  source: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}  start=({:8.3f}, {:8.3f}, {:8.3f})".format(
            math.degrees(result["source_angle"]),
            result["source_arc"].Length,
            result["source_arc"].Curve.Radius,
            result["source_tangent_segment"].x,
            result["source_tangent_segment"].y,
            result["source_tangent_segment"].z,
        )
    )
    print(
        "  target: angle={:7.2f} deg  length={:8.4f}  radius={:.3f}  end=({:8.3f}, {:8.3f}, {:8.3f})".format(
            math.degrees(result["target_angle"]),
            result["target_arc"].Length,
            result["target_arc"].Curve.Radius,
            result["target_tangent_segment"].x,
            result["target_tangent_segment"].y,
            result["target_tangent_segment"].z,
        )
    )
    print(
        "  connector straight part: {:.4f} mm".format(result["straight_length"])
    )
    print()
    print("Full path:")
    print("  source run:  {:8.4f} mm".format(result["source_run_length"]))
    print("  source fillet: {:8.4f} mm".format(result["source_arc"].Length))
    print("  connector:   {:8.4f} mm".format(result["connector_line"].Length))
    print("  target fillet: {:8.4f} mm".format(result["target_arc"].Length))
    print("  target run:  {:8.4f} mm".format(result["target_run_length"]))
    print("  total:       {:8.4f} mm".format(result["total_length"]))


def run_checks(result):
    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    source_contact, target_contact = m3.closest_points_segments(
        result["source_start"],
        result["source_end"],
        result["target_start"],
        result["target_end"],
    )
    check(
        "contacts are the closest pair",
        (result["source_contact"] - source_contact).Length < 1e-6
        and (result["target_contact"] - target_contact).Length < 1e-6,
    )
    check(
        "target shifted by the requested amount",
        abs((result["target_start"].y - TARGET_BASE[0].y) - TARGET_SHIFT_Y) < 1e-6
        and abs((result["target_end"].y - TARGET_BASE[1].y) - TARGET_SHIFT_Y) < 1e-6,
    )
    check(
        "connector is perpendicular to the source",
        abs(result["connector_direction"].dot(result["source_direction"])) < 1e-6,
        "dot={:.9f}".format(result["connector_direction"].dot(result["source_direction"])),
    )
    check(
        "connector is perpendicular to the target",
        abs(result["connector_direction"].dot(result["target_direction"])) < 1e-6,
        "dot={:.9f}".format(result["connector_direction"].dot(result["target_direction"])),
    )
    check(
        "common perpendicular is long enough for two fillets",
        result["connector_length"] > 2.0 * RADIUS + 1e-6,
        "{:.6f} mm".format(result["connector_length"]),
    )
    check(
        "source fillet tangent lies on the source duct",
        0.0 <= result["source_tangent_param"] <= 1.0,
        "t={:.6f}".format(result["source_tangent_param"]),
    )
    check(
        "target fillet tangent lies on the target duct",
        0.0 <= result["target_tangent_param"] <= 1.0,
        "t={:.6f}".format(result["target_tangent_param"]),
    )
    check(
        "source fillet radius",
        abs(result["source_arc"].Curve.Radius - RADIUS) < 1e-6,
        "{:.6f} mm".format(result["source_arc"].Curve.Radius),
    )
    check(
        "target fillet radius",
        abs(result["target_arc"].Curve.Radius - RADIUS) < 1e-6,
        "{:.6f} mm".format(result["target_arc"].Curve.Radius),
    )
    check(
        "source fillet is 90 degrees",
        abs(result["source_angle"] - math.pi / 2.0) < 1e-6,
        "{:.6f} deg".format(math.degrees(result["source_angle"])),
    )
    check(
        "target fillet is 90 degrees",
        abs(result["target_angle"] - math.pi / 2.0) < 1e-6,
        "{:.6f} deg".format(math.degrees(result["target_angle"])),
    )
    check(
        "source fillet starts tangent to the source",
        result["source_arc"].tangentAt(result["source_arc"].FirstParameter).dot(
            result["source_direction"]
        )
        > 1.0 - 1e-6,
    )
    check(
        "source fillet ends along the connector",
        result["source_arc"].tangentAt(result["source_arc"].LastParameter).dot(
            result["connector_direction"]
        )
        > 1.0 - 1e-6,
    )
    check(
        "target fillet starts along the connector",
        result["target_arc"].tangentAt(result["target_arc"].FirstParameter).dot(
            result["connector_direction"]
        )
        > 1.0 - 1e-6,
    )
    check(
        "target fillet ends tangent to the target",
        result["target_arc"].tangentAt(result["target_arc"].LastParameter).dot(
            result["target_direction"]
        )
        > 1.0 - 1e-6,
    )
    check(
        "connector length is the common perpendicular minus two radii",
        abs(result["straight_length"] - (result["connector_length"] - 2.0 * RADIUS)) < 1e-6,
        "{:.6f} mm".format(result["straight_length"]),
    )
    check(
        "source fillet stays beyond the source run start",
        (result["source_tangent_segment"] - result["source_start"]).dot(
            result["source_direction"]
        )
        >= -1e-6,
    )
    check(
        "target fillet stays before the target end",
        (result["target_end"] - result["target_tangent_segment"]).dot(
            result["target_direction"]
        )
        >= -1e-6,
    )

    continuity_error = 0.0
    for index in range(len(result["pieces"]) - 1):
        continuity_error = max(
            continuity_error,
            (result["pieces"][index]["end"] - result["pieces"][index + 1]["start"]).Length,
        )
    check(
        "full path is continuous",
        continuity_error < 1e-6,
        "max gap={:.9f}".format(continuity_error),
    )
    check(
        "total length matches the pieces",
        abs(result["total_length"] - sum(piece["length"] for piece in result["pieces"])) < 1e-6,
        "{:.6f} mm".format(result["total_length"]),
    )
    check("wire is valid", result["wire"] is not None and result["wire"].isValid())
    check(
        "wire has the expected edge count",
        result["wire"] is not None and len(result["wire"].Edges) == len(result["pieces"]),
        "{} edges".format(len(result["wire"].Edges) if result["wire"] is not None else 0),
    )
    check(
        "cable sweep produces one solid",
        result["cable"] is not None
        and result["cable"].isValid()
        and len(result["cable"].Solids) == 1,
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
    group = document.addObject("App::DocumentObjectGroup", "M3_SegmentToSegmentTest")
    group.Label = "M3 Segment -> Segment Test"

    display = {
        "left": m3.SEGMENTS["left"],
        "right": m3.SEGMENTS["right"],
        "stem": SOURCE,
        "angled (original)": TARGET_BASE,
        "angled (shifted)": TARGET,
    }
    for name, (start, end) in display.items():
        axis = end - start
        if axis.Length <= EPS:
            continue
        if name == "stem":
            role = "source"
        elif name == "angled (shifted)":
            role = "target"
        else:
            role = "context"
        duct = m3.add_feature(
            document,
            group,
            "M3_Duct_{}".format(name.replace(" ", "_").replace("(", "").replace(")", "")),
            "Duct {} ({})".format(name, role),
            Part.makeCylinder(m3.DUCT_RADIUS, axis.Length, start, axis.normalize()),
        )
        if role == "source":
            m3.view_property(duct, ShapeColor=(0.45, 0.47, 0.52), Transparency=85)
        elif role == "target":
            m3.view_property(duct, ShapeColor=(0.55, 0.45, 0.35), Transparency=80)
        elif name == "angled (original)":
            m3.view_property(duct, ShapeColor=(0.70, 0.70, 0.72), Transparency=92)
        else:
            m3.view_property(duct, ShapeColor=(0.70, 0.70, 0.72), Transparency=90)

    combined = {
        "pieces": result["pieces"],
        "start_point": result["source_start"],
        "q": result["target_end"],
        "arc_centers": [result["source_center"], result["target_center"]],
    }
    m3.add_transition_objects(
        document,
        group,
        "M3_Seg2Seg",
        "Common perpendicular + fillets",
        combined,
        result["wire"],
        result["cable"],
        COLOR,
    )

    document.recompute()
    return document


def main():
    result = solve_segment_to_segment(
        SOURCE[0],
        SOURCE[1],
        TARGET[0],
        TARGET[1],
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
