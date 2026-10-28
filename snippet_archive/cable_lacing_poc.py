"""PoC: place segmented lacing-thread wires on the bundle surface.

Each lacing section is a straight FreeCAD wire (a plain Part::Feature), not a
VibeWire cable. Sections are 6 * bundle-segment radius long and are separated
by a 2 mm axial gap. The wires are offset from the segment centerline to the
outer surface of the cable bundle.

Run in FreeCAD after opening CableWrappingPoC.FCStd:

    import sys
    sys.path.insert(0, "/home/mx/opencaudetest/WirePlugin-main/snippet_archive")
    from cable_lacing_poc import create_lacing_threads
    harness = App.ActiveDocument.getObject("WireHarness")
    create_lacing_threads(harness.Segments[0])
"""

import math

import FreeCAD as App
import Part

SECTION_FACTOR = 1.0
SECTION_GAP = 2.0
HELPER_LENGTH = 1.0
MIN_BEND_RADIUS = 10.0
KNOT_ALONG = 0.5
KNOT_INWARD = 0.5
KNOT_TANGENTIAL = 0.5


def lacing_sections(length, od, gap=SECTION_GAP, factor=SECTION_FACTOR):
    """Return centered (start, end) axial spans for full lacing sections."""
    section_length = factor * od
    if section_length <= 0.0:
        raise ValueError("Bundle segment outside diameter must be positive")

    step = section_length + gap
    count = int(math.floor((length + gap) / step))
    if count < 1:
        return []

    covered = count * section_length + (count - 1) * gap
    margin = (length - covered) / 2.0
    return [
        (margin + index * step, margin + index * step + section_length)
        for index in range(count)
    ]


def _harness_for_segment(segment):
    for parent in segment.InList:
        if getattr(getattr(parent, "Proxy", None), "Type", None) in (
            "WireHarness",
            "WireBundle",
        ):
            return parent
    return None


def _bundle_outer_radius(segment):
    """Bundle envelope radius for this segment, or its display radius."""
    harness = _harness_for_segment(segment)
    if harness is None:
        return segment.Radius.Value

    max_offset = 0.0
    max_cable_radius = 0.0
    for cable in harness.InList:
        if getattr(getattr(cable, "Proxy", None), "Type", None) != "WireCable":
            continue
        raw = harness.Layout.get("{}|{}".format(segment.Name, cable.Name))
        if not raw:
            continue
        offset = App.Vector(*[float(value) for value in raw.split(",")])
        max_offset = max(max_offset, offset.Length)
        max_cable_radius = max(
            max_cable_radius,
            max(0.0, cable.Diameter.Value) / 2.0,
        )

    if max_offset <= 0.0:
        return segment.Radius.Value
    return max_offset + max_cable_radius


def _surface_direction(segment, angle):
    from VibeWire.WireBundle import segment_basis

    side, normal = segment_basis(segment)
    return side * math.cos(angle) + normal * math.sin(angle)


def _segment_frame(segment):
    start = segment.Start.getGlobalPlacement().Base
    end = segment.End.getGlobalPlacement().Base
    axis = end - start
    length = axis.Length
    if length < 1e-9:
        raise ValueError("Bundle segment has identical start and end points")
    return start, axis / length, length


def knot_point(
    segment,
    point,
    along=KNOT_ALONG,
    inward=KNOT_INWARD,
    tangential=KNOT_TANGENTIAL,
    rotation_sign=1.0,
):
    """Offset a surface point inward, forward and around the bundle axis."""
    start, direction, _length = _segment_frame(segment)
    relative = point - start
    axial = relative.dot(direction)
    radial = relative - direction * axial
    radius = radial.Length
    if radius < 1e-9:
        raise ValueError("Knot point must not lie on the segment axis")

    radial_direction = radial / radius
    new_radius = max(0.0, radius - inward)
    angle = rotation_sign * tangential / max(new_radius, 1e-9)
    rotated = App.Rotation(direction, math.degrees(angle)).multVec(
        radial_direction
    )
    return start + direction * (axial + along) + rotated * new_radius


def _append_lacing_edges(segment, index, new_edges):
    document = segment.Document
    group = document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")

    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    obj = objects[index]
    edges = list(obj.Shape.Edges)
    if not edges:
        raise ValueError("Lacing wire has no edges")

    obj.Shape = Part.Wire(edges + list(new_edges))
    document.recompute()
    return obj


def _append_lacing_end(segment, index, new_point):
    group = segment.Document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")
    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    obj = objects[index]
    edges = list(obj.Shape.Edges)
    if not edges:
        raise ValueError("Lacing wire has no edges")

    last_edge = edges[-1]
    end_point = last_edge.valueAt(last_edge.LastParameter)
    obj = _append_lacing_edges(
        segment,
        index,
        [Part.makeLine(end_point, new_point)],
    )
    return new_point, obj


def extend_lacing_end_with_knot(
    segment,
    index=0,
    along=KNOT_ALONG,
    inward=KNOT_INWARD,
    tangential=KNOT_TANGENTIAL,
    rotation_sign=1.0,
):
    """Append a knot edge from the selected lacing wire's end point."""
    group = segment.Document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")
    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    obj = objects[index]
    edges = list(obj.Shape.Edges)
    if not edges:
        raise ValueError("Lacing wire has no edges")
    end_point = edges[-1].valueAt(edges[-1].LastParameter)
    new_point = knot_point(
        segment,
        end_point,
        along=along,
        inward=inward,
        tangential=tangential,
        rotation_sign=rotation_sign,
    )
    return _append_lacing_end(segment, index, new_point)


def extend_lacing_end_relative(
    segment,
    index=0,
    along=0.0,
    radial=0.0,
    tangential=0.0,
    rotation_sign=1.0,
):
    """Append a point using outward radial, axial and tangential offsets."""
    group = segment.Document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")
    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    obj = objects[index]
    edges = list(obj.Shape.Edges)
    if not edges:
        raise ValueError("Lacing wire has no edges")
    end_point = edges[-1].valueAt(edges[-1].LastParameter)
    new_point = knot_point(
        segment,
        end_point,
        along=along,
        inward=-radial,
        tangential=tangential,
        rotation_sign=rotation_sign,
    )
    return _append_lacing_end(segment, index, new_point)


def extend_lacing_end_helix(
    segment,
    index=0,
    turns=1.0,
    axial=0.5,
    rotation_sign=1.0,
):
    """Append a helical turn around the bundle from the lacing wire's end."""
    group = segment.Document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")
    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    obj = objects[index]
    edges = list(obj.Shape.Edges)
    if not edges:
        raise ValueError("Lacing wire has no edges")

    end_point = edges[-1].valueAt(edges[-1].LastParameter)
    start, direction, _length = _segment_frame(segment)
    relative = end_point - start
    axial_position = relative.dot(direction)
    radial = relative - direction * axial_position
    radius = radial.Length
    if radius < 1e-9:
        raise ValueError("Helix start must not lie on the segment axis")

    x_axis = radial / radius
    y_axis = direction.cross(x_axis) * (1.0 if rotation_sign >= 0 else -1.0)
    origin = end_point - x_axis * radius

    transform = App.Matrix()
    transform.A11, transform.A12, transform.A13, transform.A14 = (
        x_axis.x,
        y_axis.x,
        direction.x,
        origin.x,
    )
    transform.A21, transform.A22, transform.A23, transform.A24 = (
        x_axis.y,
        y_axis.y,
        direction.y,
        origin.y,
    )
    transform.A31, transform.A32, transform.A33, transform.A34 = (
        x_axis.z,
        y_axis.z,
        direction.z,
        origin.z,
    )

    turns = max(1e-9, float(turns))
    helix = Part.makeHelix(axial / turns, axial, radius)
    helix.transformShape(transform)
    obj = _append_lacing_edges(segment, index, helix.Edges)
    return end_point + direction * axial, obj


def connect_lacing_to_next_section(segment, index=0):
    """Connect the selected lacing wire's end to the next section's start."""
    group = segment.Document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")
    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    if index + 1 >= len(objects):
        raise ValueError("There is no following lacing section")

    obj = objects[index]
    next_obj = objects[index + 1]
    edges = list(obj.Shape.Edges)
    next_edges = list(next_obj.Shape.Edges)
    if not edges or not next_edges:
        raise ValueError("Lacing wire has no edges")

    end_point = edges[-1].valueAt(edges[-1].LastParameter)
    next_start = next_edges[0].valueAt(next_edges[0].FirstParameter)
    obj = _append_lacing_edges(
        segment,
        index,
        [Part.makeLine(end_point, next_start)],
    )
    return next_start, obj


