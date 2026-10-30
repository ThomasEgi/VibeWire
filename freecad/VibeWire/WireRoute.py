"""Route graph and layout codec shared by harness and cable features."""

import FreeCAD as App

from .WireFrames import segment_basis
from .WireTypes import is_bundle_segment


def layout_key(segment, cable):
    return "{}|{}".format(segment.Name, cable.Name)


def encode_offset(offset):
    return "{:.9f},{:.9f},{:.9f}".format(offset.x, offset.y, offset.z)


def decode_offset(raw, side=None, normal=None):
    if raw is None:
        return App.Vector(0.0, 0.0, 0.0)
    try:
        parts = [
            float(value)
            for value in str(raw).replace(";", ",").split(",")
            if value.strip()
        ]
    except Exception:
        return App.Vector(0.0, 0.0, 0.0)
    if len(parts) >= 3:
        return App.Vector(parts[0], parts[1], parts[2])
    if len(parts) == 2 and side is not None and normal is not None:
        return side * parts[0] + normal * parts[1]
    if len(parts) == 1 and side is not None:
        return side * parts[0]
    return App.Vector(0.0, 0.0, 0.0)


def parse_cable_route(cable, segment_set=None):
    raw_points = list(getattr(cable, "Points", []))
    raw_directions = list(getattr(cable, "SegmentDirections", []) or [])
    route = []
    directions = []
    for index, node in enumerate(raw_points):
        if not is_bundle_segment(node):
            continue
        if segment_set is not None and node not in segment_set:
            continue
        route.append(node)
        directions.append(
            int(raw_directions[index]) if index < len(raw_directions) else 0
        )
    return route, directions


def cable_uses_segment(cable, segment):
    points = list(getattr(cable, "Points", []))
    if not points or not all(is_bundle_segment(node) for node in points):
        return False
    return any(node is segment for node in points)


def build_route_graph(cables, segments):
    segment_set = set(segments)
    routes = {}
    directions = {}
    users = {segment: [] for segment in segments}
    adjacency = {segment: set() for segment in segments}
    connections = {}
    for cable in cables:
        route, route_directions = parse_cable_route(cable, segment_set)
        routes[cable] = route
        directions[cable] = route_directions
        for segment in dict.fromkeys(route):
            users[segment].append(cable)
        for index in range(len(route) - 1):
            first = route[index]
            second = route[index + 1]
            adjacency[first].add(second)
            adjacency[second].add(first)
            connections.setdefault((first, second), set()).add(cable)
            connections.setdefault((second, first), set()).add(cable)
    counts = {segment: len(users[segment]) for segment in segments}
    ordered = sorted(
        [segment for segment in segments if users[segment]],
        key=lambda segment: (counts[segment], segment.Name),
    )
    return routes, directions, users, counts, adjacency, connections, ordered


def oriented_points(segment, direction):
    start = segment.Start.getGlobalPlacement().Base
    end = segment.End.getGlobalPlacement().Base
    if int(direction) % 2:
        return end, start
    return start, end


def facing_endpoints(route, directions, first, second):
    try:
        first_index = route.index(first)
        second_index = route.index(second)
    except ValueError:
        return None, None
    first_direction = (
        directions[first_index] if first_index < len(directions) else 0
    )
    second_direction = (
        directions[second_index] if second_index < len(directions) else 0
    )
    first_start, first_end = oriented_points(first, first_direction)
    second_start, second_end = oriented_points(second, second_direction)
    if first_index < second_index:
        return first_end, second_start
    return first_start, second_end


def layout_positions(obj, segments, users):
    positions = {}
    for segment in segments:
        side, normal = segment_basis(segment)
        segment_positions = {}
        for cable in users[segment]:
            raw = obj.Layout.get(layout_key(segment, cable))
            if raw is None:
                continue
            offset = decode_offset(raw, side, normal)
            segment_positions[cable] = (
                offset.dot(side),
                offset.dot(normal),
            )
        if segment_positions:
            positions[segment] = segment_positions
    return positions
