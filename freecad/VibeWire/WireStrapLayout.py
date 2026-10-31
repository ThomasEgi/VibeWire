"""Strap placement policy for harness segments and their bends."""

import math
from dataclasses import dataclass

import FreeCAD as App
import Part

from .WireCreator import Segment as PathSegment, WireCreator
from .WireFrames import segment_basis
from .WireGeometry import polygon_centroid
from .WireRoute import build_route_graph, facing_endpoints, layout_positions
from .WireStrap import hull_for_segment
from .WireTypes import is_bundle_segment, is_lace_helper


@dataclass
class StrapPlacement:
    segment: object
    slot: int
    distance: float
    kind: str
    placement: object
    join_segment: object = None


def strap_od(segment):
    """Outer bundle diameter used for strap margins and spacing."""
    return max(0.0, 2.0 * float(segment.Radius.Value))


def distribute_distances(
    path_length,
    od,
    start_margin_factor=0.5,
    end_margin_factor=0.5,
    spacing_factor=3.0,
):
    """Space straps uniformly between configured end margins."""
    od = float(od)
    path_length = float(path_length)
    if od <= 1e-9:
        return []
    start_margin = float(start_margin_factor) * od
    end_margin = float(end_margin_factor) * od
    if path_length < start_margin + end_margin - 1e-9:
        return []
    available = max(0.0, path_length - start_margin - end_margin)
    intervals = max(
        0,
        int(round(available / (float(spacing_factor) * od))),
    )
    if intervals <= 0:
        return [start_margin]
    return [
        start_margin + available * index / intervals
        for index in range(intervals + 1)
    ]


def _unit(vector):
    if vector.Length < 1e-9:
        return App.Vector(0.0, 0.0, 0.0)
    return vector / vector.Length


def _other_endpoint(segment, face_point):
    start = segment.Start.getGlobalPlacement().Base
    end = segment.End.getGlobalPlacement().Base
    if (face_point - start).Length <= (face_point - end).Length:
        return end
    return start


def _discretize_edge(edge, max_angle=math.radians(18.0)):
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
        return []


class CurvePath:
    def __init__(self, points, rotations, centroid):
        self.points = points
        self.rotations = rotations
        self.centroid = centroid
        self.distances = [0.0]
        for start, end in zip(points, points[1:]):
            self.distances.append(
                self.distances[-1] + (end - start).Length
            )
        self.length = self.distances[-1]

    def frame_at(self, distance):
        if not self.points:
            return None
        distance = max(0.0, min(self.length, float(distance)))
        if self.length <= 1e-9:
            index = 0
            ratio = 0.0
        elif distance <= 0.0:
            index = 0
            ratio = 0.0
        elif distance >= self.length:
            index = len(self.points) - 2
            ratio = 1.0
        else:
            index = 0
            for candidate in range(len(self.distances) - 1):
                if self.distances[candidate] <= distance <= self.distances[candidate + 1]:
                    index = candidate
                    break
            span = self.distances[index + 1] - self.distances[index]
            ratio = 0.0 if span < 1e-9 else (
                (distance - self.distances[index]) / span
            )
        position = (
            self.points[index] * (1.0 - ratio)
            + self.points[index + 1] * ratio
        )
        rotation = self.rotations[index if ratio < 0.5 else index + 1]
        base = position - rotation.multVec(self.centroid)
        return base, rotation


