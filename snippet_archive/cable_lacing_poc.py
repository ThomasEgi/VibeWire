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

SECTION_FACTOR = 6.0
SECTION_GAP = 2.0
KNOT_ALONG = 0.5
KNOT_INWARD = 0.5
KNOT_TANGENTIAL = 0.5


def lacing_sections(length, radius, gap=SECTION_GAP, factor=SECTION_FACTOR):
    """Return centered (start, end) axial spans for full lacing sections."""
    section_length = factor * radius
    if section_length <= 0.0:
        raise ValueError("Bundle segment radius must be positive")

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
        lacing_sections(length, segment.Radius.Value, gap, factor),
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


def build_continuous_lacing(
    harness,
    s1c_axial=0.5,
    s1c_radial=-0.25,
    s1c_tangential=0.25,
    fillet_radius=0.2,
    diameter=0.5,
):
    """Build one continuous lacing path across all harness route segments."""
    document = harness.Document
    segments = [segment for segment in harness.Segments if segment is not None]

    for segment in segments:
        create_lacing_threads(segment)

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
    for segment in segments:
        group = document.getObject("LacingThreads_{}".format(segment.Name))
        for obj in group.Group:
            edges = list(obj.Shape.Edges)
            if not edges:
                continue
            start = edges[0].valueAt(edges[0].FirstParameter)
            if previous_end is not None and (start - previous_end).Length > 1e-9:
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
    solid = filleted.makePipeShell([profile], True, True, 0)

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
