"""Cross-section layout computation for harness segments."""

import math
from dataclasses import dataclass, field

import FreeCAD as App
import Part

from .WireFrames import segment_basis
from .WirePacking import (
    bundle_hull,
    fit_circle_for_positions,
    fit_radius_for_positions,
    packed_positions,
    packed_shapes,
)
from .WireRoute import (
    cable_uses_segment,
    build_route_graph,
    encode_offset,
    layout_key,
)
from .WireTypes import is_bundle_segment, is_lace_helper

_PACKING_FALLBACK_WARNED = False


@dataclass
class LayoutResult:
    layout: dict = field(default_factory=dict)
    positions_by_segment: dict = field(default_factory=dict)
    hulls_by_segment: dict = field(default_factory=dict)
    placements: dict = field(default_factory=dict)
    radii: dict = field(default_factory=dict)
    bundle_hull_wires: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    users: dict = field(default_factory=dict)
    ordered: list = field(default_factory=list)


def warn_packing_fallback():
    global _PACKING_FALLBACK_WARNED
    if _PACKING_FALLBACK_WARNED:
        return
    App.Console.PrintWarning(
        "VibeWire: pymunk is unavailable; Packed and Packed Bundles "
        "patterns are falling back to Circular.\n"
    )
    _PACKING_FALLBACK_WARNED = True


def linear_positions(diameters, gap):
    total = sum(diameters) + gap * (len(diameters) - 1)
    position = -total / 2.0
    positions = []
    for diameter in diameters:
        positions.append((position + diameter / 2.0, 0.0))
        position += diameter + gap
    return positions


def circular_positions(diameters, gap):
    count = len(diameters)
    if count == 1:
        return [(0.0, 0.0)]
    angle_step = 2.0 * math.pi / count
    required = [
        diameters[index] / 2.0
        + gap
        + diameters[(index + 1) % count] / 2.0
        for index in range(count)
    ]
    radius = max(required) / (2.0 * math.sin(math.pi / count))
    return [
        (radius * math.cos(index * angle_step), radius * math.sin(index * angle_step))
        for index in range(count)
    ]


def lower_neighbor_contributions(
    segment,
    cable,
    routes,
    directions,
    counts,
    positions_by_segment,
    side,
    normal,
    center,
):
    route = routes.get(cable, [])
    route_directions = directions.get(cable, [])
    target_count = counts.get(segment, 0)
    contributions = []
    for index, node in enumerate(route):
        if node is not segment:
            continue
        for neighbor_index in (index - 1, index + 1):
            if neighbor_index < 0 or neighbor_index >= len(route):
                continue
            neighbor = route[neighbor_index]
            if neighbor is segment:
                continue
            if neighbor not in positions_by_segment:
                continue
            if counts.get(neighbor, 0) >= target_count:
                continue
            local = positions_by_segment.get(neighbor, {}).get(cable)
            if local is None:
                continue
            neighbor_direction = (
                route_directions[neighbor_index]
                if neighbor_index < len(route_directions)
                else 0
            )
            target_direction = (
                route_directions[index]
                if index < len(route_directions)
                else 0
            )
            if neighbor_index < index:
                boundary = (
                    neighbor.End
                    if neighbor_direction % 2 == 0
                    else neighbor.Start
                )
            else:
                boundary = (
                    neighbor.Start
                    if neighbor_direction % 2 == 0
                    else neighbor.End
                )
            if boundary is None:
                continue
            relative = boundary.getGlobalPlacement().Base - center
            sign = (
                1
                if (neighbor_direction + target_direction) % 2 == 0
                else -1
            )
            contributions.append(
                {
                    "neighbor": neighbor,
                    "boundary": (
                        relative.dot(side),
                        relative.dot(normal),
                    ),
                    "local": (local[0], local[1] * sign),
                }
            )
    return contributions


