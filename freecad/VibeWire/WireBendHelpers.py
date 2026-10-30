"""Automatic lace-helper generation for harness bends."""

import Part

from . import WireBundle
from .WireCreator import Segment, WireCreator
from .WireGeometry import unit_vector
from .WireRoute import decode_offset, layout_key, parse_cable_route

HELPER_LENGTH = 1.0
MIN_BEND_RADIUS = 10.0


def _unit(vector):
    return unit_vector(vector, zero="none")


def _bundle_outer_radius(harness):
    max_offset = 0.0
    max_cable_radius = 0.0
    for cable in harness.InList:
        if getattr(getattr(cable, "Proxy", None), "Type", None) != "WireCable":
            continue
        max_cable_radius = max(
            max_cable_radius, max(0.0, cable.Diameter.Value) / 2.0
        )
        for segment in harness.Segments:
            raw = harness.Layout.get(layout_key(segment, cable))
            if not raw:
                continue
            side, normal = WireBundle.segment_basis(segment)
            offset = decode_offset(raw, side, normal)
            max_offset = max(max_offset, offset.Length)
    if max_offset > 1e-9:
        return max_offset + max_cable_radius
    radii = [
        segment.Radius.Value
        for segment in harness.Segments
        if WireBundle.is_bundle_segment(segment)
    ]
    return max(radii) if radii else 1.0


def _helper_count(arc, outer_diameter):
    count = int(round(arc.Length / max(outer_diameter, 1e-9)))
    return max(1, min(3, count))


def _bend_helper_frames(arc1, arc2, outer_diameter):
    count1 = _helper_count(arc1, outer_diameter)
    count2 = _helper_count(arc2, outer_diameter)
    frames = []
    for index in range(1, count1):
        distance = arc1.Length * index / count1
        parameter = arc1.getParameterByLength(distance)
        tangent = _unit(arc1.tangentAt(parameter))
        if tangent is not None:
            frames.append(
                (arc1.valueAt(parameter), tangent, False, distance)
            )
    joint_tangent = _unit(arc1.tangentAt(arc1.LastParameter))
    if joint_tangent is not None:
        frames.append(
            (
                arc1.valueAt(arc1.LastParameter),
                joint_tangent,
                True,
                arc1.Length,
            )
        )
    for index in range(1, count2):
        distance = arc2.Length * index / count2
        parameter = arc2.getParameterByLength(distance)
        tangent = _unit(arc2.tangentAt(parameter))
        if tangent is not None:
            frames.append(
                (
                    arc2.valueAt(parameter),
                    tangent,
                    False,
                    arc1.Length + distance,
                )
            )
    return frames


def _new_helper_node(document, harness, bend_index, helper_index, side, point):
    name = "LaceHelperNode_{:02d}_{:03d}_{}".format(
        bend_index + 1, helper_index, side
    )
    obj = document.addObject("App::Part", name)
    obj.Label = "Lace Helper {:02d}.{:03d} {}".format(
        bend_index + 1, helper_index, side
    )
    obj.Placement.Base = point
    group = WireBundle.ensure_helper_group(harness)
    if group is not None:
        group.addObject(obj)
    return obj


def _remove_old_helpers(harness):
    document = harness.Document
    old_helpers = [
        segment
        for segment in list(harness.Segments)
        if WireBundle.is_lace_helper(segment)
    ]
    for segment in old_helpers:
        WireBundle.remove_bundle_segment(harness, segment)
    old_node_names = [
        obj.Name
        for obj in list(document.Objects)
        if obj.Name.startswith(("LaceHelperNode_", "BendNode_"))
    ]
    for name in old_node_names:
        if document.getObject(name) is not None:
            document.removeObject(name)


def rebuild_bend_helpers(
    harness,
    helper_length=HELPER_LENGTH,
    min_bend_radius=None,
):
    """Rebuild the sparse lace helpers for all harness bends."""
    document = harness.Document
    document.recompute()

    all_segments = list(harness.Segments)
    original = [
        segment
        for segment in all_segments
        if not WireBundle.is_lace_helper(segment)
    ]
    if len(original) < 2:
        return original

    cables = [
        obj
        for obj in document.Objects
        if getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable"
    ]

    cable_routes = {}
    original_set = set(original)
    for cable in cables:
        cable_routes[cable] = parse_cable_route(cable, original_set)

    _remove_old_helpers(harness)

    if min_bend_radius is None:
        min_bend_radius = max(
            [MIN_BEND_RADIUS]
            + [max(0.0, cable.MinBendRadius.Value) for cable in cables]
        )

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
        raise ValueError(
            "Expected {} bends, found {}".format(
                len(original) - 1, len(bends)
            )
        )

    outer_diameter = 2.0 * _bundle_outer_radius(harness)
    new_order = [original[0]]
    for bend_index, bend_edges in enumerate(bends):
        if len(bend_edges) != 2:
            raise ValueError("Only bi-arc bends are supported")
        arc1, arc2 = bend_edges
        frames = _bend_helper_frames(arc1, arc2, outer_diameter)

        start_angle = original[bend_index].Orientation.Value
        end_angle = original[bend_index + 1].Orientation.Value
        angle_delta = ((end_angle - start_angle + 180.0) % 360.0) - 180.0
        if frames:
            first_distance = frames[0][3]
            last_distance = frames[-1][3]
            distance_span = last_distance - first_distance
        else:
            distance_span = 0.0

        previous_node = original[bend_index].End
        for helper_index, (center, tangent, shared, distance) in enumerate(
            frames, start=1
        ):
            start_point = center - tangent * (helper_length / 2.0)
            end_point = center + tangent * (helper_length / 2.0)
            start_node = _new_helper_node(
                document, harness, bend_index, helper_index, "Start", start_point
            )
            end_node = _new_helper_node(
                document, harness, bend_index, helper_index, "End", end_point
            )
            helper = WireBundle.create_bundle_segment(
                harness,
                start_node,
                end_node,
                radius=original[bend_index].Radius.Value,
            )
            helper.SegmentRole = WireBundle.LACE_HELPER_ROLE
            helper.Label = "Lace Helper {:02d}.{:03d}".format(
                bend_index + 1, helper_index
            )
            if distance_span < 1e-9:
                fraction = 0.5
            else:
                fraction = (distance - first_distance) / distance_span
            helper.Orientation = start_angle + angle_delta * fraction
            try:
                helper.ViewObject.ShapeColor = (
                    (0.0, 0.75, 0.0) if shared else (1.0, 0.0, 0.0)
                )
                helper.ViewObject.Transparency = 80
                helper.ViewObject.Visibility = True
            except Exception:
                pass
            new_order.append(helper)
            previous_node = end_node
        new_order.append(original[bend_index + 1])

    harness.Segments = new_order
    WireBundle.ensure_segment_group(harness)
    WireBundle.ensure_helper_group(harness)
    for cable in cables:
        route, directions = cable_routes.get(cable, ([], []))
        if route == original and directions and all(
            int(direction) == 0 for direction in directions
        ):
            cable.Points = new_order
            cable.SegmentDirections = [0] * len(new_order)
        elif route == original and directions and all(
            int(direction) % 2 for direction in directions
        ):
            cable.Points = list(reversed(new_order))
            cable.SegmentDirections = [0] * len(new_order)
        else:
            cable.Points = route
            cable.SegmentDirections = directions
        WireBundle.add_cable_to_harness(harness, cable)
    document.recompute()
    return new_order
