"""Test the M3 open/closed bundle-segment foundation with a real harness wire.

Setup order:
1. create the harness,
2. add a segment and set its start/end point references,
3. repeat for the remaining segments,
4. create the wire from those segments and link it to the harness.

The route has three open segments. The first and last are tip segments, so
they must be treated as closed for this wire: the cable enters/leaves at the
segment endpoints even though those segments are globally open. The middle
open segment is routed automatically: S5 from the first tip and reversed S5
to the last tip determine its entry/exit. Manual entry/exit parameters are
ignored for open segments in this automatic mode.

Run in the FreeCAD GUI console:
    exec(open("/home/mx/opencaudetest/WirePlugin-main/snippet_archive/test_open_closed_segments.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/WirePlugin-main/snippet_archive/test_open_closed_segments.py

Reload the plugin or restart FreeCAD after changing the plugin code so the
updated WireBundle/WireCable modules are the ones in use.
"""

import os
import sys

import FreeCAD as App
import Part

DOC_NAME = "M3_OpenClosedSegmentsS5Test"

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
REPO_ROOT = os.path.dirname(SNIPPET_DIR)
FREECAD_DIR = os.path.join(REPO_ROOT, "freecad")
if FREECAD_DIR not in sys.path:
    sys.path.insert(0, FREECAD_DIR)

from VibeWire import WireBundle, WireCable, WireTransitions

V = App.Vector


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


def document_point(document, name, position):
    point = document.addObject("App::Part", name)
    point.Label = name
    point.Placement.Base = position
    return point


def add_segment(document, harness, start, end, radius=5.0, segment_type="Open"):
    segment = WireBundle.create_bundle_segment(harness, start, end, radius=radius)
    segment.Start = start
    segment.End = end
    segment.SegmentType = segment_type
    return segment


def has_line(shape, start, end, tolerance=1e-6):
    for edge in shape.Edges:
        if hasattr(edge.Curve, "Radius"):
            continue
        edge_start = edge.valueAt(edge.FirstParameter)
        edge_end = edge.valueAt(edge.LastParameter)
        if (
            (edge_start - start).Length < tolerance
            and (edge_end - end).Length < tolerance
        ) or (
            (edge_start - end).Length < tolerance
            and (edge_end - start).Length < tolerance
        ):
            return True
    return False