def _fillet_wire(wire, radius=0.2):
    """Round the vertices of a 3D wire with tangent arcs."""
    from VibeWire.WireTransitions import arc_edge

    edges = list(wire.Edges)
    if len(edges) < 2 or radius <= 0.0:
        return wire

    lengths = [edge.Length for edge in edges]
    trim_start = [0.0] * len(edges)
    trim_end = [0.0] * len(edges)

    for index in range(len(edges) - 1):
        tangent_in = edges[index].tangentAt(edges[index].LastParameter)
        tangent_out = edges[index + 1].tangentAt(
            edges[index + 1].FirstParameter
        )
        dot = max(-1.0, min(1.0, tangent_in.dot(tangent_out)))
        angle = math.acos(dot)
        if angle < 1e-6 or angle > math.pi - 1e-6:
            continue
        trim = radius * math.tan(angle / 2.0)
        trim = min(trim, 0.45 * lengths[index], 0.45 * lengths[index + 1])
        if trim < 1e-3:
            continue
        trim_end[index] = max(trim_end[index], trim)
        trim_start[index + 1] = max(trim_start[index + 1], trim)

    trimmed = []
    for index, edge in enumerate(edges):
        start_trim = trim_start[index]
        end_trim = trim_end[index]
        if start_trim + end_trim >= edge.Length:
            start_trim = end_trim = 0.0
        start_param = (
            edge.getParameterByLength(start_trim)
            if start_trim > 0.0
            else edge.FirstParameter
        )
        end_param = (
            edge.getParameterByLength(-end_trim)
            if end_trim > 0.0
            else edge.LastParameter
        )
        trimmed.append(edge.Curve.toShape(start_param, end_param))

    result = []
    for index, edge in enumerate(trimmed):
        result.append(edge)
        if index >= len(trimmed) - 1:
            continue
        start_point = edge.valueAt(edge.LastParameter)
        end_point = trimmed[index + 1].valueAt(
            trimmed[index + 1].FirstParameter
        )
        if (end_point - start_point).Length < 1e-9:
            continue
        start_tangent = edge.tangentAt(edge.LastParameter)
        arc = arc_edge(start_point, end_point, start_tangent)
        if arc is not None:
            result.append(arc)

    filleted = Part.Wire(result)
    if not filleted.isValid():
        raise ValueError("Filleted lacing wire is not valid")
    return filleted


def fillet_lacing_wire(segment, index=0, radius=0.2):
    """Create a filleted copy of one lacing wire."""
    group = segment.Document.getObject("LacingThreads_{}".format(segment.Name))
    if group is None or not group.Group:
        raise ValueError("No lacing wires exist for this segment")
    objects = list(group.Group)
    if index < 0:
        index += len(objects)
    wire = objects[index].Shape

    document = segment.Document
    fillet_group_name = "LacingFillets_{}".format(segment.Name)
    fillet_group = document.getObject(fillet_group_name)
    if fillet_group is not None:
        for obj in list(fillet_group.Group):
            if obj.Document is document:
                document.removeObject(obj.Name)
        document.removeObject(fillet_group.Name)

    fillet_group = document.addObject(
        "App::DocumentObjectGroup", fillet_group_name
    )
    fillet_group.Label = "Lacing Fillets - {}".format(segment.Label)

    obj = document.addObject(
        "Part::Feature",
        "LacingFillet_{}_{:02d}".format(segment.Name, index + 1),
    )
    obj.Label = "Lacing Fillet {} {:02d}".format(segment.Label, index + 1)
    obj.Shape = _fillet_wire(wire, radius)
    try:
        obj.ViewObject.LineColor = (0.20, 0.45, 0.85)
        obj.ViewObject.LineWidth = 2.0
    except Exception:
        pass
    fillet_group.addObject(obj)
    document.recompute()
    return obj


def sweep_lacing_wire(
    segment,
    index=0,
    diameter=0.5,
    fillet_radius=0.2,
    use_frenet=True,
):
    """Fillet one lacing wire, then sweep a circular profile along it."""
    fillet_obj = fillet_lacing_wire(segment, index=index, radius=fillet_radius)
    wire = fillet_obj.Shape
    if not wire.Edges:
        raise ValueError("Filleted lacing wire has no edges")

    first_edge = wire.Edges[0]
    start = first_edge.valueAt(first_edge.FirstParameter)
    tangent = first_edge.tangentAt(first_edge.FirstParameter)
    profile = Part.Wire(
        [Part.Circle(start, tangent, diameter / 2.0).toShape()]
    )
    solid = wire.makePipeShell([profile], True, use_frenet, 0)

    document = segment.Document
    sweep_group_name = "LacingSweeps_{}".format(segment.Name)
    sweep_group = document.getObject(sweep_group_name)
    if sweep_group is not None:
        for obj in list(sweep_group.Group):
            if obj.Document is document:
                document.removeObject(obj.Name)
        document.removeObject(sweep_group.Name)

    sweep_group = document.addObject(
        "App::DocumentObjectGroup", sweep_group_name
    )
    sweep_group.Label = "Lacing Sweeps - {}".format(segment.Label)

    obj = document.addObject(
        "Part::Feature",
        "LacingSweep_{}_{:02d}".format(segment.Name, index + 1),
    )
    obj.Label = "Lacing Sweep {} {:02d}".format(segment.Label, index + 1)
    obj.Shape = solid
    try:
        obj.ViewObject.ShapeColor = (0.32, 0.18, 0.07)
        obj.ViewObject.Transparency = 0
    except Exception:
        pass
    sweep_group.addObject(obj)
    document.recompute()
    return obj


def create_lacing_threads(
    segment,
    gap=SECTION_GAP,
    factor=SECTION_FACTOR,
    surface_angle=0.0,
    surface_offset=0.0,
):
    """Create straight lacing wires on the surface of one bundle segment.

    Existing lacing objects created for this segment are replaced.
    """
    if segment is None or segment.Document is None:
        raise ValueError("A valid bundle segment is required")
    if not getattr(segment, "Start", None) or not getattr(segment, "End", None):
        raise ValueError("Bundle segment needs start and end references")

    document = segment.Document
    start = segment.Start.getGlobalPlacement().Base
    end = segment.End.getGlobalPlacement().Base
    axis = end - start
    length = axis.Length
    if length < 1e-9:
        raise ValueError("Bundle segment has identical start and end points")
    direction = axis / length

    group_name = "LacingThreads_{}".format(segment.Name)
    group = document.getObject(group_name)
    if group is not None:
        for obj in list(group.Group):
            if obj.Document is document:
                document.removeObject(obj.Name)
        document.removeObject(group.Name)

    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Lacing Threads - {}".format(segment.Label)

    surface_radius = _bundle_outer_radius(segment) + surface_offset
    surface_shift = _surface_direction(segment, surface_angle) * surface_radius

    objects = []
    for index, (section_start, section_end) in enumerate(
        lacing_sections(length, 2.0 * _bundle_outer_radius(segment), gap, factor),
        start=1,
    ):
        section_start_point = (
            start + direction * section_start + surface_shift
        )
        section_end_point = start + direction * section_end + surface_shift
        wire = Part.Wire(
            [Part.makeLine(section_start_point, section_end_point)]
        )

        obj = document.addObject(
            "Part::Feature",
            "Lacing_{}_{:02d}".format(segment.Name, index),
        )
        obj.Label = "Lacing {} {:02d}".format(segment.Label, index)
        obj.Shape = wire
        try:
            obj.ViewObject.LineColor = (0.28, 0.16, 0.06)
            obj.ViewObject.LineWidth = 2.0
        except Exception:
            pass
        group.addObject(obj)
        objects.append(obj)

    document.recompute()
    return objects


