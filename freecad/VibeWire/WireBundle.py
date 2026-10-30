"""Persistent bundle and bundle-segment objects."""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from .WirePacking import (
    bundle_hull,
    fit_circle_for_positions,
    fit_radius_for_positions,
    packed_positions,
    packed_shapes,
)

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")
BUNDLE_SEGMENT_TYPE = "WireBundleSegment"
ROUTE_SEGMENT_ROLE = "Route"
LACE_HELPER_ROLE = "Lace Helper"
_PACKING_FALLBACK_WARNED = False


def _unit_vector(vector):
    length = vector.Length
    if length < 1e-9:
        return App.Vector(0.0, 0.0, 0.0)
    return vector / length


def is_bundle_segment(obj):
    """Return True if obj is a WireBundleSegment document object."""
    return getattr(getattr(obj, "Proxy", None), "Type", None) == BUNDLE_SEGMENT_TYPE


def segment_is_open(segment):
    """Return True when a bundle segment allows arbitrary wire entry/exit."""
    return getattr(segment, "SegmentType", "Closed") == "Open"


def is_lace_helper(obj):
    """Return True for auto-generated lace helper segments."""
    if getattr(obj, "SegmentRole", None) == LACE_HELPER_ROLE:
        return True
    return getattr(obj, "Label", "").startswith("Lace Helper ")


def _cross_2d(origin, first, second):
    return (
        (first[0] - origin[0]) * (second[1] - origin[1])
        - (first[1] - origin[1]) * (second[0] - origin[0])
    )


def _convex_hull_2d(points):
    unique = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(unique) <= 1:
        return unique
    lower = []
    for point in unique:
        while (
            len(lower) >= 2
            and _cross_2d(lower[-2], lower[-1], point) <= 0.0
        ):
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while (
            len(upper) >= 2
            and _cross_2d(upper[-2], upper[-1], point) <= 0.0
        ):
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _bundle_hull_shape(start, side, normal, positions, diameters, samples=64):
    if not positions:
        return Part.Shape()
    angles = [
        2.0 * math.pi * index / samples
        for index in range(samples)
    ]
    points = []
    for (x, y), diameter in zip(positions, diameters):
        radius = max(0.0, diameter) / 2.0
        for angle in angles:
            points.append(
                (
                    x + radius * math.cos(angle),
                    y + radius * math.sin(angle),
                )
            )
    hull = _convex_hull_2d(points)
    if len(hull) < 3:
        return Part.Shape()
    points3d = [
        start + side * x + normal * y
        for x, y in hull
    ]
    points3d.append(points3d[0])
    return Part.makePolygon(points3d)


