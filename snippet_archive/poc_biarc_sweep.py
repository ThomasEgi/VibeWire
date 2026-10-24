"""Proof of concept: a chain of cable segments joined by symmetric bi-arcs.

By default the route is 20 randomly generated segments inside a +/-300 mm
volume. For the original two-segment example call main(TWO_SEGMENTS).

Run from the FreeCAD GUI Python console:
    exec(open("/home/mx/opencaudetest/wireplugin/poc_biarc_sweep.py").read())

Run headless:
    freecadcmd /home/mx/opencaudetest/wireplugin/poc_biarc_sweep.py

The bi-arc is the G1 transition between the end of one straight segment and
the start of the next. FreeCAD/OpenCascade has no built-in bi-arc solver, so
the joint point is computed in Python; arc construction, tangency checks,
lengths, curvature, and the sweep all use FreeCAD's Part kernel.
"""

import math
import os
import random
import sys
from collections import namedtuple

import FreeCAD as App
import Part

V = App.Vector

CABLE_DIAMETER = 4.0
MIN_BEND_RADIUS = 12.0
USE_FRENET = True
SHOW_GEOMETRY = True

FAILED_RADIUS_COLOR = (1.0, 0.0, 0.0)
FAILED_LENGTH_COLOR = (1.0, 0.55, 0.0)

SEGMENT_COUNT = 100
ROUTE_EXTENT = 300.0
MIN_SEGMENT_LENGTH = 30.0
RANDOM_SEED = 14

Segment = namedtuple("Segment", ["start", "end"])

TWO_SEGMENTS = [
    Segment(V(0, 0, 0), V(40, 0, 0)),
    Segment(V(55, 15, 5), V(55, 55, 5)),
]

# Colinear-like segments pointing away from each other can produce large loops
COLINEAR_AWAY = [
    Segment(V(1, 0, 0), V(20, 0, 0)),
    Segment(V(4, 0, 11), V(24, 0, 10)),
]


# Colinear-like segments pointing away from each other can produce large loops
COLINEAR_AWAY = [
    Segment(V(1, 0, 0), V(50, 0, 0)),
    Segment(V(90, 0, 11), V(40, 0, 10)),
]



def _unit(vector):
    if vector.Length < 1e-12:
        raise ValueError("Cannot normalize a zero vector")
    return V(vector).normalize()


def _arc_edge(start, end, start_tangent):
    chord = end - start
    chord_length = chord.Length
    if chord_length < 1e-9:
        return None

    cross = chord.cross(start_tangent)
    offset = cross.Length
    if offset < 1e-9 * max(1.0, chord_length):
        return Part.makeLine(start, end)

    normal = _unit(start_tangent.cross(cross))
    radius = chord_length * chord_length / (2.0 * offset)
    center = start + normal * radius

    radial_start = start - center
    radial_end = end - center
    axis = _unit(radial_start.cross(start_tangent))

    angle = radial_start.getAngle(radial_end)
    if radial_start.cross(radial_end).dot(axis) < 0.0:
        angle = 2.0 * math.pi - angle

    circle = Part.Circle(center, axis, radius)
    circle.XAxis = _unit(radial_start)
    return Part.ArcOfCircle(circle, 0.0, angle).toShape()


def _biarc(start, start_tangent, end, end_tangent):
    tangent_start = _unit(start_tangent)
    tangent_end = _unit(end_tangent)

    chord = end - start
    tangent_sum = tangent_start + tangent_end

    chord_length_sq = chord.dot(chord)
    if chord_length_sq < 1e-18:
        return [], start, tangent_start

    dot_product = chord.dot(tangent_sum)
    constant = tangent_sum.dot(tangent_sum) - 4.0
    discriminant = max(
        0.0,
        4.0 * (dot_product * dot_product - chord_length_sq * constant),
    )

    inverse_joint_scale = (
        2.0 * dot_product + math.sqrt(discriminant)
    ) / (2.0 * chord_length_sq)
    if abs(inverse_joint_scale) < 1e-18:
        chord_len = math.sqrt(chord_length_sq)
        arcs = [_arc_edge(start, end, tangent_start)]
        if arcs[0] is None:
            arcs = [Part.makeLine(start, end)]
        return [a for a in arcs if a is not None], start + tangent_start * chord_len * 0.5, tangent_start

    try:
        joint_tangent = _unit(chord * inverse_joint_scale - tangent_sum)
    except Exception:
        chord_len = math.sqrt(chord_length_sq)
        arcs = [_arc_edge(start, end, tangent_start)]
        if arcs[0] is None:
            arcs = [Part.makeLine(start, end)]
        return [a for a in arcs if a is not None], start + tangent_start * chord_len * 0.5, tangent_start

    joint_scale = 1.0 / inverse_joint_scale
    joint = start + (tangent_start + joint_tangent) * joint_scale

    arcs = [
        _arc_edge(start, joint, tangent_start),
        _arc_edge(joint, end, joint_tangent),
    ]
    return [arc for arc in arcs if arc is not None], joint, joint_tangent