def build_lacing_knot(
    segment,
    index=0,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
    fillet_radius=0.2,
    diameter=0.5,
):
    """Rebuild the knot control points and return the filleted sweep."""
    create_lacing_threads(segment)
    extend_lacing_end_relative(
        segment,
        index=index,
        along=s1c_axial,
        radial=s1c_radial,
        tangential=s1c_tangential,
    )
    extend_lacing_end_relative(
        segment, index=index, along=0.5, radial=0.5, tangential=0.0
    )
    extend_lacing_end_relative(
        segment, index=index, along=0.5, radial=0.5, tangential=-0.5
    )
    extend_lacing_end_relative(
        segment, index=index, along=-0.5, radial=-0.5, tangential=-0.5
    )
    extend_lacing_end_relative(
        segment, index=index, along=-0.5, radial=0.5, tangential=0.5
    )
    extend_lacing_end_helix(
        segment, index=index, turns=1.0, axial=0.5
    )
    extend_lacing_end_relative(
        segment, index=index, along=0.5, radial=-0.5, tangential=0.0
    )
    connect_lacing_to_next_section(segment, index=index)
    return sweep_lacing_wire(
        segment,
        index=index,
        diameter=diameter,
        fillet_radius=fillet_radius,
        use_frenet=True,
    )


def apply_knot_sequence(
    segment,
    index=0,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
):
    """Apply the knot control-point sequence to one lacing section."""
    extend_lacing_end_relative(
        segment,
        index=index,
        along=s1c_axial,
        radial=s1c_radial,
        tangential=s1c_tangential,
    )
    extend_lacing_end_relative(
        segment, index=index, along=0.5, radial=0.5, tangential=0.0
    )
    extend_lacing_end_relative(
        segment, index=index, along=0.5, radial=0.5, tangential=-0.5
    )
    extend_lacing_end_relative(
        segment, index=index, along=-0.5, radial=-0.5, tangential=-0.5
    )
    extend_lacing_end_relative(
        segment, index=index, along=-0.5, radial=0.5, tangential=0.5
    )
    extend_lacing_end_helix(
        segment, index=index, turns=1.0, axial=0.5
    )
    _point, obj = extend_lacing_end_relative(
        segment, index=index, along=0.5, radial=-0.5, tangential=0.0
    )
    return obj


def solve_bundle_path(harness, min_bend_radius=MIN_BEND_RADIUS):
    """Solve the harness centerline, including the bends between segments."""
    from VibeWire.WireCreator import Segment, WireCreator

    route = []
    for segment in harness.Segments:
        start = segment.Start.getGlobalPlacement().Base
        end = segment.End.getGlobalPlacement().Base
        route.append(Segment(start, end))
    creator = WireCreator(min_bend_radius=min_bend_radius)
    return creator.create_wire(route)


def _rotate_between(from_tangent, to_tangent, vector):
    axis = from_tangent.cross(to_tangent)
    if axis.Length < 1e-9:
        return vector
    axis.normalize()
    dot = max(-1.0, min(1.0, from_tangent.dot(to_tangent)))
    angle = math.degrees(math.acos(dot))
    return App.Rotation(axis, angle).multVec(vector)


def _safe_remove_group(document, name):
    group = document.getObject(name)
    if group is None:
        return
    child_names = []
    for child in list(getattr(group, "Group", [])):
        try:
            child_names.append(child.Name)
        except ReferenceError:
            continue
    for child_name in child_names:
        if document.getObject(child_name) is not None:
            document.removeObject(child_name)
    if document.getObject(name) is not None:
        document.removeObject(name)


def _odd_helper_count(length, segment_length):
    if segment_length <= 0.0:
        raise ValueError("Helper segment length must be positive")
    raw = length / segment_length
    count = int(math.floor(raw + 0.5))
    if count < 1:
        count = 1
    if count % 2 == 0:
        count += 1 if raw > count else -1
    if count < 1:
        count = 1
    return count


def _arc_helper_segments(edge, segment_length):
    length = edge.Length
    count = _odd_helper_count(length, segment_length)
    segments = []
    for index in range(count):
        distance = length * (index + 0.5) / count
        parameter = edge.getParameterByLength(distance)
        center = edge.valueAt(parameter)
        tangent = edge.tangentAt(parameter)
        if tangent.Length < 1e-9:
            continue
        segments.append(
            {
                "center": center,
                "tangent": tangent.normalize(),
                "distance": distance,
            }
        )
    return segments


def make_bend_helpers(
    harness,
    helper_length=HELPER_LENGTH,
    min_bend_radius=MIN_BEND_RADIUS,
    surface_angle=0.0,
):
    """Create odd-count, joint-shared helper cylinders along each bi-arc."""
    document = harness.Document
    segments = [segment for segment in harness.Segments if segment is not None]
    if len(segments) < 2:
        return []

    solved = solve_bundle_path(harness, min_bend_radius=min_bend_radius)
    bends = []
    current = []
    for edge in solved.Edges:
        if isinstance(edge.Curve, Part.Circle):
            current.append(edge)
        elif current:
            bends.append(current)
            current = []
    if current:
        bends.append(current)

    group_name = "BendHelpers_{}".format(harness.Name)
    _safe_remove_group(document, group_name)
    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Bend Helpers - {}".format(harness.Label)

    result = []
    for bend_index, bend_edges in enumerate(bends):
        if bend_index >= len(segments) - 1:
            break
        start_segment = segments[bend_index]
        end_segment = segments[bend_index + 1]
        radius = max(
            _bundle_outer_radius(start_segment),
            _bundle_outer_radius(end_segment),
        )

        records = []
        for arc_index, arc in enumerate(bend_edges):
            if arc_index > 0:
                joint_tangent = arc.tangentAt(arc.FirstParameter)
                if joint_tangent.Length > 1e-9:
                    records.append(
                        {
                            "center": arc.valueAt(arc.FirstParameter),
                            "tangent": joint_tangent.normalize(),
                            "joint": True,
                        }
                    )
            records.extend(_arc_helper_segments(arc, helper_length))

        for segment_index, record in enumerate(records, start=1):
            center = record["center"]
            tangent = record["tangent"]
            cylinder = Part.makeCylinder(
                radius,
                helper_length,
                center - tangent * (helper_length / 2.0),
                tangent,
            )
            obj = document.addObject(
                "Part::Feature",
                "BendHelper_{:02d}_{:02d}".format(
                    bend_index + 1, segment_index
                ),
            )
            obj.Label = "Bend Helper {:02d}.{:02d}".format(
                bend_index + 1, segment_index
            )
            obj.Shape = cylinder
            try:
                obj.ViewObject.ShapeColor = (1.0, 0.0, 0.0)
                obj.ViewObject.Transparency = 75
            except Exception:
                pass
            group.addObject(obj)

        radial = _surface_direction(start_segment, surface_angle)
        previous_tangent = None
        surface_points = []
        tangents = []
        radials = []
        for record in records:
            tangent = record["tangent"]
            if previous_tangent is not None:
                radial = _rotate_between(previous_tangent, tangent, radial)
                if radial.Length < 1e-9:
                    radial = _surface_direction(start_segment, surface_angle)
                else:
                    radial = radial.normalize()
            previous_tangent = tangent
            surface_points.append(record["center"] + radial * radius)
            tangents.append(tangent)
            radials.append(radial)

        result.append(
            {
                "start_segment": start_segment,
                "end_segment": end_segment,
                "radius": radius,
                "helper_segments": records,
                "surface_points": surface_points,
                "tangents": tangents,
                "radials": radials,
            }
        )
    return result


def _offset_in_frame(
    point,
    tangent,
    radial_dir,
    radius,
    along=0.0,
    radial=0.0,
    tangential=0.0,
    rotation_sign=1.0,
):
    new_radius = max(0.0, radius + radial)
    angle = math.degrees(
        rotation_sign * tangential / max(new_radius, 1e-9)
    )
    rotated = App.Rotation(tangent, angle).multVec(radial_dir)
    if rotated.Length < 1e-9:
        rotated = radial_dir
    else:
        rotated = rotated.normalize()
    new_point = (
        point
        + tangent * along
        + rotated * new_radius
        - radial_dir * radius
    )
    return new_point, rotated, new_radius