class WireHarnessProxy:
    """Harness container and layout authority for bundle segments and cables."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "WireHarness"
        self._applied_display_mode = None
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        properties = obj.PropertiesList
        if "Segments" not in properties:
            obj.addProperty(
                "App::PropertyLinkList",
                "Segments",
                "Harness",
                "Independent straight bundle segments",
            )
        if "SegmentGroup" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "SegmentGroup",
                "Harness",
                "Group containing the harness bundle segments",
            )
        if "HelperGroup" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "HelperGroup",
                "Harness",
                "Group containing the lace helper segments",
            )
        if "BundleHullObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "BundleHullObject",
                "Harness",
                "Display object for packed bundle hulls",
            )
        if "OverallHullObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "OverallHullObject",
                "Harness",
                "Display object for overall segment hulls",
            )
        if "ReducedBundleObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "ReducedBundleObject",
                "Harness",
                "Display object for reduced bundle geometry",
            )
        if "DisplayMode" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "DisplayMode",
                "Harness",
                "Harness display detail",
            )
        current_display = getattr(obj, "DisplayMode", "Full Detail")
        obj.DisplayMode = ["Full Detail", "Reduced Bundle"]
        obj.DisplayMode = (
            current_display
            if current_display in ("Full Detail", "Reduced Bundle")
            else "Full Detail"
        )
        if "CableOrder" not in properties:
            obj.addProperty(
                "App::PropertyStringList",
                "CableOrder",
                "Harness",
                "Preferred cable order inside the harness",
            )
        if "Gap" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "Gap",
                "Harness",
                "Edge-to-edge gap between cables",
            )
            obj.Gap = 1.0
        if "Pattern" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "Pattern",
                "Harness",
                "Cable arrangement pattern",
            )
        current_pattern = getattr(obj, "Pattern", "Circular")
        obj.Pattern = ["Circular", "Linear", "Packed", "Packed Bundles"]
        obj.Pattern = (
            current_pattern
            if current_pattern in ("Circular", "Linear", "Packed", "Packed Bundles")
            else "Circular"
        )
        if "Layout" not in properties:
            obj.addProperty(
                "App::PropertyMap",
                "Layout",
                "Harness",
                "Computed cable lane offsets keyed by segment|cable",
            )
            try:
                obj.setEditorMode("Layout", 2)
            except Exception:
                pass

    def execute(self, obj):
        cables = [item for item in obj.InList if is_wire_cable(item)]
        order = list(obj.CableOrder)
        order_index = {name: index for index, name in enumerate(order)}
        cables.sort(
            key=lambda cable: (
                order_index.get(cable.Name, len(order)),
                cable.Name,
            )
        )

        gap = obj.Gap.Value
        pattern = getattr(obj, "Pattern", "Circular")
        if pattern in ("Packed", "Packed Bundles"):
            obj.Layout = self._packed_layout(
                obj,
                cables,
                gap,
                bundle_mode=pattern == "Packed Bundles",
            )
            self._update_reduced_display(obj, cables)
            return

        layout = {}
        for segment in obj.Segments:
            if not is_bundle_segment(segment):
                continue
            users = [
                cable for cable in cables if cable_uses_segment(cable, segment)
            ]
            if not users:
                if "HullCurve" in segment.PropertiesList:
                    try:
                        segment.HullCurve = Part.Shape()
                    except Exception:
                        pass
                continue

            diameters = [max(0.0, cable.Diameter.Value) for cable in users]
            if pattern == "Linear":
                positions = self._linear_positions(diameters, gap)
            else:
                positions = self._circular_positions(diameters, gap)

            side, normal = segment_basis(segment)
            for cable, (x, y) in zip(users, positions):
                offset = side * x + normal * y
                layout[f"{segment.Name}|{cable.Name}"] = (
                    f"{offset.x:.9f},{offset.y:.9f},{offset.z:.9f}"
                )

            self._update_segment_section(segment, positions, diameters)
        self._set_hull_overlays(obj, [], [])
        obj.Layout = layout
        self._update_reduced_display(obj, cables)

    def _packed_layout(self, obj, cables, gap, bundle_mode=False):
        """Pack every segment from the fewest to the most cables.

        A cable entering a segment from an already-solved segment with fewer
        cables seeds that cable's cross-section position. Higher-count
        neighbours are ignored so information only flows from branches into
        the trunk. Adjacent segments with identical cable sets copy their
        section directly.
        """
        segments = [segment for segment in obj.Segments if is_bundle_segment(segment)]
        if not segments:
            return {}

        segment_set = set(segments)
        routes = {}
        directions = {}
        users = {segment: [] for segment in segments}
        adjacency = {segment: set() for segment in segments}
        for cable in cables:
            raw_points = list(getattr(cable, "Points", []))
            raw_directions = list(getattr(cable, "SegmentDirections", []) or [])
            route = []
            route_directions = []
            for index, node in enumerate(raw_points):
                if not is_bundle_segment(node) or node not in segment_set:
                    continue
                route.append(node)
                route_directions.append(
                    int(raw_directions[index])
                    if index < len(raw_directions)
                    else 0
                )
            routes[cable] = route
            directions[cable] = route_directions
            for segment in dict.fromkeys(route):
                users[segment].append(cable)
            for index in range(len(route) - 1):
                first = route[index]
                second = route[index + 1]
                adjacency[first].add(second)
                adjacency[second].add(first)

        active = [segment for segment in segments if users[segment]]
        counts = {segment: len(users[segment]) for segment in active}
        ordered = sorted(
            active,
            key=lambda segment: (counts[segment], segment.Name),
        )

        positions_by_segment = {}
        hulls_by_segment = {}
        packed_placements_by_segment = {}
        bundle_hull_wires = []
        layout = {}

        for segment in ordered:
            if segment.Start is None or segment.End is None:
                continue
            segment_users = users[segment]
            count = counts[segment]
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
                if neighbor not in positions_by_segment:
                    continue
                if set(users[neighbor]) == segment_user_set:
                    copied_from = neighbor
                    break

            if copied_from is not None:
                positions = [
                    positions_by_segment[copied_from][cable]
                    for cable in segment_users
                ]
                hulls_2d = list(hulls_by_segment.get(copied_from, []))
                placements = dict(
                    packed_placements_by_segment.get(copied_from, {})
                )
            elif bundle_mode:
                bundle_result = self._packed_bundle_positions(
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
                )
                if bundle_result is None:
                    positions = packed_positions(diameters)
                    if positions is None:
                        self._warn_packing_fallback()
                        positions = self._circular_positions(diameters, gap)
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
                    contributions = self._lower_neighbor_contributions(
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
                    self._warn_packing_fallback()
                    positions = self._circular_positions(diameters, gap)

            segment_positions = {}
            for cable, (x, y) in zip(segment_users, positions):
                segment_positions[cable] = (x, y)
                offset = side * x + normal * y
                layout[f"{segment.Name}|{cable.Name}"] = (
                    f"{offset.x:.9f},{offset.y:.9f},{offset.z:.9f}"
                )
            positions_by_segment[segment] = segment_positions
            hulls_by_segment[segment] = hulls_2d
            packed_placements_by_segment[segment] = placements
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
                        bundle_hull_wires.append(Part.makePolygon(points))
                    except Exception:
                        pass

            fit_radius = fit_radius_for_positions(positions, diameters)
            if fit_radius is not None:
                self._set_segment_radius(segment, fit_radius)
            self._update_segment_section(segment, positions, diameters)

        for segment in segments:
            if users[segment]:
                continue
            if "HullCurve" in segment.PropertiesList:
                try:
                    segment.HullCurve = Part.Shape()
                except Exception:
                    pass
        if bundle_mode:
            overall_hull_wires = []
            for segment in ordered:
                if is_lace_helper(segment):
                    continue
                if "HullCurve" not in segment.PropertiesList:
                    continue
                shape = segment.HullCurve
                if shape is None or shape.isNull():
                    continue
                overall_hull_wires.append(shape)
            self._set_hull_overlays(
                obj,
                bundle_hull_wires,
                overall_hull_wires,
            )
        else:
            self._set_hull_overlays(obj, [], [])
        self._packed_placements = packed_placements_by_segment
        return layout

    def _lower_neighbor_contributions(
        self,
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

    def _packed_bundle_positions(
        self,
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
            contributions = self._lower_neighbor_contributions(
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
            boundary_x = sum(
                item[1]["boundary"][0] for item in items
            ) / len(items)
            boundary_y = sum(
                item[1]["boundary"][1] for item in items
            ) / len(items)
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
                    "seed": (
                        boundary_x + hull_center[0],
                        boundary_y + hull_center[1],
                    ),
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
            unit_shapes.append(
                ("circle", max(0.0, cable.Diameter.Value) / 2.0)
            )
        if not units:
            return None

        seeds = [unit["seed"] for unit in units]
        initial = seeds if any(seed is not None for seed in seeds) else None
        unit_positions = packed_shapes(
            unit_shapes,
            initial_positions=initial,
        )
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
        positions = [
            result.get(cable, (0.0, 0.0)) for cable in segment_users
        ]
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

    @staticmethod
    def _warn_packing_fallback():
        global _PACKING_FALLBACK_WARNED
        if not _PACKING_FALLBACK_WARNED:
            App.Console.PrintWarning(
                "VibeWire: pymunk is unavailable; Packed and Packed Bundles "
                "patterns are falling back to Circular.\n"
            )
            _PACKING_FALLBACK_WARNED = True

    @staticmethod
    def _set_segment_radius(segment, radius):
        if abs(segment.Radius.Value - radius) <= 1e-6:
            return
        segment.Radius = radius
        try:
            segment.Proxy.execute(segment)
        except Exception:
            segment.touch()

    @staticmethod
    def _update_segment_section(segment, positions, diameters):
        if "HullCurve" not in segment.PropertiesList:
            try:
                WireBundleSegmentProxy._add_properties(segment)
            except Exception:
                pass
        try:
            start = segment.Start.getGlobalPlacement().Base
            side, normal = segment_basis(segment)
            segment.HullCurve = _bundle_hull_shape(
                start,
                side,
                normal,
                positions,
                diameters,
            )
        except Exception:
            try:
                segment.HullCurve = Part.Shape()
            except Exception:
                pass


    @staticmethod
    def _set_hull_overlays(harness, bundle_wires, overall_wires):
        bundle_object, overall_object = ensure_hull_objects(harness)

        def apply_shape(target, wires):
            if target is None:
                return
            try:
                target.Shape = (
                    Part.makeCompound(wires) if wires else Part.Shape()
                )
            except Exception:
                try:
                    target.Shape = Part.Shape()
                except Exception:
                    pass

        apply_shape(bundle_object, bundle_wires)
        apply_shape(overall_object, overall_wires)

    @staticmethod
    def _route_graph(cables, segments):
        segment_set = set(segments)
        routes = {}
        directions = {}
        users = {segment: [] for segment in segments}
        adjacency = {segment: set() for segment in segments}
        connections = {}
        for cable in cables:
            raw_points = list(getattr(cable, "Points", []))
            raw_directions = list(getattr(cable, "SegmentDirections", []) or [])
            route = []
            route_directions = []
            for index, node in enumerate(raw_points):
                if not is_bundle_segment(node) or node not in segment_set:
                    continue
                route.append(node)
                route_directions.append(
                    int(raw_directions[index])
                    if index < len(raw_directions)
                    else 0
                )
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

    @staticmethod
    def _fit_rigid_2d(source, target):
        count = len(source)
        if count == 0:
            return 1.0, 0.0, 0.0, 0.0
        source_x = sum(point[0] for point in source) / count
        source_y = sum(point[1] for point in source) / count
        target_x = sum(point[0] for point in target) / count
        target_y = sum(point[1] for point in target) / count
        dot = 0.0
        cross = 0.0
        for (first_x, first_y), (second_x, second_y) in zip(source, target):
            ax = first_x - source_x
            ay = first_y - source_y
            bx = second_x - target_x
            by = second_y - target_y
            dot += ax * bx + ay * by
            cross += ax * by - ay * bx
        angle = math.atan2(cross, dot)
        cosine = math.cos(angle)
        sine = math.sin(angle)
        offset_x = target_x - (cosine * source_x - sine * source_y)
        offset_y = target_y - (sine * source_x + cosine * source_y)
        return cosine, sine, offset_x, offset_y

    @staticmethod
    def _octagon_points(x, y, diameter):
        radius = max(0.0, float(diameter)) / 2.0 / math.cos(math.pi / 8.0)
        return [
            (
                x + radius * math.cos(2.0 * math.pi * index / 8.0),
                y + radius * math.sin(2.0 * math.pi * index / 8.0),
            )
            for index in range(8)
        ]

    @staticmethod
    def _layout_positions(obj, segments, users):
        positions = {}
        for segment in segments:
            side, normal = segment_basis(segment)
            segment_positions = {}
            for cable in users[segment]:
                raw = obj.Layout.get(f"{segment.Name}|{cable.Name}")
                if raw is None:
                    continue
                try:
                    parts = [
                        float(value)
                        for value in raw.replace(";", ",").split(",")
                        if value.strip()
                    ]
                except Exception:
                    continue
                if len(parts) < 3:
                    continue
                offset = App.Vector(parts[0], parts[1], parts[2])
                segment_positions[cable] = (
                    offset.dot(side),
                    offset.dot(normal),
                )
            if segment_positions:
                positions[segment] = segment_positions
        return positions

    def _reduced_bundle_hulls(
        self,
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
                cosine, sine, offset_x, offset_y = self._fit_rigid_2d(
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
                    self._octagon_points(
                        position[0],
                        position[1],
                        cable.Diameter.Value,
                    )
                )
            if len(points) < 3:
                continue
            hull = _convex_hull_2d(points)
            if len(hull) >= 3:
                hulls[segment] = hull
        return hulls

    @staticmethod
    def _reduced_bundle_solids(hulls):
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

    @staticmethod
    def _discretize_edge(edge, max_angle=math.radians(20.0)):
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

    @staticmethod
    def _polygon_centroid(hull):
        count = len(hull)
        if count == 0:
            return 0.0, 0.0
        if count < 3:
            return (
                sum(point[0] for point in hull) / count,
                sum(point[1] for point in hull) / count,
            )
        area2 = 0.0
        center_x = 0.0
        center_y = 0.0
        for index in range(count):
            x0, y0 = hull[index]
            x1, y1 = hull[(index + 1) % count]
            cross = x0 * y1 - x1 * y0
            area2 += cross
            center_x += (x0 + x1) * cross
            center_y += (y0 + y1) * cross
        if abs(area2) < 1e-12:
            return (
                sum(point[0] for point in hull) / count,
                sum(point[1] for point in hull) / count,
            )
        return center_x / (3.0 * area2), center_y / (3.0 * area2)

    @staticmethod
    def _triangle(a, b, c):
        try:
            if (b - a).cross(c - a).Length < 1e-12:
                return None
            return Part.Face(Part.makePolygon([a, b, c, a]))
        except Exception:
            return None

    @staticmethod
    def _transition_frames(
        path_points,
        start_side,
        start_normal,
        end_side,
        end_normal,
    ):
        count = len(path_points)
        if count < 2:
            return None
        tangents = []
        for index, point in enumerate(path_points):
            if index == 0:
                tangent = path_points[1] - path_points[0]
            elif index == count - 1:
                tangent = path_points[-1] - path_points[-2]
            else:
                before = path_points[index] - path_points[index - 1]
                after = path_points[index + 1] - path_points[index]
                if before.Length < 1e-9:
                    tangent = after
                elif after.Length < 1e-9:
                    tangent = before
                else:
                    tangent = _unit_vector(before) + _unit_vector(after)
                    if tangent.Length < 1e-9:
                        tangent = before
            if tangent.Length < 1e-9:
                return None
            tangents.append(_unit_vector(tangent))

        sides = [_unit_vector(start_side)]
        normals = [_unit_vector(start_normal)]
        for index in range(1, count):
            rotation = App.Rotation(tangents[index - 1], tangents[index])
            next_side = rotation.multVec(sides[-1])
            next_side = (
                next_side
                - tangents[index] * next_side.dot(tangents[index])
            )
            next_normal = rotation.multVec(normals[-1])
            next_normal = (
                next_normal
                - tangents[index] * next_normal.dot(tangents[index])
            )
            next_side = _unit_vector(next_side)
            next_normal = _unit_vector(next_normal)
            next_normal = _unit_vector(
                next_normal - next_side * next_normal.dot(next_side)
            )
            sides.append(next_side)
            normals.append(next_normal)

        end_tangent = tangents[-1]
        end_side_projected = end_side - end_tangent * end_side.dot(end_tangent)
        end_normal_projected = (
            end_normal - end_tangent * end_normal.dot(end_tangent)
        )
        if (
            end_side_projected.Length < 1e-9
            or end_normal_projected.Length < 1e-9
        ):
            return None
        end_side_projected = _unit_vector(end_side_projected)
        end_normal_projected = _unit_vector(end_normal_projected)
        side_angle = math.atan2(
            end_tangent.dot(sides[-1].cross(end_side_projected)),
            sides[-1].dot(end_side_projected),
        )
        normal_angle = math.atan2(
            end_tangent.dot(normals[-1].cross(end_normal_projected)),
            normals[-1].dot(end_normal_projected),
        )
        difference = (normal_angle - side_angle + math.pi) % (
            2.0 * math.pi
        ) - math.pi
        if abs(difference) > math.radians(5.0):
            return None
        roll = 0.5 * (side_angle + normal_angle)
        for index in range(1, count):
            fraction = index / (count - 1)
            rotation = App.Rotation(
                tangents[index],
                math.degrees(roll * fraction),
            )
            sides[index] = _unit_vector(rotation.multVec(sides[index]))
            normals[index] = _unit_vector(rotation.multVec(normals[index]))
        return sides, normals

    def _reduced_transition_solids(
        self,
        hulls,
        counts,
        connections,
        positions_by_segment,
        packed_placements,
        routes,
        directions,
    ):
        from .WireCreator import Segment as WireSegment, WireCreator

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

            def oriented_points(segment, direction):
                start = segment.Start.getGlobalPlacement().Base
                end = segment.End.getGlobalPlacement().Base
                if int(direction) % 2:
                    return end, start
                return start, end

            first_direction = (
                route_directions[first_index]
                if first_index < len(route_directions)
                else 0
            )
            second_direction = (
                route_directions[second_index]
                if second_index < len(route_directions)
                else 0
            )
            first_oriented_start, first_oriented_end = oriented_points(
                first,
                first_direction,
            )
            second_oriented_start, second_oriented_end = oriented_points(
                second,
                second_direction,
            )
            if first_index < second_index:
                first_facing = first_oriented_end
                second_facing = second_oriented_start
            else:
                first_facing = first_oriented_start
                second_facing = second_oriented_end

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
            small_outward = _unit_vector(small_face_point - small_far_point)
            if small_outward.Length < 1e-9:
                continue

            large_start = large_segment.Start.getGlobalPlacement().Base
            large_end = large_segment.End.getGlobalPlacement().Base
            large_far_point = (
                large_end
                if (large_face_point - large_start).Length < 1e-9
                else large_start
            )
            large_inward = _unit_vector(large_far_point - large_face_point)
            if large_inward.Length < 1e-9:
                continue

            small_hull = hulls[small_segment]
            if len(small_hull) < 3:
                continue
            center_x, center_y = self._polygon_centroid(small_hull)
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
            end_rotation = App.Rotation(
                target_side,
                target_normal,
                target_side.cross(target_normal),
                "XYZ",
            )

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
                edge_points = self._discretize_edge(edge)
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
                    face = self._triangle(a, b, c)
                    if face is not None:
                        faces.append(face)
                    face = self._triangle(a, c, d)
                    if face is not None:
                        faces.append(face)
            for corner in range(1, count - 1):
                face = self._triangle(
                    sections[0][0],
                    sections[0][corner],
                    sections[0][corner + 1],
                )
                if face is not None:
                    faces.append(face)
                face = self._triangle(
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

    def _update_reduced_display(self, obj, cables):
        mode = getattr(obj, "DisplayMode", "Full Detail")
        if getattr(obj, "Pattern", "Circular") != "Packed Bundles":
            mode = "Full Detail"
        reduced_object = ensure_reduced_bundle_object(obj)
        if mode == "Reduced Bundle":
            segments = [
                segment for segment in obj.Segments if is_bundle_segment(segment)
            ]
            (
                routes,
                directions,
                users,
                counts,
                adjacency,
                connections,
                ordered,
            ) = self._route_graph(cables, segments)
            positions_by_segment = self._layout_positions(
                obj,
                segments,
                users,
            )
            hulls = self._reduced_bundle_hulls(
                users,
                counts,
                adjacency,
                connections,
                positions_by_segment,
                ordered,
            )
            solids = self._reduced_bundle_solids(hulls)
            solids.extend(
                self._reduced_transition_solids(
                    hulls,
                    counts,
                    connections,
                    positions_by_segment,
                    getattr(self, "_packed_placements", {}),
                    routes,
                    directions,
                )
            )
            if reduced_object is not None:
                try:
                    reduced_object.Shape = (
                        Part.makeCompound(solids)
                        if solids
                        else Part.Shape()
                    )
                except Exception:
                    pass
        elif reduced_object is not None:
            try:
                reduced_object.Shape = Part.Shape()
            except Exception:
                pass
        applied = getattr(self, "_applied_display_mode", None)
        if mode != applied:
            self._apply_display_visibility(obj, mode)
        self._applied_display_mode = mode

    def _apply_display_visibility(self, obj, mode):
        if not App.GuiUp:
            return
        from .WireCable import SUPPORT_OBJECT_PROPERTIES, find_container

        reduced = mode == "Reduced Bundle"
        cables = [item for item in obj.InList if is_wire_cable(item)]
        containers = set()
        for cable in cables:
            container = find_container(cable)
            if container is not None:
                containers.add(container)
            try:
                cable.ViewObject.Visibility = not reduced
            except Exception:
                pass
            for property_name in ("StartTip", "EndTip"):
                tip = getattr(cable, property_name, None)
                if tip is not None:
                    try:
                        tip.ViewObject.Visibility = not reduced
                    except Exception:
                        pass
            for property_name in SUPPORT_OBJECT_PROPERTIES:
                helper = getattr(cable, property_name, None)
                if helper is not None:
                    try:
                        helper.ViewObject.Visibility = not reduced
                    except Exception:
                        pass
        for container in containers:
            try:
                container.ViewObject.Visibility = not reduced
            except Exception:
                pass
        helper_group = getattr(obj, "HelperGroup", None)
        if helper_group is not None:
            try:
                helper_group.ViewObject.Visibility = not reduced
            except Exception:
                pass
        reduced_object = getattr(obj, "ReducedBundleObject", None)
        if reduced_object is not None:
            try:
                reduced_object.ViewObject.Visibility = (
                    reduced and not reduced_object.Shape.isNull()
                )
            except Exception:
                pass
        for property_name in ("BundleHullObject", "OverallHullObject"):
            overlay = getattr(obj, property_name, None)
            if overlay is not None:
                try:
                    overlay.ViewObject.Visibility = (
                        not reduced and not overlay.Shape.isNull()
                    )
                except Exception:
                    pass

    @staticmethod
    def _linear_positions(diameters, gap):
        total = sum(diameters) + gap * (len(diameters) - 1)
        position = -total / 2.0
        positions = []
        for diameter in diameters:
            positions.append((position + diameter / 2.0, 0.0))
            position += diameter + gap
        return positions

    @staticmethod
    def _circular_positions(diameters, gap):
        count = len(diameters)
        if count == 1:
            return [(0.0, 0.0)]
        angle_step = 2.0 * math.pi / count
        required = [
            diameters[i] / 2.0
            + gap
            + diameters[(i + 1) % count] / 2.0
            for i in range(count)
        ]
        radius = max(required) / (2.0 * math.sin(math.pi / count))
        positions = []
        for index in range(count):
            angle = index * angle_step
            positions.append((radius * math.cos(angle), radius * math.sin(angle)))
        return positions


    def onChanged(self, obj, prop):
        if prop == "DisplayMode":
            self._applied_display_mode = None
            obj.touch()
        elif prop == "Pattern":
            if (
                getattr(obj, "Pattern", "Circular") != "Packed Bundles"
                and getattr(obj, "DisplayMode", "Full Detail")
                == "Reduced Bundle"
            ):
                obj.DisplayMode = "Full Detail"
            self._applied_display_mode = None
            obj.touch()

    def dumps(self):
        return self.Type

    def loads(self, state):
        self.Type = "WireHarness"

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        ensure_segment_group(obj)
        ensure_helper_group(obj)
        ensure_hull_objects(obj)
        ensure_reduced_bundle_object(obj)
        if "Cables" in obj.PropertiesList:
            try:
                obj.removeProperty("Cables")
            except Exception:
                pass


WireBundleProxy = WireHarnessProxy


def segment_basis(segment):
    start_obj = segment.Start
    end_obj = segment.End
    if start_obj is None or end_obj is None:
        return App.Vector(1.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0)
    start = start_obj.getGlobalPlacement().Base
    end = end_obj.getGlobalPlacement().Base
    direction = end - start
    length = direction.Length
    if length < 1e-9:
        return App.Vector(1.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0)
    direction = direction / length
    orientation = 0.0
    if "Orientation" in segment.PropertiesList:
        orientation = math.radians(segment.Orientation.Value)
    side = segment_side_vector(start, end, orientation, start_obj, end_obj)
    normal = direction.cross(side)
    if normal.Length < 1e-9:
        normal = App.Vector(0.0, 0.0, 1.0)
    else:
        normal = normal.normalize()
    return side, normal


def is_harness(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) in (
        "WireHarness",
        "WireBundle",
    )


def is_wire_cable(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable"


def cable_uses_segment(cable, segment):
    points = list(getattr(cable, "Points", []))
    if not points or not all(is_bundle_segment(node) for node in points):
        return False
    return any(node is segment for node in points)


def find_harness_for_segments(nodes):
    for node in nodes:
        if not is_bundle_segment(node):
            continue
        for parent in node.InList:
            if is_harness(parent):
                return parent
    return None


def add_cable_to_harness(harness, cable):
    if not is_harness(harness):
        try:
            cable.Harness = None
        except Exception:
            pass
        return
    cable.Harness = harness
    order = list(harness.CableOrder)
    if cable.Name not in order:
        order.append(cable.Name)
        harness.CableOrder = order
    harness.touch()


def _reference_axis(ref, axis):
    if ref is None:
        return None
    try:
        return ref.getGlobalPlacement().Rotation.multVec(axis)
    except Exception:
        return None


def _averaged_reference_axis(start_ref, end_ref, axis):
    start_axis = _reference_axis(start_ref, axis)
    end_axis = _reference_axis(end_ref, axis)
    if start_axis is None and end_axis is None:
        return None
    if start_axis is None:
        return end_axis.normalize() if end_axis.Length > 1e-9 else None
    if end_axis is None:
        return start_axis.normalize() if start_axis.Length > 1e-9 else None
    combined = start_axis + end_axis
    if combined.Length < 1e-9:
        return start_axis.normalize()
    return combined.normalize()


def segment_side_vector(
    start, end, orientation=0.0, start_ref=None, end_ref=None
):
    """Lateral axis from the averaged reference frames plus manual roll."""
    direction = end - start
    length = direction.Length
    if length < 1e-9:
        return App.Vector(0.0, 0.0, 0.0)
    direction = direction / length

    side = None
    for axis in (
        App.Vector(0.0, 0.0, 1.0),
        App.Vector(0.0, 1.0, 0.0),
        App.Vector(1.0, 0.0, 0.0),
    ):
        up = _averaged_reference_axis(start_ref, end_ref, axis)
        if up is None:
            continue
        candidate = direction.cross(up)
        if candidate.Length > 1e-9:
            side = candidate.normalize()
            break

    if side is None:
        up = App.Vector(0.0, 0.0, 1.0)
        if abs(direction.dot(up)) > 0.99:
            up = App.Vector(0.0, 1.0, 0.0)
        side = direction.cross(up)
        if side.Length < 1e-9:
            side = direction.cross(App.Vector(1.0, 0.0, 0.0))
        side = side.normalize()

    if abs(orientation) > 1e-12:
        normal = direction.cross(side)
        if normal.Length > 1e-9:
            normal = normal.normalize()
            side = side * math.cos(orientation) + normal * math.sin(orientation)
    return side


class ViewProviderWireBundle:
    """Bundle view provider with tree children and editor entry point."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object
        self._setup_display_mode(vobj)

    def getIcon(self):
        return ICON

    def attach(self, vobj):
        self.Object = vobj.Object
        self._setup_display_mode(vobj)
        self._sync_visibility_mode(vobj)
        try:
            vobj.signalChangeIcon()
        except Exception:
            pass

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            self._sync_visibility_mode(vobj)
            try:
                vobj.signalChangeIcon()
            except Exception:
                pass

    @staticmethod
    def _mode_switch(vobj):
        try:
            from pivy import coin

            root = vobj.RootNode
            for i in range(root.getNumChildren()):
                node = root.getChild(i)
                if isinstance(node, coin.SoSwitch):
                    return node
        except Exception:
            pass
        return None

    def _setup_display_mode(self, vobj):
        switch = self._mode_switch(vobj)
        if switch is not None:
            try:
                if switch.getNumChildren() == 0:
                    from pivy import coin

                    self._coin_node = coin.SoSeparator()
                    vobj.addDisplayMode(self._coin_node, "Default")
            except Exception:
                self._coin_node = None
        try:
            vobj.DefaultMode = 0
        except Exception:
            pass

    @staticmethod
    def _sync_visibility_mode(vobj):
        switch = ViewProviderWireBundle._mode_switch(vobj)
        if switch is None:
            return
        try:
            switch.whichChild = 0 if vobj.Visibility else -1
        except Exception:
            pass

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        children = []
        for property_name in ("SegmentGroup", "HelperGroup"):
            group = getattr(obj, property_name, None)
            if group is not None and group.isValid() and group not in children:
                children.append(group)
        for property_name in ("BundleHullObject", "OverallHullObject"):
            hull_object = getattr(obj, property_name, None)
            if (
                hull_object is not None
                and hull_object.isValid()
                and hull_object not in children
            ):
                children.append(hull_object)
        reduced_object = getattr(obj, "ReducedBundleObject", None)
        if (
            reduced_object is not None
            and reduced_object.isValid()
            and reduced_object not in children
        ):
            children.append(reduced_object)
        if not children:
            children = list(obj.Segments)
        try:
            from .WireCable import find_container

            for cable in obj.InList:
                if not is_wire_cable(cable):
                    continue
                group = find_container(cable)
                if group is not None and group not in children:
                    children.append(group)
        except Exception:
            pass
        return children

    def setEdit(self, vobj, mode):
        if mode != 0:
            return False
        from .WireBundleTaskPanel import WireBundleTaskPanel

        harness = vobj.Object
        selected_segment = None
        for selected in Gui.Selection.getSelection():
            if is_bundle_segment(selected) and selected in harness.Segments:
                selected_segment = selected
                break
        Gui.Control.showDialog(WireBundleTaskPanel(bundle=harness))
        try:
            from .WireSelection import schedule_select_tool_object

            schedule_select_tool_object(selected_segment or harness)
        except Exception:
            pass
        return True

    def unsetEdit(self, vobj, mode):
        if mode != 0:
            return False
        Gui.Control.closeDialog()
        try:
            from .WireSelection import schedule_clear_tool_selection

            schedule_clear_tool_selection(vobj.Object)
        except Exception:
            pass
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object, 0)
        return True

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        document = obj.Document
        document_name = document.Name
        segment_names = [
            segment.Name for segment in obj.Segments if segment.isValid()
        ]
        group_names = []
        for property_name in (
            "SegmentGroup",
            "HelperGroup",
            "BundleHullObject",
            "OverallHullObject",
            "ReducedBundleObject",
        ):
            group = getattr(obj, property_name, None)
            if group is not None and group.isValid():
                group_names.append(group.Name)

        def cleanup():
            doc = App.getDocument(document_name)
            if doc is None:
                return
            for name in segment_names:
                if doc.getObject(name) is not None:
                    try:
                        doc.removeObject(name)
                    except Exception:
                        pass
            for group_name in group_names:
                if doc.getObject(group_name) is not None:
                    try:
                        doc.removeObject(group_name)
                    except Exception:
                        pass

        try:
            from PySide import QtCore

            QtCore.QTimer.singleShot(0, cleanup)
        except Exception:
            cleanup()
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