def _transition_curve(
    small_segment,
    small_far,
    small_face,
    large_segment,
    large_face,
    hull,
    target_x,
    target_y,
    target_angle,
):
    """Return the reduced-bundle-style bi-arc path from small to large face."""
    large_far = _other_endpoint(large_segment, large_face)
    small_outward = _unit(small_face - small_far)
    large_inward = _unit(large_far - large_face)
    if small_outward.Length < 1e-9 or large_inward.Length < 1e-9:
        return None

    center_x, center_y = polygon_centroid(
        [(float(point.x), float(point.y)) for point in hull]
    )
    centroid = App.Vector(center_x, center_y, 0.0)
    small_side, small_normal = segment_basis(small_segment)
    start_center = (
        small_face
        + small_side * center_x
        + small_normal * center_y
    )
    large_side, large_normal = segment_basis(large_segment)
    cosine = math.cos(target_angle)
    sine = math.sin(target_angle)
    target_side = large_side * cosine + large_normal * sine
    target_normal = -large_side * sine + large_normal * cosine
    end_center = (
        large_face
        + large_side * target_x
        + large_normal * target_y
    )
    chord = (end_center - start_center).Length
    if chord < 1e-9:
        return None
    length = max(chord * 2.0, 1.0)
    creator = WireCreator(min_bend_radius=12.0)
    try:
        creator.create_wire(
            [
                PathSegment(
                    start_center - small_outward * length,
                    start_center,
                ),
                PathSegment(
                    end_center,
                    end_center + large_inward * length,
                ),
            ]
        )
    except Exception:
        return None
    arcs = [
        piece["edge"]
        for piece in creator.pieces
        if piece.get("type") == "biarc"
    ]
    if not arcs:
        return None
    points = []
    for edge in arcs:
        edge_points = _discretize_edge(edge)
        if not edge_points:
            continue
        if points and (points[-1] - edge_points[0]).Length < 1e-7:
            edge_points = edge_points[1:]
        points.extend(edge_points)
    if len(points) < 2:
        return None
    tangents = []
    for index in range(len(points)):
        if index == 0:
            tangent = small_outward
        elif index == len(points) - 1:
            tangent = large_inward
        else:
            tangent = points[index + 1] - points[index - 1]
            if tangent.Length < 1e-9:
                tangent = points[index] - points[index - 1]
        tangent = _unit(tangent)
        if tangent.Length < 1e-9:
            return None
        tangents.append(tangent)
    if len(tangents) != len(points):
        return None

    z_axes = [-tangent for tangent in tangents]
    z_axes[0] = small_side.cross(small_normal)
    z_axes[-1] = target_side.cross(target_normal)
    x_axes = []
    x_prev = small_side
    for z_axis in z_axes:
        x_axis = _unit(x_prev - z_axis * x_prev.dot(z_axis))
        if x_axis.Length < 1e-9:
            x_axis = _unit(z_axis.cross(App.Vector(0.0, 0.0, 1.0)))
        if x_axis.Length < 1e-9:
            x_axis = _unit(z_axis.cross(App.Vector(1.0, 0.0, 0.0)))
        x_axes.append(x_axis)
        x_prev = x_axis
    y_axes = [
        z_axes[index].cross(x_axes[index])
        for index in range(len(points))
    ]
    end_x = x_axes[-1]
    target_x_axis = target_side - z_axes[-1] * target_side.dot(z_axes[-1])
    if target_x_axis.Length < 1e-9:
        target_x_axis = end_x
    target_x_axis = _unit(target_x_axis)
    roll = math.atan2(
        z_axes[-1].dot(end_x.cross(target_x_axis)),
        end_x.dot(target_x_axis),
    )

    distances = [0.0]
    for start, end in zip(points, points[1:]):
        distances.append(distances[-1] + (end - start).Length)
    total_length = distances[-1]
    rotations = []
    for index in range(len(points)):
        fraction = 0.0 if total_length < 1e-9 else distances[index] / total_length
        angle = roll * fraction
        cosine = math.cos(angle)
        sine = math.sin(angle)
        x_axis = x_axes[index] * cosine + y_axes[index] * sine
        y_axis = y_axes[index] * cosine - x_axes[index] * sine
        rotations.append(
            App.Rotation(x_axis, y_axis, z_axes[index], "XYZ")
        )
    return CurvePath(points, rotations, centroid)


def _shared_cable(connections, first, second):
    shared = connections.get((first, second), set())
    if not shared:
        return None
    return min(shared, key=lambda item: item.Name)