def _helix_edges_in_frame(point, tangent, radial_dir, radius, axial, turns=1.0):
    y_axis = tangent.cross(radial_dir)
    if y_axis.Length < 1e-9:
        raise ValueError("Cannot build a helix on this frame")
    y_axis = y_axis.normalize()
    origin = point - radial_dir * radius

    transform = App.Matrix()
    transform.A11, transform.A12, transform.A13, transform.A14 = (
        radial_dir.x,
        y_axis.x,
        tangent.x,
        origin.x,
    )
    transform.A21, transform.A22, transform.A23, transform.A24 = (
        radial_dir.y,
        y_axis.y,
        tangent.y,
        origin.y,
    )
    transform.A31, transform.A32, transform.A33, transform.A34 = (
        radial_dir.z,
        y_axis.z,
        tangent.z,
        origin.z,
    )

    turns = max(1e-9, float(turns))
    helix = Part.makeHelix(axial / turns, axial, radius)
    helix.transformShape(transform)
    return list(helix.Edges), point + tangent * axial


def _knot_edges_in_frame(
    point,
    tangent,
    radial_dir,
    radius,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
):
    edges = []
    current_point = point
    current_tangent = tangent
    current_radial = radial_dir
    current_radius = radius

    steps = [
        (s1c_axial, s1c_radial, s1c_tangential),
        (0.5, 0.5, 0.0),
        (0.5, 0.5, -0.5),
        (-0.5, -0.5, -0.5),
        (-0.5, 0.5, 0.5),
    ]
    for along, radial, tangential in steps:
        new_point, new_radial, new_radius = _offset_in_frame(
            current_point,
            current_tangent,
            current_radial,
            current_radius,
            along=along,
            radial=radial,
            tangential=tangential,
        )
        edges.append(Part.makeLine(current_point, new_point))
        current_point = new_point
        current_radial = new_radial
        current_radius = new_radius

    helix_edges, helix_end = _helix_edges_in_frame(
        current_point,
        current_tangent,
        current_radial,
        current_radius,
        axial=0.5,
        turns=1.0,
    )
    if helix_edges:
        helix_start = helix_edges[0].valueAt(
            helix_edges[0].FirstParameter
        )
        if (helix_start - current_point).Length > 1e-12:
            if edges:
                previous_edge = edges[-1]
                edge_start = previous_edge.valueAt(
                    previous_edge.FirstParameter
                )
                edges[-1] = Part.makeLine(edge_start, helix_start)
            else:
                edges.append(Part.makeLine(current_point, helix_start))
        edges.extend(helix_edges)
        last_helix = helix_edges[-1]
        current_point = last_helix.valueAt(last_helix.LastParameter)
    else:
        current_point = helix_end

    new_point, new_radial, new_radius = _offset_in_frame(
        current_point,
        current_tangent,
        current_radial,
        current_radius,
        along=0.5,
        radial=-0.5,
        tangential=0.0,
    )
    edges.append(Part.makeLine(current_point, new_point))
    return edges, new_point, current_tangent, new_radial, new_radius


def _polyline_distances(points):
    distances = [0.0]
    for start, end in zip(points, points[1:]):
        distances.append(distances[-1] + (end - start).Length)
    return distances


def _interpolate_polyline(points, distances, distance):
    if distance <= 0.0:
        return App.Vector(points[0])
    if distance >= distances[-1]:
        return App.Vector(points[-1])
    for index in range(len(distances) - 1):
        if distances[index] <= distance <= distances[index + 1]:
            span = distances[index + 1] - distances[index]
            if span < 1e-9:
                return App.Vector(points[index])
            ratio = (distance - distances[index]) / span
            return points[index] + (points[index + 1] - points[index]) * ratio
    return App.Vector(points[-1])


def _frame_at_distance(data, distance):
    points = data["surface_points"]
    distances = _polyline_distances(points)
    if distance <= 0.0:
        index = 0
    elif distance >= distances[-1]:
        index = len(points) - 1
    else:
        index = 0
        for candidate in range(len(distances) - 1):
            if distances[candidate] <= distance <= distances[candidate + 1]:
                index = candidate
                break
    point = _interpolate_polyline(points, distances, distance)
    tangent = data["tangents"][index]
    radial = data["radials"][index]
    return point, tangent, radial, data["radius"]


def _section_edges_along_polyline(points, distances, start_distance, end_distance):
    section_points = [_interpolate_polyline(points, distances, start_distance)]
    for point, distance in zip(points, distances):
        if start_distance + 1e-9 < distance < end_distance - 1e-9:
            section_points.append(point)
    section_points.append(_interpolate_polyline(points, distances, end_distance))

    edges = []
    for start, end in zip(section_points, section_points[1:]):
        if (end - start).Length > 1e-9:
            edges.append(Part.makeLine(start, end))
    return edges


def make_bend_lacing(
    harness,
    bend_data,
    gap=SECTION_GAP,
    factor=SECTION_FACTOR,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
):
    """Create lacing sections and knots along every bend helper path."""
    document = harness.Document
    group_name = "BendLacing_{}".format(harness.Name)
    _safe_remove_group(document, group_name)
    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Bend Lacing - {}".format(harness.Label)

    result = []
    for bend_index, data in enumerate(bend_data):
        points = data["surface_points"]
        if len(points) < 2:
            result.append([])
            continue
        distances = _polyline_distances(points)
        bend_length = distances[-1]
        od = 2.0 * data["radius"]
        spans = lacing_sections(bend_length, od, gap, factor)
        if not spans and bend_length > 1e-9:
            spans = [(0.0, bend_length)]

        edges = []
        previous_end = None
        for start_distance, end_distance in spans:
            section_edges = _section_edges_along_polyline(
                points, distances, start_distance, end_distance
            )
            if not section_edges:
                continue
            section_start = section_edges[0].valueAt(
                section_edges[0].FirstParameter
            )
            if previous_end is not None and (section_start - previous_end).Length > 1e-9:
                edges.append(Part.makeLine(previous_end, section_start))
            edges.extend(section_edges)

            end_point, tangent, radial, radius = _frame_at_distance(
                data, end_distance
            )
            knot_edges, knot_end, _tangent, _radial, _radius = (
                _knot_edges_in_frame(
                    end_point,
                    tangent,
                    radial,
                    radius,
                    s1c_axial=s1c_axial,
                    s1c_radial=s1c_radial,
                    s1c_tangential=s1c_tangential,
                )
            )
            edges.extend(knot_edges)
            previous_end = knot_end

        if edges:
            obj = document.addObject(
                "Part::Feature",
                "BendLacing_{:02d}".format(bend_index + 1),
            )
            obj.Label = "Bend Lacing {:02d}".format(bend_index + 1)
            obj.Shape = Part.Wire(edges)
            try:
                obj.ViewObject.LineColor = (0.20, 0.40, 0.85)
                obj.ViewObject.LineWidth = 2.0
            except Exception:
                pass
            group.addObject(obj)
        result.append(edges)
    return result


