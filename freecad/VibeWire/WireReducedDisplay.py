"""Reduced harness display geometry."""

import math

import FreeCAD as App
import Part

from .WireCreator import Segment as WireSegment, WireCreator
from .WireFrames import segment_basis
from .WireGeometry import (
    circumscribed_points,
    convex_hull_2d,
    fit_rigid_2d,
    polygon_centroid,
    unit_vector,
)
from .WireRoute import facing_endpoints
from .WireTypes import is_lace_helper


def reduced_bundle_hulls(
    users,
    counts,
    adjacency,
    connections,
    positions_by_segment,
    ordered,
):
    hulls = {}
    for segment in ordered:
        if is_lace_helper(segment):
            continue
        target_positions = positions_by_segment.get(segment)
        if not target_positions:
            continue
        points = []
        covered = set()
        for neighbor in adjacency.get(segment, ()):
            if is_lace_helper(neighbor):
                continue
            if counts.get(neighbor, 0) >= counts[segment]:
                continue
            source_hull = hulls.get(neighbor)
            if source_hull is None:
                continue
            shared = connections.get((neighbor, segment), set())
            source_points = []
            target_points = []
            for cable in shared:
                source = positions_by_segment.get(neighbor, {}).get(cable)
                target = target_positions.get(cable)
                if source is None or target is None:
                    continue
                source_points.append(source)
                target_points.append(target)
            if not source_points:
                continue
            cosine, sine, offset_x, offset_y = fit_rigid_2d(
                source_points,
                target_points,
            )
            points.extend(
                (
                    x * cosine - y * sine + offset_x,
                    x * sine + y * cosine + offset_y,
                )
                for x, y in source_hull
            )
            covered.update(shared)
        for cable in users[segment]:
            if cable in covered:
                continue
            position = target_positions.get(cable)
            if position is None:
                continue
            points.extend(
                circumscribed_points(
                    position[0],
                    position[1],
                    cable.Diameter.Value,
                )
            )
        if len(points) < 3:
            continue
        hull = convex_hull_2d(points)
        if len(hull) >= 3:
            hulls[segment] = hull
    return hulls

def reduced_bundle_solids(hulls):
    solids = []
    for segment, hull in hulls.items():
        start_obj = segment.Start
        end_obj = segment.End
        if start_obj is None or end_obj is None:
            continue
        start = start_obj.getGlobalPlacement().Base
        end = end_obj.getGlobalPlacement().Base
        direction = end - start
        length = direction.Length
        if length < 1e-9:
            continue
        direction = direction / length
        side, normal = segment_basis(segment)
        points = [
            start + side * x + normal * y
            for x, y in hull
        ]
        if len(points) < 3:
            continue
        points.append(points[0])
        try:
            wire = Part.makePolygon(points)
            face = Part.Face(wire)
            solids.append(face.extrude(direction * length))
        except Exception:
            pass
    return solids

def discretize_edge(edge, max_angle=math.radians(20.0)):
    try:
        curve = edge.Curve
        first = edge.FirstParameter
        last = edge.LastParameter
    except Exception:
        return []
    if isinstance(curve, Part.Circle):
        span = abs(last - first)
        if span > 2.0 * math.pi + 1e-6:
            span = 2.0 * math.pi
        count = max(1, int(math.ceil(span / max_angle)))
        try:
            return [
                edge.valueAt(first + (last - first) * index / count)
                for index in range(count + 1)
            ]
        except Exception:
            return []
    try:
        return [edge.valueAt(first), edge.valueAt(last)]
    except Exception:
        try:
            return [edge.Vertexes[0].Point, edge.Vertexes[-1].Point]
        except Exception:
            return []

def triangle(a, b, c):
    try:
        if (b - a).cross(c - a).Length < 1e-12:
            return None
        return Part.Face(Part.makePolygon([a, b, c, a]))
    except Exception:
        return None