def packed_bundle_positions(
    segment,
    segment_users,
    routes,
    directions,
    users,
    counts,
    positions_by_segment,
    side,
    normal,
    center,
):
    groups = {}
    individual = []
    for cable in segment_users:
        contributions = lower_neighbor_contributions(
            segment,
            cable,
            routes,
            directions,
            counts,
            positions_by_segment,
            side,
            normal,
            center,
        )
        if not contributions:
            individual.append(cable)
            continue
        best = min(
            contributions,
            key=lambda item: (
                counts.get(item["neighbor"], 0),
                item["neighbor"].Name,
            ),
        )
        groups.setdefault(best["neighbor"], []).append((cable, best))
    if not groups:
        return None

    units = []
    unit_shapes = []
    for neighbor in sorted(groups, key=lambda item: item.Name):
        items = groups[neighbor]
        neighbor_diameters = [
            max(0.0, cable.Diameter.Value) for cable in users[neighbor]
        ]
        neighbor_positions = [
            positions_by_segment[neighbor][cable]
            for cable in users[neighbor]
        ]
        hull_vertices, hull_center = bundle_hull(
            neighbor_positions,
            neighbor_diameters,
        )
        boundary_x = sum(item[1]["boundary"][0] for item in items) / len(items)
        boundary_y = sum(item[1]["boundary"][1] for item in items) / len(items)
        internal = {}
        for cable, contribution in items:
            internal[cable] = (
                contribution["boundary"][0]
                - boundary_x
                + contribution["local"][0]
                - hull_center[0],
                contribution["boundary"][1]
                - boundary_y
                + contribution["local"][1]
                - hull_center[1],
            )
        units.append(
            {
                "seed": (boundary_x + hull_center[0], boundary_y + hull_center[1]),
                "internal": internal,
                "source": neighbor,
            }
        )
        unit_shapes.append(("poly", hull_vertices))

    for cable in individual:
        units.append(
            {
                "seed": None,
                "internal": {cable: (0.0, 0.0)},
                "source": None,
            }
        )
        unit_shapes.append(("circle", max(0.0, cable.Diameter.Value) / 2.0))
    if not units:
        return None

    seeds = [unit["seed"] for unit in units]
    initial = seeds if any(seed is not None for seed in seeds) else None
    unit_positions = packed_shapes(unit_shapes, initial_positions=initial)
    if unit_positions is None:
        return None

    result = {}
    for unit, (unit_x, unit_y, angle) in zip(units, unit_positions):
        cosine = math.cos(angle)
        sine = math.sin(angle)
        for cable, (internal_x, internal_y) in unit["internal"].items():
            result[cable] = (
                unit_x + internal_x * cosine - internal_y * sine,
                unit_y + internal_x * sine + internal_y * cosine,
            )
    positions = [result.get(cable, (0.0, 0.0)) for cable in segment_users]
    hulls = []
    for shape, (unit_x, unit_y, angle) in zip(unit_shapes, unit_positions):
        if shape[0] != "poly":
            continue
        cosine = math.cos(angle)
        sine = math.sin(angle)
        hulls.append(
            [
                (
                    unit_x + x * cosine - y * sine,
                    unit_y + x * sine + y * cosine,
                )
                for x, y in shape[1]
            ]
        )
    fit_center, _fit_radius = fit_circle_for_positions(
        positions,
        [max(0.0, cable.Diameter.Value) for cable in segment_users],
    )
    placements = {}
    for unit, (unit_x, unit_y, angle) in zip(units, unit_positions):
        source = unit.get("source")
        if source is not None:
            placements[source] = (
                unit_x - fit_center[0],
                unit_y - fit_center[1],
                angle,
            )
    return {
        "positions": [
            (point[0] - fit_center[0], point[1] - fit_center[1])
            for point in positions
        ],
        "hulls": [
            [
                (point[0] - fit_center[0], point[1] - fit_center[1])
                for point in hull
            ]
            for hull in hulls
        ],
        "placements": placements,
    }


def simple_layout(obj, cables, gap, pattern):
    segments = [
        segment for segment in obj.Segments if is_bundle_segment(segment)
    ]
    result = LayoutResult(segments=segments)
    if not segments:
        return result

    for segment in segments:
        users = [
            cable for cable in cables if cable_uses_segment(cable, segment)
        ]
        result.users[segment] = users
        if not users:
            continue
        diameters = [max(0.0, cable.Diameter.Value) for cable in users]
        if pattern == "Linear":
            positions = linear_positions(diameters, gap)
        else:
            positions = circular_positions(diameters, gap)
        side, normal = segment_basis(segment)
        segment_positions = {}
        for cable, (x, y) in zip(users, positions):
            segment_positions[cable] = (x, y)
            result.layout[layout_key(segment, cable)] = encode_offset(
                side * x + normal * y
            )
        result.positions_by_segment[segment] = segment_positions
        result.ordered.append(segment)
    return result