def build_continuous_lacing(
    harness,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
    fillet_radius=0.2,
    diameter=0.5,
    helper_length=HELPER_LENGTH,
    min_bend_radius=MIN_BEND_RADIUS,
    surface_angle=0.0,
    section_gap=SECTION_GAP,
    section_factor=SECTION_FACTOR,
    use_bend_helpers=True,
    use_frenet=False,
):
    """Build one continuous lacing path across all harness route segments."""
    document = harness.Document
    document.recompute()
    segments = [segment for segment in harness.Segments if segment is not None]
    bend_data = (
        make_bend_helpers(
            harness,
            helper_length=helper_length,
            min_bend_radius=min_bend_radius,
            surface_angle=surface_angle,
        )
        if use_bend_helpers
        else []
    )
    bend_lacing = (
        make_bend_lacing(
            harness,
            bend_data,
            gap=section_gap,
            factor=section_factor,
            s1c_axial=s1c_axial,
            s1c_radial=s1c_radial,
            s1c_tangential=s1c_tangential,
        )
        if use_bend_helpers
        else []
    )

    for segment in segments:
        create_lacing_threads(
            segment, gap=section_gap, factor=section_factor
        )

    for segment in segments:
        group = document.getObject("LacingThreads_{}".format(segment.Name))
        for index in range(len(group.Group)):
            apply_knot_sequence(
                segment,
                index=index,
                s1c_axial=s1c_axial,
                s1c_radial=s1c_radial,
                s1c_tangential=s1c_tangential,
            )

    combined_edges = []
    previous_end = None
    for route_index, segment in enumerate(segments):
        group = document.getObject("LacingThreads_{}".format(segment.Name))
        for section_index, obj in enumerate(group.Group):
            edges = list(obj.Shape.Edges)
            if not edges:
                continue
            start = edges[0].valueAt(edges[0].FirstParameter)
            if previous_end is not None:
                bend_index = route_index - 1
                bend_edges = (
                    bend_lacing[bend_index]
                    if section_index == 0
                    and route_index > 0
                    and bend_index < len(bend_lacing)
                    else []
                )
                if bend_edges:
                    first_start = bend_edges[0].valueAt(
                        bend_edges[0].FirstParameter
                    )
                    if (first_start - previous_end).Length > 1e-9:
                        combined_edges.append(
                            Part.makeLine(previous_end, first_start)
                        )
                    combined_edges.extend(bend_edges)
                    last_bend = bend_edges[-1]
                    previous_end = last_bend.valueAt(
                        last_bend.LastParameter
                    )
                    if (start - previous_end).Length > 1e-9:
                        combined_edges.append(
                            Part.makeLine(previous_end, start)
                        )
                elif (
                    section_index == 0
                    and route_index > 0
                    and bend_index < len(bend_data)
                ):
                    for point in bend_data[bend_index]["surface_points"]:
                        if (point - previous_end).Length > 1e-9:
                            combined_edges.append(
                                Part.makeLine(previous_end, point)
                            )
                            previous_end = point
                    if (start - previous_end).Length > 1e-9:
                        combined_edges.append(
                            Part.makeLine(previous_end, start)
                        )
                elif (start - previous_end).Length > 1e-9:
                    combined_edges.append(Part.makeLine(previous_end, start))
            combined_edges.extend(edges)
            last_edge = edges[-1]
            previous_end = last_edge.valueAt(last_edge.LastParameter)

    path_wire = Part.Wire(combined_edges)
    if not path_wire.isValid():
        raise ValueError("Continuous lacing path is not valid")

    group_name = "ContinuousLacing_{}".format(harness.Name)
    old_group = document.getObject(group_name)
    if old_group is not None:
        for obj in list(old_group.Group):
            if obj.Document is document:
                document.removeObject(obj.Name)
        document.removeObject(old_group.Name)

    stale_names = []
    for obj in list(document.Objects):
        try:
            name = obj.Name
        except ReferenceError:
            continue
        if name.startswith("LacingFillets_") or name.startswith(
            "LacingSweeps_"
        ):
            stale_names.append(name)

    for name in stale_names:
        obj = document.getObject(name)
        if obj is None:
            continue
        if hasattr(obj, "Group"):
            child_names = []
            for child in list(obj.Group):
                try:
                    child_names.append(child.Name)
                except ReferenceError:
                    continue
            for child_name in child_names:
                if document.getObject(child_name) is not None:
                    document.removeObject(child_name)
        if document.getObject(name) is not None:
            document.removeObject(name)

    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Continuous Lacing - {}".format(harness.Label)

    path_obj = document.addObject(
        "Part::Feature", "LacingContinuousPath"
    )
    path_obj.Label = "Continuous Lacing Path"
    path_obj.Shape = path_wire
    try:
        path_obj.ViewObject.LineColor = (0.28, 0.16, 0.06)
        path_obj.ViewObject.LineWidth = 2.0
    except Exception:
        pass
    group.addObject(path_obj)

    filleted = _fillet_wire(path_wire, fillet_radius)
    first_edge = filleted.Edges[0]
    start = first_edge.valueAt(first_edge.FirstParameter)
    tangent = first_edge.tangentAt(first_edge.FirstParameter)
    profile = Part.Wire(
        [Part.Circle(start, tangent, diameter / 2.0).toShape()]
    )
    solid = filleted.makePipeShell([profile], True, use_frenet, 0)

    sweep_obj = document.addObject(
        "Part::Feature", "LacingContinuousSweep"
    )
    sweep_obj.Label = "Continuous Lacing Sweep"
    sweep_obj.Shape = solid
    try:
        sweep_obj.ViewObject.ShapeColor = (0.32, 0.18, 0.07)
        sweep_obj.ViewObject.Transparency = 0
    except Exception:
        pass
    group.addObject(sweep_obj)

    document.recompute()
    return sweep_obj


def _new_bend_node(document, bend_index, node_index, point):
    name = "BendNode_{:02d}_{:03d}".format(bend_index + 1, node_index)
    obj = document.addObject("App::Part", name)
    obj.Label = "Bend {:02d} Node {:03d}".format(bend_index + 1, node_index)
    obj.Placement.Base = point
    return obj


def _arc_point(edge, distance):
    distance = max(0.0, min(edge.Length, distance))
    parameter = edge.getParameterByLength(distance)
    return edge.valueAt(parameter)


def rebuild_harness_bend_helpers(
    harness,
    helper_length=HELPER_LENGTH,
    min_bend_radius=MIN_BEND_RADIUS,
):
    """Replace harness bend helpers with odd-count, joint-shared 1 mm pieces."""
    from VibeWire import WireBundle
    from VibeWire.WireCreator import Segment, WireCreator

    document = harness.Document
    document.recompute()
    all_segments = list(harness.Segments)
    original = [
        segment
        for segment in all_segments
        if not segment.Label.startswith("Bend ")
    ]
    if len(original) < 2:
        return original

    cables = [
        obj
        for obj in document.Objects
        if getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable"
    ]
    for cable in cables:
        cable.Points = original
        cable.SegmentDirections = [0] * len(original)

    old_helpers = [
        segment
        for segment in all_segments
        if segment.Label.startswith("Bend ")
    ]
    old_nodes = []
    for segment in old_helpers:
        for reference in (segment.Start, segment.End):
            if (
                reference is not None
                and getattr(reference, "Label", "").startswith("Bend ")
                and " Node " in reference.Label
            ):
                old_nodes.append(reference)

    for segment in old_helpers:
        WireBundle.remove_bundle_segment(harness, segment)

    seen_nodes = set()
    for obj in old_nodes:
        try:
            name = obj.Name
        except ReferenceError:
            continue
        if name in seen_nodes:
            continue
        seen_nodes.add(name)
        if document.getObject(name) is not None:
            document.removeObject(name)

    for old_group in (
        "BendHelpers_{}".format(harness.Name),
        "BendLacing_{}".format(harness.Name),
        "ContinuousLacing_{}".format(harness.Name),
    ):
        _safe_remove_group(document, old_group)

    route = [
        Segment(
            segment.Start.getGlobalPlacement().Base,
            segment.End.getGlobalPlacement().Base,
        )
        for segment in original
    ]
    solved = WireCreator(min_bend_radius=min_bend_radius).create_wire(route)
    bends = []
    current = []
    for edge in solved.Edges:
        if isinstance(edge.Curve, Part.Circle):
            current.append(edge)
        elif current:
            bends.append(current)
            current = []
    if current:
        bends.append(current)

    if len(bends) != len(original) - 1:
        harness.Segments = original
        for cable in cables:
            cable.Points = original
            cable.SegmentDirections = [0] * len(original)
        document.recompute()
        raise ValueError(
            "Expected {} bends, found {}".format(
                len(original) - 1, len(bends)
            )
        )

    new_order = [original[0]]
    for bend_index, bend_edges in enumerate(bends):
        if len(bend_edges) != 2:
            raise ValueError("Only bi-arc bends are supported")
        arc1, arc2 = bend_edges
        n1 = max(3, _odd_helper_count(arc1.Length, helper_length))
        n2 = max(3, _odd_helper_count(arc2.Length, helper_length))
        remaining1 = n1 - 1
        remaining2 = n2 - 1

        shared_start_distance = max(
            0.0, arc1.Length - helper_length / 2.0
        )
        arc1_nodes = []
        for index in range(1, remaining1 + 1):
            distance = (
                shared_start_distance * index / remaining1
                if remaining1 > 0
                else 0.0
            )
            arc1_nodes.append(
                _new_bend_node(
                    document,
                    bend_index,
                    len(arc1_nodes) + 1,
                    _arc_point(arc1, distance),
                )
            )

        shared_end_distance = min(
            arc2.Length, helper_length / 2.0
        )
        arc2_nodes = [
            _new_bend_node(
                document,
                bend_index,
                len(arc1_nodes) + 1,
                _arc_point(arc2, shared_end_distance),
            )
        ]
        for index in range(1, remaining2):
            distance = (
                shared_end_distance
                + (arc2.Length - shared_end_distance)
                * index
                / remaining2
            )
            arc2_nodes.append(
                _new_bend_node(
                    document,
                    bend_index,
                    len(arc1_nodes) + len(arc2_nodes) + 1,
                    _arc_point(arc2, distance),
                )
            )

        shared_start_node = (
            arc1_nodes[-1] if arc1_nodes else original[bend_index].End
        )
        shared_end_node = arc2_nodes[0]
        chain = (
            [original[bend_index].End]
            + arc1_nodes
            + arc2_nodes
            + [original[bend_index + 1].Start]
        )

        for segment_index, (node_a, node_b) in enumerate(
            zip(chain, chain[1:]), start=1
        ):
            helper = WireBundle.create_bundle_segment(
                harness,
                node_a,
                node_b,
                radius=original[bend_index].Radius.Value,
            )
            if node_a is shared_start_node and node_b is shared_end_node:
                helper.Label = "Bend {:02d} Shared Helper".format(
                    bend_index + 1
                )
            else:
                helper.Label = "Bend {:02d} Helper {:03d}".format(
                    bend_index + 1, segment_index
                )
            try:
                helper.ViewObject.ShapeColor = (1.0, 0.0, 0.0)
                helper.ViewObject.Transparency = 75
                helper.ViewObject.Visibility = True
            except Exception:
                pass
            new_order.append(helper)
        new_order.append(original[bend_index + 1])

    harness.Segments = new_order
    WireBundle.ensure_segment_group(harness)
    for cable in cables:
        cable.Points = new_order
        cable.SegmentDirections = [0] * len(new_order)
        WireBundle.add_cable_to_harness(harness, cable)
    document.recompute()
    return new_order