def main():
    document = prepare_document()

    first_start = V(0, 0, 0)
    first_end = V(80, 0, 0)
    middle_start = V(90, -30, 40)
    middle_end = V(280, 160, 230)
    last_start = V(380, 0, 300)
    last_end = V(460, 0, 300)
    first_direction = V(1, 0, 0)
    last_direction = V(1, 0, 0)
    transition_radius = max(4.0 * 4.0, 6.0)

    auto_transition_1 = WireTransitions.solve_s5_point_to_segment(
        first_end,
        first_direction,
        middle_start,
        middle_end,
        transition_radius,
    )
    auto_transition_2 = WireTransitions.solve_s5_segment_to_point(
        middle_start,
        middle_end,
        last_start,
        last_direction,
        transition_radius,
    )
    middle_entry = auto_transition_1["q"]
    middle_exit = auto_transition_2["source_departure"]

    p0 = document_point(document, "A0", first_start)
    p1 = document_point(document, "A1", first_end)
    p2 = document_point(document, "B0", middle_start)
    p3 = document_point(document, "B1", middle_end)
    p4 = document_point(document, "C0", last_start)
    p5 = document_point(document, "C1", last_end)

    harness = WireBundle.create_wire_harness(document, "OpenClosedHarness")

    segment1 = add_segment(document, harness, p0, p1, segment_type="Open")
    segment2 = add_segment(document, harness, p2, p3, segment_type="Open")
    segment3 = add_segment(document, harness, p4, p5, segment_type="Open")
    document.recompute()

    group = document.addObject("App::DocumentObjectGroup", "OpenClosedCable_Group")
    group.Label = "OpenClosedCable"
    cable = WireCable.create_wire_cable(
        document,
        [segment1, segment2, segment3],
        [0, 0, 0],
        diameter=4.0,
        min_bend_radius=6.0,
        container=group,
        build_cable=True,
    )
    WireBundle.add_cable_to_harness(harness, cable)

    cable.SegmentEntryParams = [0.2, 0.3, 0.2]
    cable.SegmentExitParams = [0.8, 0.7, 0.8]
    document.recompute()

    failures = []

    def check(name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        suffix = " ({})".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if not condition:
            failures.append(name)

    check("cable links to the harness", cable.Harness is harness)
    check(
        "harness cable order contains the cable",
        cable.Name in list(harness.CableOrder),
    )
    check(
        "harness computed a lane layout for the middle segment",
        "{}|{}".format(segment2.Name, cable.Name) in harness.Layout,
    )
    check("cable status", not cable.Status.startswith("Error"), cable.Status)
    check("cable shape is valid", cable.Shape.isValid())
    check("cable shape is one solid", len(cable.Shape.Solids) == 1)
    check(
        "path is valid",
        cable.PathObject is not None and cable.PathObject.Shape.isValid(),
    )

    path_shape = cable.PathObject.Shape
    check(
        "first tip segment uses its full run",
        has_line(path_shape, first_start, first_end),
    )
    check(
        "middle open segment uses its entry/exit range",
        has_line(path_shape, middle_entry, middle_exit),
    )
    check(
        "middle open run is shorter than the full segment",
        (middle_exit - middle_entry).Length
        < (middle_end - middle_start).Length - 1e-6,
        "{:.4f} / {:.4f} mm".format(
            (middle_exit - middle_entry).Length,
            (middle_end - middle_start).Length,
        ),
    )
    manual_entry = middle_start + (middle_end - middle_start) * 0.3
    manual_exit = middle_start + (middle_end - middle_start) * 0.7
    check(
        "manual entry/exit are ignored by auto open routing",
        not has_line(path_shape, manual_entry, manual_exit),
    )
    check(
        "last tip segment uses its full run",
        has_line(path_shape, last_start, last_end),
    )
    check(
        "path starts at the first tip endpoint",
        (
            path_shape.Edges[0].valueAt(path_shape.Edges[0].FirstParameter)
            - first_start
        ).Length
        < 1e-6,
    )
    check(
        "path ends at the last tip endpoint",
        (
            path_shape.Edges[-1].valueAt(path_shape.Edges[-1].LastParameter)
            - last_end
        ).Length
        < 1e-6,
    )

    segment2.SegmentType = "Closed"
    document.recompute()
    check(
        "closed middle segment rejects custom entry/exit",
        cable.Status.startswith("Error") and "Closed bundle segment" in cable.Status,
        cable.Status,
    )

    segment2.SegmentType = "Open"
    document.recompute()
    check(
        "open middle segment rebuilds",
        not cable.Status.startswith("Error"),
        cable.Status,
    )

    segment1.SegmentType = "Closed"
    segment3.SegmentType = "Closed"
    document.recompute()
    check(
        "closed tip segments still build end to end",
        not cable.Status.startswith("Error"),
        cable.Status,
    )
    path_shape = cable.PathObject.Shape
    check(
        "closed tip segments keep the full first run",
        has_line(path_shape, first_start, first_end),
    )
    check(
        "closed tip segments keep the full last run",
        has_line(path_shape, last_start, last_end),
    )

    start_tip = cable.StartTip
    check("start tip exists", start_tip is not None)
    if start_tip is not None:
        start_tip.LengthOffset = 20.0
        cable.touch()
        document.recompute()
        check(
            "open route supports tip offsets",
            not cable.Status.startswith("Error"),
            cable.Status,
        )
        check(
            "trimmed path length",
            abs(
                cable.PathObject.Shape.Length
                - (cable.Length.Value - 20.0)
            )
            < 1e-4,
            "{:.4f} mm".format(cable.PathObject.Shape.Length),
        )
        start_tip.LengthOffset = 0.0
        cable.touch()
        document.recompute()
        check(
            "tip offset reset",
            abs(cable.CableOnlyLength.Value - cable.Length.Value) < 1e-4,
        )

    print()
    print("Cable length: {:.4f} mm".format(cable.Length.Value))
    if failures:
        print("RESULT: {} check(s) failed".format(len(failures)))
    else:
        print("RESULT: all checks passed")
    print("Document: {}".format(document.Name))

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