def reduced_transition_solids(
    hulls,
    counts,
    connections,
    positions_by_segment,
    packed_placements,
    routes,
    directions,
):
    solids = []
    processed = set()
    for (first, second), shared in connections.items():
        if first is second or not shared:
            continue
        key = tuple(sorted((first.Name, second.Name)))
        if key in processed:
            continue
        processed.add(key)
        if first not in hulls or second not in hulls:
            continue
        if is_lace_helper(first) or is_lace_helper(second):
            continue

        if counts.get(first, 0) <= counts.get(second, 0):
            small_segment = first
            large_segment = second
        else:
            small_segment = second
            large_segment = first

        cable = next(iter(shared))
        route = routes.get(cable, [])
        route_directions = directions.get(cable, [])
        try:
            first_index = route.index(first)
            second_index = route.index(second)
        except ValueError:
            continue
        if abs(first_index - second_index) != 1:
            continue

        first_facing, second_facing = facing_endpoints(
            route,
            route_directions,
            first,
            second,
        )
        if first_facing is None or second_facing is None:
            continue

        if small_segment is first:
            small_face_point = first_facing
            large_face_point = second_facing
        else:
            small_face_point = second_facing
            large_face_point = first_facing

        small_start = small_segment.Start.getGlobalPlacement().Base
        small_end = small_segment.End.getGlobalPlacement().Base
        small_far_point = (
            small_end
            if (small_face_point - small_start).Length < 1e-9
            else small_start
        )
        small_outward = unit_vector(small_face_point - small_far_point, zero="zero")
        if small_outward.Length < 1e-9:
            continue

        large_start = large_segment.Start.getGlobalPlacement().Base
        large_end = large_segment.End.getGlobalPlacement().Base
        large_far_point = (
            large_end
            if (large_face_point - large_start).Length < 1e-9
            else large_start
        )
        large_inward = unit_vector(large_far_point - large_face_point, zero="zero")
        if large_inward.Length < 1e-9:
            continue

        small_hull = hulls[small_segment]
        if len(small_hull) < 3:
            continue
        center_x, center_y = polygon_centroid(small_hull)
        local_profile = [
            (x - center_x, y - center_y)
            for x, y in small_hull
        ]
        small_side, small_normal = segment_basis(small_segment)
        start_center = (
            small_face_point
            + small_side * center_x
            + small_normal * center_y
        )

        large_side, large_normal = segment_basis(large_segment)
        placement = packed_placements.get(large_segment, {}).get(
            small_segment
        )
        if placement is not None:
            target_x, target_y, target_angle = placement
        else:
            large_positions = positions_by_segment.get(large_segment, {})
            target_points = [
                large_positions[cable]
                for cable in shared
                if cable in large_positions
            ]
            if target_points:
                target_x = sum(point[0] for point in target_points) / len(
                    target_points
                )
                target_y = sum(point[1] for point in target_points) / len(
                    target_points
                )
            else:
                target_x = 0.0
                target_y = 0.0
            target_angle = 0.0

        end_center = (
            large_face_point
            + large_side * target_x
            + large_normal * target_y
        )
        if (end_center - start_center).Length < 1e-9:
            continue

        cosine = math.cos(target_angle)
        sine = math.sin(target_angle)
        target_side = large_side * cosine + large_normal * sine
        target_normal = -large_side * sine + large_normal * cosine
        start_normal = small_side.cross(small_normal)
        end_normal = target_side.cross(target_normal)

        length = max((end_center - start_center).Length * 2.0, 1.0)
        virtual_small = WireSegment(
            start_center - small_outward * length,
            start_center,
        )
        virtual_large = WireSegment(
            end_center,
            end_center + large_inward * length,
        )
        creator = WireCreator(min_bend_radius=12.0)
        try:
            creator.create_wire([virtual_small, virtual_large])
        except Exception:
            continue
        edges = [
            piece["edge"]
            for piece in creator.pieces
            if piece.get("type") == "biarc"
        ]
        if not edges:
            continue
        path_points = []
        for edge in edges:
            edge_points = discretize_edge(edge)
            if not edge_points:
                continue
            if (
                path_points
                and (path_points[-1] - edge_points[0]).Length < 1e-7
            ):
                path_points.extend(edge_points[1:])
            else:
                path_points.extend(edge_points)
        if len(path_points) < 2:
            continue

        cumulative = [0.0]
        for index in range(1, len(path_points)):
            cumulative.append(
                cumulative[-1]
                + (path_points[index] - path_points[index - 1]).Length
            )
        total_length = cumulative[-1]
        if total_length < 1e-9:
            continue

        tangents = []
        for index in range(len(path_points)):
            if index == 0:
                tangent = small_outward
            elif index == len(path_points) - 1:
                tangent = large_inward
            else:
                tangent = path_points[index + 1] - path_points[index - 1]
                if tangent.Length < 1e-9:
                    tangent = path_points[index] - path_points[index - 1]
                tangent.normalize()
            tangents.append(tangent)

        z_axes = [-tangent for tangent in tangents]
        z_axes[0] = start_normal
        z_axes[-1] = end_normal

        x_axes = []
        x_prev = small_side
        for z_axis in z_axes:
            x_axis = x_prev - z_axis * x_prev.dot(z_axis)
            if x_axis.Length < 1e-9:
                x_axis = z_axis.cross(App.Vector(0.0, 0.0, 1.0))
                if x_axis.Length < 1e-9:
                    x_axis = z_axis.cross(App.Vector(1.0, 0.0, 0.0))
            x_axis.normalize()
            x_axes.append(x_axis)
            x_prev = x_axis
        y_axes = [
            z_axes[index].cross(x_axes[index])
            for index in range(len(path_points))
        ]

        end_x = x_axes[-1]
        target_x = target_side - z_axes[-1] * target_side.dot(z_axes[-1])
        if target_x.Length < 1e-9:
            target_x = end_x
        target_x.normalize()
        roll = math.atan2(
            z_axes[-1].dot(end_x.cross(target_x)),
            end_x.dot(target_x),
        )

        sections = []
        for index, point in enumerate(path_points):
            fraction = cumulative[index] / total_length
            angle = roll * fraction
            cosine = math.cos(angle)
            sine = math.sin(angle)
            x_axis = x_axes[index] * cosine + y_axes[index] * sine
            y_axis = y_axes[index] * cosine - x_axes[index] * sine
            rotation = App.Rotation(
                x_axis,
                y_axis,
                z_axes[index],
                "XYZ",
            )
            sections.append(
                [
                    point
                    + rotation.multVec(App.Vector(x, y, 0.0))
                    for x, y in local_profile
                ]
            )
        count = len(local_profile)
        faces = []
        for index in range(len(sections) - 1):
            for corner in range(count):
                a = sections[index][corner]
                b = sections[index][(corner + 1) % count]
                c = sections[index + 1][(corner + 1) % count]
                d = sections[index + 1][corner]
                face = triangle(a, b, c)
                if face is not None:
                    faces.append(face)
                face = triangle(a, c, d)
                if face is not None:
                    faces.append(face)
        for corner in range(1, count - 1):
            face = triangle(
                sections[0][0],
                sections[0][corner],
                sections[0][corner + 1],
            )
            if face is not None:
                faces.append(face)
            face = triangle(
                sections[-1][0],
                sections[-1][corner + 1],
                sections[-1][corner],
            )
            if face is not None:
                faces.append(face)
        if not faces:
            continue
        try:
            shell = Part.makeShell(faces)
            shell.sewShape()
            if (
                shell.isNull()
                or not shell.isValid()
                or not shell.isClosed()
            ):
                continue
            solid = Part.makeSolid(shell)
            if solid.isValid():
                solids.append(solid)
            else:
                solids.append(shell)
        except Exception:
            pass
    return solids