def build_route_lacing(
    harness,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
    fillet_radius=0.2,
    diameter=0.5,
    surface_angle=0.0,
    section_gap=SECTION_GAP,
    section_factor=SECTION_FACTOR,
    use_frenet=False,
):
    """Generate one lacing path along the complete harness route."""
    document = harness.Document
    document.recompute()
    segments = [segment for segment in harness.Segments if segment is not None]
    if not segments:
        raise ValueError("Harness has no route segments")

    center_points = [segments[0].Start.getGlobalPlacement().Base]
    tangents = []
    for segment in segments:
        start = segment.Start.getGlobalPlacement().Base
        end = segment.End.getGlobalPlacement().Base
        delta = end - start
        if delta.Length < 1e-9:
            raise ValueError("Route contains a zero-length segment")
        tangents.append(delta / delta.Length)
        center_points.append(end)

    radial = _surface_direction(segments[0], surface_angle)
    node_radials = [radial]
    for index in range(len(segments) - 1):
        radial = _rotate_between(tangents[index], tangents[index + 1], radial)
        if radial.Length < 1e-9:
            radial = _surface_direction(segments[0], surface_angle)
        else:
            radial = radial.normalize()
        node_radials.append(radial)
    node_radials.append(node_radials[-1])

    radius = max(_bundle_outer_radius(segment) for segment in segments)
    surface_points = [
        center_points[index] + node_radials[index] * radius
        for index in range(len(center_points))
    ]
    distances = _polyline_distances(surface_points)
    total_length = distances[-1]
    od = 2.0 * radius
    spans = lacing_sections(total_length, od, section_gap, section_factor)

    def frame_at(distance):
        if distance <= 0.0:
            index = 0
        elif distance >= distances[-1]:
            index = len(distances) - 2
        else:
            index = 0
            for candidate in range(len(distances) - 1):
                if distances[candidate] <= distance <= distances[candidate + 1]:
                    index = candidate
                    break
        point = _interpolate_polyline(surface_points, distances, distance)
        span = distances[index + 1] - distances[index]
        ratio = 0.0 if span < 1e-9 else (distance - distances[index]) / span
        local_radial = (
            node_radials[index] * (1.0 - ratio)
            + node_radials[index + 1] * ratio
        )
        if local_radial.Length < 1e-9:
            local_radial = node_radials[index]
        else:
            local_radial = local_radial.normalize()
        return point, tangents[index], local_radial, radius

    edges = []
    previous_end = None
    for start_distance, end_distance in spans:
        section_edges = _section_edges_along_polyline(
            surface_points, distances, start_distance, end_distance
        )
        if not section_edges:
            continue
        section_start = section_edges[0].valueAt(
            section_edges[0].FirstParameter
        )
        if (
            previous_end is not None
            and (section_start - previous_end).Length > 1e-9
        ):
            edges.append(Part.makeLine(previous_end, section_start))
        edges.extend(section_edges)

        end_point, tangent, local_radial, local_radius = frame_at(
            end_distance
        )
        knot_edges, knot_end, _tangent, _radial, _radius = (
            _knot_edges_in_frame(
                end_point,
                tangent,
                local_radial,
                local_radius,
                s1c_axial=s1c_axial,
                s1c_radial=s1c_radial,
                s1c_tangential=s1c_tangential,
            )
        )
        edges.extend(knot_edges)
        previous_end = knot_end

    path_wire = Part.Wire(edges)
    if not path_wire.isValid():
        raise ValueError("Route lacing path is not valid")

    group_name = "ContinuousLacing_{}".format(harness.Name)
    _safe_remove_group(document, group_name)
    stale_names = []
    for obj in list(document.Objects):
        try:
            name = obj.Name
        except ReferenceError:
            continue
        if name.startswith(
            ("LacingThreads_", "LacingFillets_", "LacingSweeps_", "BendLacing_")
        ):
            stale_names.append(name)
    for name in stale_names:
        _safe_remove_group(document, name)

    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Continuous Lacing - {}".format(harness.Label)

    path_obj = document.addObject("Part::Feature", "LacingContinuousPath")
    path_obj.Label = "Continuous Lacing Path"
    path_obj.Shape = path_wire
    try:
        path_obj.ViewObject.LineColor = (0.28, 0.16, 0.06)
        path_obj.ViewObject.LineWidth = 2.0
    except Exception:
        pass
    group.addObject(path_obj)

    filleted = _fillet_wire(path_wire, fillet_radius)
    first_edge = filleted.Edges[0]
    start = first_edge.valueAt(first_edge.FirstParameter)
    tangent = first_edge.tangentAt(first_edge.FirstParameter)
    profile = Part.Wire(
        [Part.Circle(start, tangent, diameter / 2.0).toShape()]
    )
    solid = filleted.makePipeShell([profile], True, use_frenet, 0)

    sweep_obj = document.addObject("Part::Feature", "LacingContinuousSweep")
    sweep_obj.Label = "Continuous Lacing Sweep"
    sweep_obj.Shape = solid
    try:
        sweep_obj.ViewObject.ShapeColor = (0.32, 0.18, 0.07)
        sweep_obj.ViewObject.Transparency = 0
    except Exception:
        pass
    group.addObject(sweep_obj)

    document.recompute()
    return sweep_obj


def _solved_path_polyline(wire, arc_sample=0.5):
    points = []
    tangents = []
    for edge in wire.Edges:
        if isinstance(edge.Curve, Part.Circle):
            count = max(1, int(math.ceil(edge.Length / arc_sample)))
            samples = [
                edge.valueAt(edge.getParameterByLength(edge.Length * i / count))
                for i in range(count + 1)
            ]
        else:
            samples = [
                edge.valueAt(edge.FirstParameter),
                edge.valueAt(edge.LastParameter),
            ]
        if points and (samples[0] - points[-1]).Length < 1e-9:
            samples = samples[1:]
        for index, point in enumerate(samples):
            if not points:
                points.append(point)
                continue
            previous = points[-1]
            delta = point - previous
            if delta.Length < 1e-9:
                continue
            points.append(point)
            tangents.append(delta / delta.Length)
    return points, tangents


