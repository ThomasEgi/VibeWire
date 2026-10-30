import math

import FreeCAD as App
import Part


def _vector(point):
    if isinstance(point, App.Vector):
        return App.Vector(point.x, point.y, 0.0)
    return App.Vector(float(point[0]), float(point[1]), 0.0)


def _signed_area(points):
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point.x * nxt.y - nxt.x * point.y
    return area / 2.0


def _line_intersection(a1, a2, b1, b2):
    da = a2 - a1
    db = b2 - b1
    denominator = da.x * db.y - da.y * db.x
    if abs(denominator) < 1e-12:
        raise ValueError("parallel offset edges")
    factor = ((b1.x - a1.x) * db.y - (b1.y - a1.y) * db.x) / denominator
    return App.Vector(a1.x + da.x * factor, a1.y + da.y * factor, 0.0)


def offset_convex_polygon(points, distance):
    points = [_vector(point) for point in points]
    if _signed_area(points) < 0.0:
        points.reverse()
    lines = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        edge = end - start
        length = edge.Length
        if length < 1e-12:
            continue
        normal = App.Vector(edge.y / length, -edge.x / length, 0.0)
        lines.append((start + normal * distance, end + normal * distance))
    if len(lines) != len(points):
        raise ValueError("degenerate hull edge")
    result = []
    for index in range(len(points)):
        previous = lines[index - 1]
        current = lines[index]
        result.append(
            _line_intersection(
                previous[0],
                previous[1],
                current[0],
                current[1],
            )
        )
    return result


def _closed_wire(points):
    return Part.makePolygon(list(points) + [points[0]])


def _point_line_distance(point, first, second):
    edge = second - first
    length = edge.Length
    if length < 1e-12:
        return (point - first).Length
    return abs((point - first).cross(edge).Length) / length


def _convex_hull_2d(points):
    unique = sorted(set((round(float(point.x), 9), round(float(point.y), 9)) for point in points))
    if len(unique) <= 1:
        return [App.Vector(x, y, 0.0) for x, y in unique]
    lower = []
    for point in unique:
        while (
            len(lower) >= 2
            and (
                (lower[-1][0] - lower[-2][0]) * (point[1] - lower[-2][1])
                - (lower[-1][1] - lower[-2][1]) * (point[0] - lower[-2][0])
            )
            <= 0.0
        ):
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while (
            len(upper) >= 2
            and (
                (upper[-1][0] - upper[-2][0]) * (point[1] - upper[-2][1])
                - (upper[-1][1] - upper[-2][1]) * (point[0] - upper[-2][0])
            )
            <= 0.0
        ):
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    result = [App.Vector(x, y, 0.0) for x, y in hull]
    if _signed_area(result) < 0.0:
        result.reverse()
    return result


def _simplify_hull(points, tolerance, min_vertices=12):
    if tolerance <= 0.0:
        return points
    result = list(points)
    minimum = max(3, min_vertices)
    while len(result) > minimum:
        kept = []
        removed = False
        count = len(result)
        for index in range(count):
            previous = result[index - 1]
            current = result[index]
            following = result[(index + 1) % count]
            if (
                _point_line_distance(current, previous, following)
                <= tolerance
            ):
                removed = True
                continue
            kept.append(current)
        if not removed:
            break
        if len(kept) >= minimum:
            result = kept
            continue
        reduced = result[::2]
        if len(reduced) < minimum:
            break
        result = reduced
    return result


def _make_head_local(spec):
    head_y = -spec.head_length / 2.0 - spec.hole_length / 2.0
    head_z = -spec.head_width / 2.0
    head_box = Part.makeBox(
        spec.head_height,
        spec.head_length,
        spec.head_width,
        App.Vector(-spec.head_height / 2.0, head_y, head_z),
    )
    hole_box = Part.makeBox(
        spec.head_height + 2.0 * spec.head_clearance,
        spec.hole_length,
        spec.hole_width,
        App.Vector(
            -spec.head_height / 2.0 - spec.head_clearance,
            -spec.hole_length / 2.0,
            -spec.hole_width / 2.0,
        ),
    )
    return head_box.cut(hole_box)


class StrapSpec:
    def __init__(
        self,
        width,
        length,
        thickness,
        max_bundle_diameter=None,
        hole_clearance=0.8,
        head_clearance=0.1,
        end_lift_factor=1.5,
    ):
        self.width = float(width)
        self.length = float(length)
        self.thickness = float(thickness)
        self.max_bundle_diameter = max_bundle_diameter
        self.head_clearance = float(head_clearance)
        self.end_lift_factor = float(end_lift_factor)
        self.head_width = self.width + 2.0 * self.thickness
        self.head_height = self.width
        self.head_length = self.head_width
        self.hole_width = self.width + float(hole_clearance)
        self.hole_length = self.thickness + float(hole_clearance)