ViewProviderWireHarness = ViewProviderWireBundle


class WireBundleSegmentProxy:
    """Straight bundle segment displayed as a pickable cylinder."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = BUNDLE_SEGMENT_TYPE
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        _ensure_global_link(obj, "Start", "Segment start point reference")
        _ensure_global_link(obj, "End", "Segment end point reference")
        if "Radius" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyLength",
                "Radius",
                "Segment",
                "Visualization radius",
            )
            obj.Radius = 10.0
        if "Orientation" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyAngle",
                "Orientation",
                "Segment",
                "Rotation of the cable arrangement about the segment axis",
            )
            obj.Orientation = 0.0
        if "MaxCables" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyInteger",
                "MaxCables",
                "Segment",
                "Maximum cables allowed in this segment (0 = unlimited)",
            )
            obj.MaxCables = 0
        if "SegmentType" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "SegmentType",
                "Segment",
                "Closed = end-to-end connections only; Open = wires may enter/exit anywhere",
            )
            obj.SegmentType = ["Closed", "Open"]
            obj.SegmentType = "Closed"
        if "SegmentRole" not in obj.PropertiesList:
            role = LACE_HELPER_ROLE if obj.Label.startswith("Lace Helper ") else ROUTE_SEGMENT_ROLE
            obj.addProperty(
                "App::PropertyEnumeration",
                "SegmentRole",
                "Segment",
                "Route = user routing segment; Lace Helper = auto-generated helper",
            )
            obj.SegmentRole = [ROUTE_SEGMENT_ROLE, LACE_HELPER_ROLE]
            obj.SegmentRole = role
        if "Dependencies" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyLinkListGlobal",
                "Dependencies",
                "Segment",
                "Ancestor groups that affect the reference placements",
            )
            try:
                obj.setEditorMode("Dependencies", 2)
            except Exception:
                pass
        if "HullCurve" not in obj.PropertiesList:
            obj.addProperty(
                "Part::PropertyPartShape",
                "HullCurve",
                "Segment",
                "Convex hull of the cable bundle at the segment start",
            )
            try:
                obj.setEditorMode("HullCurve", 2)
            except Exception:
                pass

    def execute(self, obj):
        start_obj = obj.Start
        end_obj = obj.End
        if start_obj is None or end_obj is None:
            obj.Shape = Part.Shape()
            return
        start = start_obj.getGlobalPlacement().Base
        end = end_obj.getGlobalPlacement().Base
        direction = end - start
        length = direction.Length
        if length < 1e-9 or obj.Radius.Value <= 0.0:
            obj.Shape = Part.Shape()
            return
        obj.Shape = Part.makeCylinder(
            obj.Radius.Value, length, start, direction / length
        )
        if App.GuiUp:
            try:
                view = obj.ViewObject
                if getattr(view, "Proxy", None) is None:
                    view.Proxy = 1
                    view.Visibility = True
                view.signalChangeIcon()
            except Exception:
                pass

    def onChanged(self, obj, prop):
        if prop not in ("MaxCables", "SegmentType"):
            return
        for parent in obj.InList:
            if getattr(getattr(parent, "Proxy", None), "Type", None) in (
                "WireCable",
                "WireHarness",
            ):
                try:
                    parent.touch()
                except Exception:
                    pass

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)



def _ensure_global_link(obj, name, description):
    """Use global links so segment references may point into App::Part scopes."""
    if name in obj.PropertiesList:
        if obj.getTypeIdOfProperty(name) == "App::PropertyLinkGlobal":
            return
        value = getattr(obj, name)
        obj.removeProperty(name)
    else:
        value = None
    obj.addProperty("App::PropertyLinkGlobal", name, "Segment", description)
    if value is not None:
        setattr(obj, name, value)


def ancestor_groups(obj):
    groups = []
    seen = set()
    try:
        parent = obj.getParentGeoFeatureGroup()
    except Exception:
        parent = None
    while parent is not None:
        if parent.Name in seen:
            break
        seen.add(parent.Name)
        groups.append(parent)
        try:
            parent = parent.getParentGeoFeatureGroup()
        except Exception:
            parent = None
    return groups


def update_segment_dependencies(segment):
    """Depend on ancestor groups so moving an enclosing Part recomputes us."""
    dependencies = []
    seen = set()
    for ref in (segment.Start, segment.End):
        if ref is None:
            continue
        for group in ancestor_groups(ref):
            if group.Name in seen:
                continue
            seen.add(group.Name)
            dependencies.append(group)
    if "Dependencies" in segment.PropertiesList:
        segment.Dependencies = dependencies


def ensure_segment_group(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    group = getattr(harness, "SegmentGroup", None)
    if group is None or not group.isValid() or group.Document is not document:
        name = "Segments"
        index = 1
        while document.getObject(name) is not None:
            name = f"Segments{index:03d}"
            index += 1
        group = document.addObject("App::DocumentObjectGroup", name)
        group.Label = "Segments"
        harness.SegmentGroup = group
    desired = [
        segment for segment in harness.Segments if not is_lace_helper(segment)
    ]
    current = list(group.Group)
    if current != desired:
        group.Group = desired
    return group


def ensure_helper_group(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    group = getattr(harness, "HelperGroup", None)
    if group is None or not group.isValid() or group.Document is not document:
        name = "LaceHelpers"
        index = 1
        while document.getObject(name) is not None:
            name = f"LaceHelpers{index:03d}"
            index += 1
        group = document.addObject("App::DocumentObjectGroup", name)
        group.Label = "Lace Helpers"
        harness.HelperGroup = group
    desired = [
        segment for segment in harness.Segments if is_lace_helper(segment)
    ]
    desired_set = set(desired)
    for child in list(group.Group):
        if is_bundle_segment(child) and child not in desired_set:
            group.removeObject(child)
    current_names = {child.Name for child in group.Group}
    for segment in desired:
        if segment.Name not in current_names:
            group.addObject(segment)
    return group


def ensure_hull_objects(harness):
    if harness is None or harness.Document is None:
        return None, None
    document = harness.Document

    def ensure(property_name, name, label, color):
        obj = getattr(harness, property_name, None)
        if obj is None or not obj.isValid() or obj.Document is not document:
            obj = document.addObject("Part::Feature", name)
            obj.Label = label
            setattr(harness, property_name, obj)
        if App.GuiUp:
            try:
                obj.ViewObject.Selectable = False
                obj.ViewObject.LineColor = color
                obj.ViewObject.LineWidth = 2
                obj.ViewObject.ShapeColor = color
            except Exception:
                pass
        return obj

    bundle_object = ensure(
        "BundleHullObject",
        "BundleHulls",
        "Bundle Hulls",
        (0.1, 0.85, 0.2),
    )
    overall_object = ensure(
        "OverallHullObject",
        "OverallHull",
        "Overall Hull",
        (1.0, 0.55, 0.0),
    )
    return bundle_object, overall_object


def ensure_reduced_bundle_object(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    obj = getattr(harness, "ReducedBundleObject", None)
    if obj is not None and obj.isValid() and obj.Document is document:
        return obj
    obj = document.addObject("Part::Feature", "ReducedBundles")
    obj.Label = "Reduced Bundles"
    harness.ReducedBundleObject = obj
    if App.GuiUp:
        try:
            obj.ViewObject.Selectable = False
            obj.ViewObject.ShapeColor = (0.5, 0.55, 0.62)
            obj.ViewObject.LineColor = (0.35, 0.4, 0.48)
            obj.ViewObject.Transparency = 0
            obj.ViewObject.Visibility = False
        except Exception:
            pass
    return obj


def create_wire_harness(document, label="Harness"):
    harness = document.addObject("App::FeaturePython", "WireHarness")
    harness.Label = label
    WireHarnessProxy(harness)
    ensure_segment_group(harness)
    ensure_helper_group(harness)
    ensure_hull_objects(harness)
    ensure_reduced_bundle_object(harness)
    if App.GuiUp:
        ViewProviderWireHarness(harness.ViewObject)
    return harness


def create_wire_bundle(document, label="Harness"):
    return create_wire_harness(document, label=label)


def create_bundle_segment(bundle, start, end, radius=10.0, segment_type="Closed"):
    document = bundle.Document
    segment = document.addObject("Part::FeaturePython", "BundleSegment")
    segment.Label = "Bundle Segment"
    WireBundleSegmentProxy(segment)
    segment.Start = start
    segment.End = end
    segment.Radius = radius
    segment.SegmentType = segment_type
    update_segment_dependencies(segment)
    if App.GuiUp:
        try:
            segment.ViewObject.ShapeColor = (0.33, 0.33, 0.36)
            segment.ViewObject.Transparency = 65
            segment.ViewObject.Visibility = True
            segment.ViewObject.signalChangeIcon()
        except Exception:
            pass
    segments = list(bundle.Segments)
    segments.append(segment)
    bundle.Segments = segments
    ensure_segment_group(bundle)
    ensure_helper_group(bundle)
    return segment


def remove_bundle_segment(bundle, segment):
    segments = [item for item in bundle.Segments if item is not segment]
    bundle.Segments = segments
    ensure_segment_group(bundle)
    ensure_helper_group(bundle)
    document = bundle.Document
    if document.getObject(segment.Name) is segment:
        document.removeObject(segment.Name)