def build_solved_path_lacing(
    harness,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
    fillet_radius=0.2,
    diameter=0.5,
    surface_angle=0.0,
    section_gap=SECTION_GAP,
    section_factor=SECTION_FACTOR,
    arc_sample=0.5,
    use_frenet=False,
):
    """Generate lacing along the solved bundle centerline without helpers."""
    document = harness.Document
    document.recompute()
    solved = solve_bundle_path(harness)
    center_points, tangents = _solved_path_polyline(
        solved, arc_sample=arc_sample
    )
    if len(center_points) < 2 or len(tangents) != len(center_points) - 1:
        raise ValueError("Solved path did not produce a usable polyline")

    radial = _surface_direction(harness.Segments[0], surface_angle)
    node_radials = [radial]
    for index in range(1, len(center_points)):
        if index < len(tangents):
            radial = _rotate_between(
                tangents[index - 1], tangents[index], radial
            )
            if radial.Length < 1e-9:
                radial = _surface_direction(
                    harness.Segments[0], surface_angle
                )
            else:
                radial = radial.normalize()
        node_radials.append(radial)

    radius = max(_bundle_outer_radius(segment) for segment in harness.Segments)
    surface_points = [
        center_points[index] + node_radials[index] * radius
        for index in range(len(center_points))
    ]
    distances = _polyline_distances(surface_points)
    total_length = distances[-1]
    od = 2.0 * radius
    spans = lacing_sections(total_length, od, section_gap, section_factor)

    def frame_at(distance):
        if distance <= 0.0:
            index = 0
        elif distance >= distances[-1]:
            index = len(distances) - 2
        else:
            index = 0
            for candidate in range(len(distances) - 1):
                if distances[candidate] <= distance <= distances[candidate + 1]:
                    index = candidate
                    break
        point = _interpolate_polyline(surface_points, distances, distance)
        span = distances[index + 1] - distances[index]
        ratio = 0.0 if span < 1e-9 else (distance - distances[index]) / span
        local_radial = (
            node_radials[index] * (1.0 - ratio)
            + node_radials[index + 1] * ratio
        )
        if local_radial.Length < 1e-9:
            local_radial = node_radials[index]
        else:
            local_radial = local_radial.normalize()
        return point, tangents[index], local_radial, radius

    edges = []
    previous_end = None
    for start_distance, end_distance in spans:
        section_edges = _section_edges_along_polyline(
            surface_points, distances, start_distance, end_distance
        )
        if not section_edges:
            continue
        section_start = section_edges[0].valueAt(
            section_edges[0].FirstParameter
        )
        if (
            previous_end is not None
            and (section_start - previous_end).Length > 1e-9
        ):
            edges.append(Part.makeLine(previous_end, section_start))
        edges.extend(section_edges)

        end_point, tangent, local_radial, local_radius = frame_at(
            end_distance
        )
        knot_edges, knot_end, _tangent, _radial, _radius = (
            _knot_edges_in_frame(
                end_point,
                tangent,
                local_radial,
                local_radius,
                s1c_axial=s1c_axial,
                s1c_radial=s1c_radial,
                s1c_tangential=s1c_tangential,
            )
        )
        edges.extend(knot_edges)
        previous_end = knot_end

    path_wire = Part.Wire(edges)
    if not path_wire.isValid():
        raise ValueError("Solved-path lacing is not valid")

    group_name = "ContinuousLacing_{}".format(harness.Name)
    _safe_remove_group(document, group_name)
    stale_names = []
    for obj in list(document.Objects):
        try:
            name = obj.Name
        except ReferenceError:
            continue
        if name.startswith(
            ("LacingThreads_", "LacingFillets_", "LacingSweeps_", "BendLacing_")
        ):
            stale_names.append(name)
    for name in stale_names:
        _safe_remove_group(document, name)

    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Continuous Lacing - {}".format(harness.Label)

    path_obj = document.addObject("Part::Feature", "LacingContinuousPath")
    path_obj.Label = "Continuous Lacing Path"
    path_obj.Shape = path_wire
    try:
        path_obj.ViewObject.LineColor = (0.28, 0.16, 0.06)
        path_obj.ViewObject.LineWidth = 2.0
    except Exception:
        pass
    group.addObject(path_obj)

    filleted = _fillet_wire(path_wire, fillet_radius)
    first_edge = filleted.Edges[0]
    start = first_edge.valueAt(first_edge.FirstParameter)
    tangent = first_edge.tangentAt(first_edge.FirstParameter)
    profile = Part.Wire(
        [Part.Circle(start, tangent, diameter / 2.0).toShape()]
    )
    solid = filleted.makePipeShell([profile], True, use_frenet, 0)

    sweep_obj = document.addObject("Part::Feature", "LacingContinuousSweep")
    sweep_obj.Label = "Continuous Lacing Sweep"
    sweep_obj.Shape = solid
    try:
        sweep_obj.ViewObject.ShapeColor = (0.32, 0.18, 0.07)
        sweep_obj.ViewObject.Transparency = 0
    except Exception:
        pass
    group.addObject(sweep_obj)

    document.recompute()
    return sweep_obj


def visualize_bend_helpers(
    harness,
    helper_length=HELPER_LENGTH,
    min_bend_radius=MIN_BEND_RADIUS,
    transparency=80,
):
    """Draw a small lace-based set of bend helpers as red cylinders.

    Each bi-arc gets 1-3 helper positions per arc, including one shared helper
    exactly at the arc-arc joint. This is a visualization overlay only: the
    harness route and cables are not modified.
    """
    document = harness.Document
    segments = [segment for segment in harness.Segments if segment is not None]
    if not segments:
        return None

    solved = solve_bundle_path(harness, min_bend_radius=min_bend_radius)
    bends = []
    current = []
    for edge in solved.Edges:
        if isinstance(edge.Curve, Part.Circle):
            current.append(edge)
        elif current:
            bends.append(current)
            current = []
    if current:
        bends.append(current)

    radius = max(_bundle_outer_radius(segment) for segment in segments)
    outer_diameter = 2.0 * radius
    group_name = "BendHelpers_{}".format(harness.Name)
    _safe_remove_group(document, group_name)
    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Bend Helpers - {}".format(harness.Label)

    def helper_count(arc):
        count = int(round(arc.Length / outer_diameter))
        return max(1, min(3, count))

    def add_helper(bend_index, helper_index, center, tangent, shared=False):
        if tangent.Length < 1e-9:
            return
        tangent = tangent.normalize()
        cylinder = Part.makeCylinder(
            radius,
            helper_length,
            center - tangent * (helper_length / 2.0),
            tangent,
        )
        obj = document.addObject(
            "Part::Feature",
            "BendHelper_{:02d}_{:03d}".format(bend_index + 1, helper_index),
        )
        if shared:
            obj.Label = "Bend {:02d} Shared Helper".format(bend_index + 1)
        else:
            obj.Label = "Bend {:02d} Helper {:03d}".format(
                bend_index + 1, helper_index
            )
        obj.Shape = cylinder
        try:
            if shared:
                obj.ViewObject.ShapeColor = (0.0, 0.75, 0.0)
            else:
                obj.ViewObject.ShapeColor = (1.0, 0.0, 0.0)
            obj.ViewObject.Transparency = transparency
        except Exception:
            pass
        group.addObject(obj)

    for bend_index, bend_edges in enumerate(bends):
        if len(bend_edges) != 2:
            continue
        arc1, arc2 = bend_edges
        count1 = helper_count(arc1)
        count2 = helper_count(arc2)
        helper_index = 0

        for index in range(1, count1):
            distance = arc1.Length * index / count1
            parameter = arc1.getParameterByLength(distance)
            helper_index += 1
            add_helper(
                bend_index,
                helper_index,
                arc1.valueAt(parameter),
                arc1.tangentAt(parameter),
            )

        helper_index += 1
        joint_center = arc1.valueAt(arc1.LastParameter)
        joint_tangent = arc1.tangentAt(arc1.LastParameter)
        add_helper(
            bend_index,
            helper_index,
            joint_center,
            joint_tangent,
            shared=True,
        )

        for index in range(1, count2):
            distance = arc2.Length * index / count2
            parameter = arc2.getParameterByLength(distance)
            helper_index += 1
            add_helper(
                bend_index,
                helper_index,
                arc2.valueAt(parameter),
                arc2.tangentAt(parameter),
            )

    document.recompute()
    return group


def _project_point_to_polyline(points, distances, point):
    best_distance = None
    best_position = 0.0
    for index in range(len(points) - 1):
        start = points[index]
        end = points[index + 1]
        direction = end - start
        length_sq = direction.dot(direction)
        if length_sq < 1e-12:
            continue
        parameter = max(
            0.0, min(1.0, (point - start).dot(direction) / length_sq)
        )
        projected = start + direction * parameter
        distance = (point - projected).Length
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_position = (
                distances[index]
                + parameter * (distances[index + 1] - distances[index])
            )
    return best_position