def packed_layout(obj, cables, gap, bundle_mode=False):
    segments = [
        segment for segment in obj.Segments if is_bundle_segment(segment)
    ]
    result = LayoutResult(segments=segments)
    if not segments:
        return result

    (
        routes,
        directions,
        users,
        counts,
        adjacency,
        _connections,
        ordered,
    ) = build_route_graph(cables, segments)
    result.users = users
    result.ordered = ordered

    for segment in ordered:
        if segment.Start is None or segment.End is None:
            continue
        segment_users = users[segment]
        diameters = [
            max(0.0, cable.Diameter.Value) for cable in segment_users
        ]
        side, normal = segment_basis(segment)
        start = segment.Start.getGlobalPlacement().Base
        end = segment.End.getGlobalPlacement().Base
        center = (start + end) / 2.0

        copied_from = None
        segment_user_set = set(segment_users)
        for neighbor in adjacency.get(segment, ()):
            if neighbor not in result.positions_by_segment:
                continue
            if set(users[neighbor]) == segment_user_set:
                copied_from = neighbor
                break

        if copied_from is not None:
            positions = [
                result.positions_by_segment[copied_from][cable]
                for cable in segment_users
            ]
            hulls_2d = list(result.hulls_by_segment.get(copied_from, []))
            placements = dict(result.placements.get(copied_from, {}))
        elif bundle_mode:
            bundle_result = packed_bundle_positions(
                segment,
                segment_users,
                routes,
                directions,
                users,
                counts,
                result.positions_by_segment,
                side,
                normal,
                center,
            )
            if bundle_result is None:
                positions = packed_positions(diameters)
                if positions is None:
                    warn_packing_fallback()
                    positions = circular_positions(diameters, gap)
                hulls_2d = []
                placements = {}
            else:
                positions = bundle_result["positions"]
                hulls_2d = bundle_result["hulls"]
                placements = bundle_result.get("placements", {})
        else:
            hulls_2d = []
            placements = {}
            seeds = []
            has_seed = False
            for cable in segment_users:
                contributions = lower_neighbor_contributions(
                    segment,
                    cable,
                    routes,
                    directions,
                    counts,
                    result.positions_by_segment,
                    side,
                    normal,
                    center,
                )
                if contributions:
                    points = [
                        (
                            contribution["boundary"][0]
                            + contribution["local"][0],
                            contribution["boundary"][1]
                            + contribution["local"][1],
                        )
                        for contribution in contributions
                    ]
                    seeds.append(
                        (
                            sum(point[0] for point in points) / len(points),
                            sum(point[1] for point in points) / len(points),
                        )
                    )
                    has_seed = True
                else:
                    seeds.append(None)
            positions = packed_positions(
                diameters,
                initial_positions=seeds if has_seed else None,
            )
            if positions is None:
                warn_packing_fallback()
                positions = circular_positions(diameters, gap)

        segment_positions = {}
        for cable, (x, y) in zip(segment_users, positions):
            segment_positions[cable] = (x, y)
            result.layout[layout_key(segment, cable)] = encode_offset(
                side * x + normal * y
            )
        result.positions_by_segment[segment] = segment_positions
        result.hulls_by_segment[segment] = hulls_2d
        result.placements[segment] = placements
        if bundle_mode and not is_lace_helper(segment):
            for hull in hulls_2d:
                if len(hull) < 3:
                    continue
                points = [
                    start + side * x + normal * y
                    for x, y in hull
                ]
                points.append(points[0])
                try:
                    result.bundle_hull_wires.append(Part.makePolygon(points))
                except Exception:
                    pass

        fit_radius = fit_radius_for_positions(positions, diameters)
        if fit_radius is not None:
            result.radii[segment] = fit_radius
    return result