def random_segments(
    count=SEGMENT_COUNT,
    extent=ROUTE_EXTENT,
    min_length=MIN_SEGMENT_LENGTH,
    seed=None,
):
    generator = random.Random(seed)
    segments = []

    while len(segments) < count:
        start = V(
            generator.uniform(-extent, extent),
            generator.uniform(-extent, extent),
            generator.uniform(-extent, extent),
        )
        end = V(
            generator.uniform(-extent, extent),
            generator.uniform(-extent, extent),
            generator.uniform(-extent, extent),
        )
        if (end - start).Length < min_length:
            continue
        segments.append(Segment(start, end))

    return segments


def build_route(segments):
    pieces = []
    joints = []

    for index, segment in enumerate(segments):
        direction = _unit(segment.end - segment.start)

        if index:
            previous = segments[index - 1]
            gap = (segment.start - previous.end).Length
            if gap > 1e-9:
                previous_direction = _unit(previous.end - previous.start)
                chord_start = previous.end
                chord_end = segment.start
                chord_len = (chord_end - chord_start).Length
                arcs, joint, _ = _biarc(
                    chord_start,
                    previous_direction,
                    chord_end,
                    direction,
                )
                joints.append(joint)
                biarc_total_len = sum(arc.Length for arc in arcs)
                is_bad_biarc = False
                if chord_len > 1e-12:
                    if biarc_total_len > 2.0 * math.pi * chord_len + 1e-9:
                        is_bad_biarc = True
                for arc_index, arc in enumerate(arcs, start=1):
                    is_bad_radius = False
                    arc_radius = _bend_radius(arc)
                    if arc_radius is not None and arc_radius < MIN_BEND_RADIUS - 1e-9:
                        is_bad_radius = True

                    fail_reason = None
                    if is_bad_radius:
                        fail_reason = "radius"
                    elif is_bad_biarc:
                        fail_reason = "length"

                    pieces.append(
                        (
                            f"Bi-arc {index}.{arc_index}",
                            arc,
                            is_bad_biarc,
                            biarc_total_len,
                            chord_len,
                            arc,
                            is_bad_radius,
                            fail_reason,
                        )
                    )

        pieces.append(
            (
                f"Segment {index + 1}",
                Part.makeLine(segment.start, segment.end),
                False,
                None,
                None,
                None,
                False,
                None,
            )
        )

    path = Part.Wire([item[1] for item in pieces])
    return path, pieces, joints


def _bend_radius(edge):
    curve = edge.Curve
    if isinstance(curve, Part.Circle):
        return curve.Radius

    first = edge.FirstParameter
    last = edge.LastParameter
    max_curvature = 0.0
    for step in range(1, 9):
        parameter = first + (last - first) * step / 9.0
        max_curvature = max(max_curvature, abs(edge.curvatureAt(parameter)))

    if max_curvature < 1e-12:
        return None
    return 1.0 / max_curvature


def measure(pieces):
    total_length = 0.0
    minimum_radius = None
    details = []

    for item in pieces:
        label, edge = item[0], item[1]
        length = edge.Length
        radius = _bend_radius(edge)
        total_length += length
        if radius is not None:
            if minimum_radius is None:
                minimum_radius = radius
            else:
                minimum_radius = min(minimum_radius, radius)
        details.append((label, length, radius))

    return total_length, minimum_radius, details