def _helper_count(arc, outer_diameter):
    count = int(round(arc.Length / outer_diameter))
    return max(1, min(3, count))


def _bend_helper_positions(arc1, arc2, outer_diameter):
    count1 = _helper_count(arc1, outer_diameter)
    count2 = _helper_count(arc2, outer_diameter)
    positions = []
    for index in range(1, count1):
        distance = arc1.Length * index / count1
        positions.append(
            arc1.valueAt(arc1.getParameterByLength(distance))
        )
    positions.append(arc1.valueAt(arc1.LastParameter))
    for index in range(1, count2):
        distance = arc2.Length * index / count2
        positions.append(
            arc2.valueAt(arc2.getParameterByLength(distance))
        )
    return positions


def build_helper_aligned_lacing(
    harness,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
    fillet_radius=0.2,
    diameter=0.5,
    surface_angle=0.0,
    section_gap=SECTION_GAP,
    arc_sample=0.5,
    use_frenet=False,
):
    """Place laces at the helper segments and keep OD spacing on straights."""
    document = harness.Document
    document.recompute()
    solved = solve_bundle_path(harness)
    center_points, tangents = _solved_path_polyline(
        solved, arc_sample=arc_sample
    )
    if len(center_points) < 2 or len(tangents) != len(center_points) - 1:
        raise ValueError("Solved path did not produce a usable polyline")

    radial = _surface_direction(harness.Segments[0], surface_angle)
    node_radials = [radial]
    for index in range(1, len(center_points)):
        if index < len(tangents):
            radial = _rotate_between(
                tangents[index - 1], tangents[index], radial
            )
            if radial.Length < 1e-9:
                radial = _surface_direction(
                    harness.Segments[0], surface_angle
                )
            else:
                radial = radial.normalize()
        node_radials.append(radial)

    radius = max(_bundle_outer_radius(segment) for segment in harness.Segments)
    outer_diameter = 2.0 * radius
    surface_points = [
        center_points[index] + node_radials[index] * radius
        for index in range(len(center_points))
    ]
    distances = _polyline_distances(surface_points)
    total_length = distances[-1]

    def frame_at(distance):
        if distance <= 0.0:
            index = 0
        elif distance >= distances[-1]:
            index = len(distances) - 2
        else:
            index = 0
            for candidate in range(len(distances) - 1):
                if distances[candidate] <= distance <= distances[candidate + 1]:
                    index = candidate
                    break
        point = _interpolate_polyline(surface_points, distances, distance)
        span = distances[index + 1] - distances[index]
        ratio = 0.0 if span < 1e-9 else (distance - distances[index]) / span
        local_radial = (
            node_radials[index] * (1.0 - ratio)
            + node_radials[index + 1] * ratio
        )
        if local_radial.Length < 1e-9:
            local_radial = node_radials[index]
        else:
            local_radial = local_radial.normalize()
        return point, tangents[index], local_radial, radius

    bends = []
    current = []
    for edge in solved.Edges:
        if isinstance(edge.Curve, Part.Circle):
            current.append(edge)
        elif current:
            bends.append(current)
            current = []
    if current:
        bends.append(current)

    helper_knots = []
    bend_intervals = []
    for bend_edges in bends:
        if len(bend_edges) != 2:
            continue
        arc1, arc2 = bend_edges
        start_distance = _project_point_to_polyline(
            surface_points,
            distances,
            arc1.valueAt(arc1.FirstParameter),
        )
        end_distance = _project_point_to_polyline(
            surface_points,
            distances,
            arc2.valueAt(arc2.LastParameter),
        )
        bend_intervals.append((start_distance, end_distance))
        for point in _bend_helper_positions(arc1, arc2, outer_diameter):
            helper_knots.append(
                (
                    _project_point_to_polyline(
                        surface_points, distances, point
                    ),
                    "helper",
                )
            )

    spacing = outer_diameter + section_gap
    base_knots = []
    position = outer_diameter
    while position < total_length - 1e-6:
        base_knots.append((position, "base"))
        position += spacing

    def inside_bend(distance):
        return any(
            start - 1.0 <= distance <= end + 1.0
            for start, end in bend_intervals
        )

    def near_helper(distance):
        return any(
            abs(distance - helper_distance) < 2.0
            for helper_distance, _kind in helper_knots
        )

    knots = [
        (distance, kind)
        for distance, kind in base_knots
        if not inside_bend(distance) and not near_helper(distance)
    ]
    knots.extend(helper_knots)
    knots.sort(key=lambda item: item[0])

    merged = []
    for distance, kind in knots:
        if not merged:
            merged.append((distance, kind))
            continue
        previous_distance, previous_kind = merged[-1]
        if distance - previous_distance >= 2.0:
            merged.append((distance, kind))
        elif kind == "helper" and previous_kind == "base":
            merged[-1] = (distance, kind)

    edges = []
    previous_end = None
    previous_knot_distance = None
    for knot_distance, _kind in merged:
        section_start = (
            0.0
            if previous_knot_distance is None
            else previous_knot_distance + section_gap
        )
        section_end = knot_distance
        if section_end > section_start + 1e-6:
            section_edges = _section_edges_along_polyline(
                surface_points, distances, section_start, section_end
            )
            if section_edges:
                section_start_point = section_edges[0].valueAt(
                    section_edges[0].FirstParameter
                )
                if (
                    previous_end is not None
                    and (section_start_point - previous_end).Length > 1e-9
                ):
                    edges.append(
                        Part.makeLine(previous_end, section_start_point)
                    )
                edges.extend(section_edges)
        elif previous_end is not None:
            knot_point = _interpolate_polyline(
                surface_points, distances, section_end
            )
            if (knot_point - previous_end).Length > 1e-9:
                edges.append(Part.makeLine(previous_end, knot_point))

        end_point, tangent, local_radial, local_radius = frame_at(
            knot_distance
        )
        knot_edges, knot_end, _tangent, _radial, _radius = (
            _knot_edges_in_frame(
                end_point,
                tangent,
                local_radial,
                local_radius,
                s1c_axial=s1c_axial,
                s1c_radial=s1c_radial,
                s1c_tangential=s1c_tangential,
            )
        )
        edges.extend(knot_edges)
        previous_end = knot_end
        previous_knot_distance = knot_distance

    path_wire = Part.Wire(edges)
    if not path_wire.isValid():
        raise ValueError("Helper-aligned lacing path is not valid")

    group_name = "ContinuousLacing_{}".format(harness.Name)
    _safe_remove_group(document, group_name)
    stale_names = []
    for obj in list(document.Objects):
        try:
            name = obj.Name
        except ReferenceError:
            continue
        if name.startswith(
            ("LacingThreads_", "LacingFillets_", "LacingSweeps_", "BendLacing_")
        ):
            stale_names.append(name)
    for name in stale_names:
        _safe_remove_group(document, name)

    group = document.addObject("App::DocumentObjectGroup", group_name)
    group.Label = "Continuous Lacing - {}".format(harness.Label)

    path_obj = document.addObject("Part::Feature", "LacingContinuousPath")
    path_obj.Label = "Continuous Lacing Path"
    path_obj.Shape = path_wire
    try:
        path_obj.ViewObject.LineColor = (0.28, 0.16, 0.06)
        path_obj.ViewObject.LineWidth = 2.0
    except Exception:
        pass
    group.addObject(path_obj)

    filleted = _fillet_wire(path_wire, fillet_radius)
    first_edge = filleted.Edges[0]
    start = first_edge.valueAt(first_edge.FirstParameter)
    tangent = first_edge.tangentAt(first_edge.FirstParameter)
    profile = Part.Wire(
        [Part.Circle(start, tangent, diameter / 2.0).toShape()]
    )
    solid = filleted.makePipeShell([profile], True, use_frenet, 0)

    sweep_obj = document.addObject("Part::Feature", "LacingContinuousSweep")
    sweep_obj.Label = "Continuous Lacing Sweep"
    sweep_obj.Shape = solid
    try:
        sweep_obj.ViewObject.ShapeColor = (0.32, 0.18, 0.07)
        sweep_obj.ViewObject.Transparency = 0
    except Exception:
        pass
    group.addObject(sweep_obj)

    document.recompute()
    return sweep_obj