def _segment_placements(
    segment,
    larger,
    routes,
    directions,
    connections,
    counts,
    positions_by_segment,
    packed_placements,
):
    start = segment.Start.getGlobalPlacement().Base
    end = segment.End.getGlobalPlacement().Base
    if (end - start).Length < 1e-9:
        return []
    od = strap_od(segment)
    if od <= 1e-9:
        return []
    hull = hull_for_segment(segment)
    if hull is None:
        return []
    result = []

    if not larger:
        runs = [(None, start, end, None)]
    else:
        runs = []
        for neighbor in larger:
            cable = _shared_cable(connections, segment, neighbor)
            if cable is None:
                continue
            route = routes.get(cable, [])
            route_directions = directions.get(cable, [])
            small_face, large_face = facing_endpoints(
                route,
                route_directions,
                segment,
                neighbor,
            )
            if small_face is None or large_face is None:
                continue
            shared = connections.get((segment, neighbor), set())
            target_x = 0.0
            target_y = 0.0
            target_angle = 0.0
            packed = packed_placements.get(neighbor, {}).get(segment)
            if packed is not None:
                target_x, target_y, target_angle = packed
            else:
                large_positions = positions_by_segment.get(neighbor, {})
                target_points = [
                    large_positions[item]
                    for item in shared
                    if item in large_positions
                ]
                if target_points:
                    target_x = sum(
                        point[0] for point in target_points
                    ) / len(target_points)
                    target_y = sum(
                        point[1] for point in target_points
                    ) / len(target_points)
            small_far = _other_endpoint(segment, small_face)
            curve = _transition_curve(
                segment,
                small_far,
                small_face,
                neighbor,
                large_face,
                hull,
                target_x,
                target_y,
                target_angle,
            )
            runs.append((neighbor, small_far, small_face, curve))

    for neighbor, far, join, curve in runs:
        straight = join - far
        straight_length = straight.Length
        if straight_length < 1e-9:
            continue
        straight_direction = straight / straight_length
        side, normal = segment_basis(segment)
        curve_length = curve.length if curve is not None else 0.0
        path_length = straight_length + curve_length
        end_margin_factor = 2.0 if neighbor is not None else 0.5
        for distance in distribute_distances(
            path_length,
            od,
            end_margin_factor=end_margin_factor,
            spacing_factor=3.0,
        ):
            if distance <= straight_length + 1e-7:
                position = far + straight_direction * distance
                rotation = App.Rotation(
                    side,
                    normal,
                    straight_direction,
                    "XYZ",
                )
                kind = "Straight"
            elif curve is not None:
                frame = curve.frame_at(distance - straight_length)
                if frame is None:
                    continue
                position, rotation = frame
                kind = "Curve"
            else:
                continue
            result.append(
                StrapPlacement(
                    segment=segment,
                    slot=0,
                    distance=distance,
                    kind=kind,
                    placement=App.Placement(position, rotation),
                    join_segment=neighbor,
                )
            )

    if len(result) > 1:
        filtered = []
        for placement in result:
            point = placement.placement.Base
            if any(
                (point - existing.placement.Base).Length < 0.5 * od
                for existing in filtered
            ):
                continue
            filtered.append(placement)
        result = filtered
    result.sort(key=lambda item: item.distance)
    for index, placement in enumerate(result, start=1):
        placement.slot = index
    return result


def plan_strap_placements(harness, cables):
    """Build all strap placements in ascending bundle-size order."""
    segments = [
        segment
        for segment in harness.Segments
        if is_bundle_segment(segment) and not is_lace_helper(segment)
    ]
    (
        routes,
        directions,
        users,
        counts,
        adjacency,
        connections,
        ordered,
    ) = build_route_graph(cables, segments)
    positions_by_segment = layout_positions(harness, segments, users)
    packed_placements = getattr(
        getattr(harness, "Proxy", None),
        "_packed_placements",
        {},
    )
    placements = []
    for segment in ordered:
        if counts.get(segment, 0) <= 1:
            continue
        larger = sorted(
            [
                neighbor
                for neighbor in adjacency.get(segment, ())
                if counts.get(neighbor, 0) > counts[segment]
            ],
            key=lambda item: (-counts[item], item.Name),
        )
        placements.extend(
            _segment_placements(
                segment,
                larger,
                routes,
                directions,
                connections,
                counts,
                positions_by_segment,
                packed_placements,
            )
        )
    return placements