class StrapBuilder:
    """Build a plastic strap and head around a convex hull in local XY."""

    def __init__(
        self,
        hull,
        spec,
        head_index=None,
        lift_factor=None,
        simplify_tolerance=0.2,
    ):
        self.spec = spec
        self.hull = self._prepare_hull(hull, simplify_tolerance)
        self.head_index = self._default_head_index() if head_index is None else head_index
        self.head_index %= len(self.hull)
        self.lift_factor = (
            spec.end_lift_factor if lift_factor is None else float(lift_factor)
        )
        self.head_start = self.hull[self.head_index]
        self.head_tangent, self.head_normal = self._head_frame()
        self.head_lift = self.lift_factor * self.spec.thickness
        self.edge4 = self._edge4_point()
        self.end_index = self._end_index()
        self.head_rotation, self.head_placement = self._head_placement()
        radial = self.head_rotation.multVec(App.Vector(1.0, 0.0, 0.0))
        self.hole_inner = self.head_placement - radial * (self.spec.head_height / 2.0)
        self.hole_top = self.head_placement + radial * (self.spec.head_height / 2.0)
        tangential = self.head_rotation.multVec(App.Vector(0.0, 1.0, 0.0))
        self.bend_point = (
            self.head_placement
            - radial * self.head_lift
            - tangential * (self.spec.thickness / 2.0)
        )
        self.strap_hull = _convex_hull_2d(self.hull + [self.bend_point])
        self.strap_head_index = self._nearest_index(
            self.strap_hull, self.head_start
        )
        self.bend_index = min(
            (
                index
                for index in range(len(self.strap_hull))
                if index != self.strap_head_index
            ),
            key=lambda index: (self.strap_hull[index] - self.bend_point).Length,
        )
        self.offset_hull = offset_convex_polygon(
            self.strap_hull, self.spec.thickness / 2.0
        )
        self.strap_start_center = (
            self.head_start
            + self.head_normal * (self.spec.thickness / 2.0)
        )
        self.wrap_path = self._wrap_path()
        self.strap_shape = self._make_strap()
        self.head_shape = _make_head_local(self.spec)

    @staticmethod
    def _prepare_hull(hull, simplify_tolerance):
        points = []
        for point in hull:
            vector = _vector(point)
            if not points or (vector - points[-1]).Length > 1e-9:
                points.append(vector)
        if len(points) > 1 and (points[0] - points[-1]).Length < 1e-9:
            points.pop()
        if len(points) < 3:
            raise ValueError("hull needs at least three points")
        if _signed_area(points) < 0.0:
            points.reverse()
        return _simplify_hull(points, simplify_tolerance)

    def _default_head_index(self):
        return max(range(len(self.hull)), key=lambda index: self.hull[index].x)

    def _head_frame(self):
        count = len(self.hull)
        previous = self.hull[self.head_index - 1]
        current = self.hull[self.head_index]
        following = self.hull[(self.head_index + 1) % count]
        tangent = following - previous
        if tangent.Length < 1e-9:
            tangent = following - current
        tangent.normalize()
        normals = []
        for first, second in ((previous, current), (current, following)):
            edge = second - first
            if edge.Length > 1e-9:
                normals.append(App.Vector(edge.y, -edge.x, 0.0).normalize())
        normal = App.Vector()
        for candidate in normals:
            normal += candidate
        if normal.Length < 1e-9:
            normal = App.Vector(tangent.y, -tangent.x, 0.0)
        normal.normalize()
        if normal.dot(current - self._centroid()) < 0.0:
            normal = normal * -1.0
        return tangent, normal

    def _centroid(self):
        center = App.Vector()
        for point in self.hull:
            center += point
        return center / len(self.hull)

    def _edge4_point(self):
        span = self.spec.head_length**2 - self.head_lift**2
        if span <= 0.0:
            raise ValueError("head length must exceed end lift")
        return (
            self.head_start
            + self.head_tangent * math.sqrt(span)
            + self.head_normal * self.head_lift
        )

    def _end_index(self):
        candidates = [
            index for index in range(len(self.hull)) if index != self.head_index
        ]
        return min(candidates, key=lambda index: (self.hull[index] - self.edge4).Length)

    @staticmethod
    def _nearest_index(points, target):
        return min(
            range(len(points)),
            key=lambda index: (points[index] - target).Length,
        )

    def _head_placement(self):
        direction = self.edge4 - self.head_start
        angle = math.atan2(-direction.x, direction.y)
        rotation = App.Rotation(App.Vector(0, 0, 1), math.degrees(angle))
        local_start = App.Vector(
            -self.spec.head_height / 2.0,
            -(self.spec.head_length + self.spec.hole_length) / 2.0,
            0.0,
        )
        placement = self.head_start - rotation.multVec(local_start)
        return rotation, placement

    def _wrap_path(self):
        count = len(self.offset_hull)
        forward = []
        index = self.strap_head_index
        while True:
            forward.append(self.offset_hull[index])
            if index == self.bend_index:
                break
            index = (index + 1) % count
        backward = []
        index = self.strap_head_index
        while True:
            backward.append(self.offset_hull[index])
            if index == self.bend_index:
                break
            index = (index - 1) % count

        def length(points):
            return sum(
                (points[position + 1] - points[position]).Length
                for position in range(len(points) - 1)
            )

        path = forward if length(forward) >= length(backward) else backward
        result = [self.strap_start_center]
        if len(path) > 1:
            result.extend(path[1:])
        result.append(self.hole_top)
        return result

    def _make_strap(self):
        start = self.wrap_path[0]
        following = self.wrap_path[1]
        tangent = following - start
        tangent.normalize()
        outward = start - self._centroid()
        outward = outward - tangent * outward.dot(tangent)
        if outward.Length < 1e-9:
            outward = App.Vector(-tangent.y, tangent.x, 0.0)
        outward.normalize()
        half = self.spec.thickness / 2.0
        half_width = self.spec.width / 2.0
        profile = Part.makePolygon(
            [
                start - outward * half + App.Vector(0, 0, -half_width),
                start + outward * half + App.Vector(0, 0, -half_width),
                start + outward * half + App.Vector(0, 0, half_width),
                start - outward * half + App.Vector(0, 0, half_width),
                start - outward * half + App.Vector(0, 0, -half_width),
            ]
        )
        wire = Part.Wire(Part.makePolygon(self.wrap_path))
        for transition in (2, 1, 0):
            try:
                shape = wire.makePipeShell([profile], True, False, transition)
                if shape.isValid() and shape.Solids:
                    return shape
            except Exception:
                continue
        raise RuntimeError("strap sweep failed")