def make_cable(path, diameter, frenet=USE_FRENET):
    first_edge = path.Edges[0]
    start = first_edge.valueAt(first_edge.FirstParameter)
    tangent = first_edge.tangentAt(first_edge.FirstParameter)
    profile = Part.Wire([Part.Circle(start, tangent, diameter / 2.0).toShape()])
    return path.makePipeShell([profile], True, frenet, 0)


def show(path, cable, pieces=None, diameter=CABLE_DIAMETER):
    if not getattr(App, "GuiUp", False):
        return None, None

    document = App.ActiveDocument
    if document is None:
        document = App.newDocument("PoC_BiarcSweep")

    for obj in list(document.Objects):
        if obj.Name.startswith("PoC_"):
            document.removeObject(obj.Name)

    route_object = document.addObject("Part::Feature", "PoC_Route")
    route_object.Shape = path
    cable_object = document.addObject("Part::Feature", "PoC_Cable")
    cable_object.Shape = cable

    route_object.ViewObject.LineColor = (0.85, 0.1, 0.1)
    route_object.ViewObject.LineWidth = 4
    cable_object.ViewObject.ShapeColor = (0.2, 0.45, 0.8)
    cable_object.ViewObject.Transparency = 20

    if pieces is not None:
        for item in pieces:
            if len(item) >= 8:
                label, edge, is_bad, biarc_total_len, chord_len, arc_shape, is_bad_radius, fail_reason = (
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                    item[4],
                    item[5],
                    item[6],
                    item[7],
                )
            elif len(item) >= 6:
                label, edge, is_bad, biarc_total_len, chord_len, arc_shape = (
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                    item[4],
                    item[5],
                )
                arc_radius = _bend_radius(arc_shape) if arc_shape is not None else _bend_radius(edge)
                is_bad_radius = arc_radius is not None and arc_radius < MIN_BEND_RADIUS - 1e-9
                if is_bad_radius:
                    fail_reason = "radius"
                elif is_bad:
                    fail_reason = "length"
                else:
                    fail_reason = None
            elif len(item) == 5:
                label, edge, is_bad, biarc_total_len, chord_len = (
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                    item[4],
                )
                arc_shape = edge
                arc_radius = _bend_radius(arc_shape)
                is_bad_radius = arc_radius is not None and arc_radius < MIN_BEND_RADIUS - 1e-9
                if is_bad_radius:
                    fail_reason = "radius"
                elif is_bad:
                    fail_reason = "length"
                else:
                    fail_reason = None
            elif len(item) == 2:
                label, edge = item[0], item[1]
                is_bad = False
                arc_shape = edge
                fail_reason = None
            else:
                continue
            if fail_reason is not None and label.startswith("Bi-arc"):
                failed_edge = arc_shape if arc_shape is not None else edge
                color = FAILED_RADIUS_COLOR if fail_reason == "radius" else FAILED_LENGTH_COLOR
                try:
                    failed_shape = failed_edge
                    if hasattr(failed_shape, "Edges") and len(failed_shape.Edges) > 0:
                        edge = failed_shape.Edges[0]
                    elif hasattr(failed_shape, "Wires") and len(failed_shape.Wires) > 0 and failed_shape.Wires[0].Edges:
                        edge = failed_shape.Wires[0].Edges[0]
                    else:
                        edge = failed_shape
                    start = edge.valueAt(edge.FirstParameter)
                    tangent = edge.tangentAt(edge.FirstParameter)
                    failed_diameter = diameter * 1.05
                    profile = Part.Wire([Part.Circle(start, tangent, failed_diameter / 2.0).toShape()])
                    edge_wire = Part.Wire([edge])
                    failed_cable = edge_wire.makePipeShell([profile], True, USE_FRENET, 0)
                    obj = document.addObject("Part::Feature", "PoC_Failed_" + label.replace(" ", "_").replace(".", "_"))
                    obj.Shape = failed_cable
                    obj.ViewObject.ShapeColor = color
                    obj.ViewObject.Transparency = 0
                except Exception:
                    obj = document.addObject("Part::Feature", "PoC_Failed_" + label.replace(" ", "_").replace(".", "_"))
                    try:
                        failed_shape = failed_edge
                        if hasattr(failed_shape, "Edges") and len(failed_shape.Edges) > 0:
                            edge = failed_shape.Edges[0]
                        elif hasattr(failed_shape, "Wires") and len(failed_shape.Wires) > 0 and failed_shape.Wires[0].Edges:
                            edge = failed_shape.Wires[0].Edges[0]
                        else:
                            edge = failed_shape
                        start = edge.valueAt(edge.FirstParameter)
                        tangent = edge.tangentAt(edge.FirstParameter)
                        failed_diameter = diameter * 1.05
                        profile = Part.Wire([Part.Circle(start, tangent, failed_diameter / 2.0).toShape()])
                        edge_wire = Part.Wire([edge])
                        failed_cable = edge_wire.makePipeShell([profile], True, USE_FRENET, 0)
                        obj.Shape = failed_cable
                        obj.ViewObject.ShapeColor = color
                    except Exception:
                        obj.Shape = failed_edge
                        try:
                            obj.ViewObject.LineColor = color
                            obj.ViewObject.LineWidth = 6
                        except Exception:
                            pass

    document.recompute()

    import FreeCADGui as Gui

    Gui.activeDocument().activeView().fitAll()
    return route_object, cable_object


def main(
    segments=None,
    diameter=CABLE_DIAMETER,
    min_bend_radius=MIN_BEND_RADIUS,
    show_geometry=SHOW_GEOMETRY,
):
    if segments is None:
        segments = random_segments(seed=RANDOM_SEED)

    path, pieces, joints = build_route(segments)
    total_length, minimum_radius, details = measure(pieces)
    cable = make_cable(path, diameter)

    print("=== FreeCAD Bi-arc Cable Routing PoC ===")
    print(f"Route                   : {len(segments)} segments, {len(joints)} bi-arcs")
    for label, length, radius in details:
        radius_text = "straight" if radius is None else f"R = {radius:.3f} mm"
        print(f"  {label:<14} length = {length:9.3f} mm   {radius_text}")

    for index, joint in enumerate(joints, start=1):
        print(
            f"  Bi-arc {index} joint = "
            f"({joint.x:.3f}, {joint.y:.3f}, {joint.z:.3f}) mm"
        )

    print(f"Total path length       : {total_length:.3f} mm")
    if minimum_radius is None:
        print("Minimum bending radius  : infinite (no curved edges)")
    else:
        print(f"Minimum bending radius  : {minimum_radius:.3f} mm")
        if min_bend_radius is not None:
            status = (
                "OK"
                if minimum_radius >= min_bend_radius
                else "WARNING: below minimum"
            )
            print(f"Minimum allowed radius  : {min_bend_radius:.3f} mm  -> {status}")

    expected_volume = total_length * math.pi * (diameter / 2.0) ** 2
    ratio = cable.Volume / expected_volume if expected_volume > 0.0 else 0.0
    box = cable.BoundBox
    print(f"Path wire valid         : {path.isValid()}")
    print(
        "Cable bound box         : "
        f"({box.XMin:.1f}, {box.YMin:.1f}, {box.ZMin:.1f}) .. "
        f"({box.XMax:.1f}, {box.YMax:.1f}, {box.ZMax:.1f}) mm"
    )
    print(f"Cable diameter          : {diameter:.3f} mm")
    print(f"Cable solid valid       : {cable.isValid()}")
    print(f"Cable solid volume      : {cable.Volume:.3f} mm^3")
    print(f"Expected sweep volume   : {expected_volume:.3f} mm^3  (ratio {ratio:.4f})")

    bad_biarcs = []
    for item in pieces:
        if len(item) >= 5:
            label, edge, is_bad, biarc_total_len, chord_len = item[0], item[1], item[2], item[3], item[4]
            if is_bad:
                bad_biarcs.append((label, biarc_total_len, chord_len, biarc_total_len - chord_len))
    if bad_biarcs:
        print("WARNING: Bad bi-arcs detected (> chord + 2*pi):")
        for label, b, c, excess in bad_biarcs:
            print(f"  {label}: biarc={b:.3f} mm, chord={c:.3f} mm, excess={excess:.3f} mm")

    if show_geometry:
        show(path, cable, pieces=pieces, diameter=diameter)

    return path, cable


def _running_as_script():
    if __name__ == "__main__":
        return True
    script = globals().get("__file__")
    if not script:
        return False
    script = os.path.abspath(script)
    return any(os.path.abspath(argument) == script for argument in sys.argv)


if _running_as_script():
    main(COLINEAR_AWAY)
