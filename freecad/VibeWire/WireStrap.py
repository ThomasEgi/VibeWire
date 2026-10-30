"""Reusable plastic-strap geometry for harness wrapping."""

import hashlib
import math

import FreeCAD as App
import Part

from .WireFrames import segment_basis


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


_HEAD_CACHE = {}


def _make_head_local(spec):
    key = (
        spec.head_height,
        spec.head_length,
        spec.head_width,
        spec.hole_length,
        spec.hole_width,
        spec.head_clearance,
        spec.draft_angle,
        spec.head_chamfer,
        spec.head_chamfer_edges,
    )
    cached = _HEAD_CACHE.get(key)
    if cached is not None:
        return cached
    head_y = -spec.head_length / 2.0 - spec.hole_length / 2.0
    head_z = -spec.head_width / 2.0
    inner_x = -spec.head_height / 2.0
    outer_x = spec.head_height / 2.0
    draft = spec.head_height * math.tan(math.radians(spec.draft_angle))
    draft = min(draft, spec.head_length / 2.0 - 1e-6)
    draft = min(draft, spec.head_width / 2.0 - 1e-6)
    inner_wire = Part.makePolygon(
        [
            App.Vector(inner_x, head_y, head_z),
            App.Vector(inner_x, head_y + spec.head_length, head_z),
            App.Vector(
                inner_x,
                head_y + spec.head_length,
                head_z + spec.head_width,
            ),
            App.Vector(inner_x, head_y, head_z + spec.head_width),
            App.Vector(inner_x, head_y, head_z),
        ]
    )
    outer_wire = Part.makePolygon(
        [
            App.Vector(outer_x, head_y + draft, head_z + draft),
            App.Vector(
                outer_x,
                head_y + spec.head_length - draft,
                head_z + draft,
            ),
            App.Vector(
                outer_x,
                head_y + spec.head_length - draft,
                head_z + spec.head_width - draft,
            ),
            App.Vector(
                outer_x,
                head_y + draft,
                head_z + spec.head_width - draft,
            ),
            App.Vector(outer_x, head_y + draft, head_z + draft),
        ]
    )
    head_box = Part.makeLoft([inner_wire, outer_wire], True, True, False)
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
    head = head_box.cut(hole_box)
    if spec.head_chamfer > 0.0 and spec.head_chamfer_edges:
        edges = [
            head.Edges[index - 1]
            for index in spec.head_chamfer_edges
            if index <= len(head.Edges)
        ]
        if edges:
            head = head.makeChamfer(spec.head_chamfer, edges)
    _HEAD_CACHE[key] = head
    return head


STRAP_TABLE = [
    (2.5, 100.0, 1.0, 20.0),
    (2.5, 150.0, 1.0, 36.0),
    (2.5, 200.0, 1.0, 59.0),
    (2.5, 250.0, 1.0, 68.0),
    (3.6, 150.0, 1.2, 36.0),
    (3.6, 200.0, 1.2, 52.0),
    (3.6, 250.0, 1.2, 68.0),
    (3.6, 300.0, 1.2, 84.0),
    (3.6, 350.0, 1.2, 99.0),
    (3.6, 400.0, 1.2, 113.0),
    (4.8, 200.0, 1.4, 49.0),
    (4.8, 250.0, 1.4, 65.0),
    (4.8, 300.0, 1.4, 81.0),
    (4.8, 350.0, 1.4, 97.0),
    (4.8, 400.0, 1.4, 113.0),
    (4.8, 500.0, 1.4, 145.0),
    (4.8, 600.0, 1.4, 179.0),
    (4.8, 750.0, 1.4, 216.0),
    (7.6, 200.0, 1.6, 55.0),
    (7.6, 250.0, 1.6, 70.0),
    (7.6, 300.0, 1.6, 80.0),
    (7.6, 400.0, 1.6, 110.0),
    (7.6, 500.0, 1.6, 145.0),
    (7.6, 600.0, 1.6, 180.0),
    (7.6, 750.0, 1.6, 230.0),
    (12.4, 200.0, 2.0, 57.0),
    (12.4, 300.0, 2.0, 76.0),
    (12.4, 400.0, 2.0, 108.0),
    (12.4, 500.0, 2.0, 156.0),
    (12.4, 600.0, 2.0, 195.0),
    (12.4, 750.0, 2.0, 216.0),
    (12.4, 1000.0, 2.0, 305.0),
]


def polygon_perimeter(points):
    if len(points) < 2:
        return 0.0
    return sum(
        (points[(index + 1) % len(points)] - points[index]).Length
        for index in range(len(points))
    )


def select_strap_spec(circumference, table=None):
    table = STRAP_TABLE if table is None else table
    equivalent_diameter = circumference / math.pi
    rows_by_width = {}
    for row in table:
        rows_by_width.setdefault(float(row[0]), []).append(row)
    fitting_widths = [
        width
        for width, rows in rows_by_width.items()
        if max(row[3] for row in rows) >= equivalent_diameter
    ]
    if not fitting_widths:
        raise ValueError(
            "no strap size fits bundle diameter %.3f mm"
            % equivalent_diameter
        )
    width = min(fitting_widths)
    fitting_rows = [
        row
        for row in rows_by_width[width]
        if row[3] >= equivalent_diameter
    ]
    row = min(fitting_rows, key=lambda item: item[3])
    spec = StrapSpec(
        width=row[0],
        length=row[1],
        thickness=row[2],
        max_bundle_diameter=row[3],
    )
    return spec, row, equivalent_diameter


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
        draft_angle=8.0,
        head_chamfer=0.2,
        head_chamfer_edges=(2, 4, 12, 20, 3, 13, 14, 15),
    ):
        self.width = float(width)
        self.length = float(length)
        self.thickness = float(thickness)
        self.max_bundle_diameter = max_bundle_diameter
        self.head_clearance = float(head_clearance)
        self.end_lift_factor = float(end_lift_factor)
        self.draft_angle = float(draft_angle)
        self.head_chamfer = float(head_chamfer)
        self.head_chamfer_edges = tuple(head_chamfer_edges)
        self.head_width = self.width + 4.0 * self.thickness
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
    ):
        self.spec = spec
        self.hull = self._prepare_hull(hull)
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
        base_offset = max(
            self.head_lift,
            self.spec.head_height / 2.0 + 0.1,
        )
        base_candidate = (
            self.head_placement
            - radial * base_offset
            - tangential * (self.spec.thickness / 2.0)
        )
        lower_candidate = (
            self.head_placement
            - radial * (base_offset + self.spec.thickness / 2.0)
            - tangential * (self.spec.thickness / 2.0)
        )
        candidates = [lower_candidate]
        if (base_candidate - lower_candidate).Length > 1e-9:
            candidates.append(base_candidate)
        for candidate in candidates:
            self.bend_point = candidate
            self.strap_hull = _convex_hull_2d(self.hull + [self.bend_point])
            self.strap_head_index = self._nearest_index(
                self.strap_hull, self.head_start
            )
            self.bend_index = self._nearest_index(
                self.strap_hull, self.bend_point
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
            if (
                self.strap_shape.isValid()
                and self.strap_shape.Solids
                and self.strap_shape.Volume > 0.0
            ):
                break
        else:
            raise RuntimeError("strap build failed for both bend points")
        self.strap_path_length = sum(
            (self.wrap_path[index + 1] - self.wrap_path[index]).Length
            for index in range(len(self.wrap_path) - 1)
        )
        self.head_shape = _make_head_local(self.spec)

    @staticmethod
    def _prepare_hull(hull):
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
        return points

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

    @staticmethod
    def _closest_on_polygon(point, polygon):
        best = None
        for index, first in enumerate(polygon):
            second = polygon[(index + 1) % len(polygon)]
            edge = second - first
            length2 = edge.Length**2
            if length2 < 1e-12:
                continue
            parameter = max(
                0.0,
                min(1.0, (point - first).dot(edge) / length2),
            )
            closest = first + edge * parameter
            distance = (point - closest).Length
            if best is None or distance < best[0]:
                best = (distance, index, parameter, closest)
        if best is None:
            raise ValueError("cannot project point onto polygon")
        return best[1], best[2], best[3]

    def _wrap_path(self):
        count = len(self.offset_hull)
        edge_index, parameter, projected = self._closest_on_polygon(
            self.strap_start_center,
            self.offset_hull,
        )

        def sequence_forward(edge, parameter):
            points = [projected]
            if parameter < 1.0 - 1e-9:
                index = (edge + 1) % count
            else:
                index = (edge + 2) % count
            while True:
                points.append(self.offset_hull[index])
                if index == self.bend_index:
                    break
                index = (index + 1) % count
            return points

        def sequence_backward(edge, parameter):
            points = [projected]
            if parameter > 1e-9:
                index = edge
            else:
                index = (edge - 1) % count
            while True:
                points.append(self.offset_hull[index])
                if index == self.bend_index:
                    break
                index = (index - 1) % count
            return points

        forward = sequence_forward(edge_index, parameter)
        backward = sequence_backward(edge_index, parameter)

        def length(points):
            return sum(
                (points[position + 1] - points[position]).Length
                for position in range(len(points) - 1)
            )

        path = forward if length(forward) >= length(backward) else backward
        result = [self.strap_start_center]
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
        for transition in (1, 0, 2):
            try:
                shape = wire.makePipeShell([profile], True, False, transition)
                if shape.isValid() and shape.Solids:
                    return shape
            except Exception:
                continue
        raise RuntimeError("strap sweep failed")


def build_strap(hull):
    """Build one combined strap+head solid from a local 2D convex hull."""
    points = [_vector(point) for point in hull]
    if len(points) < 3:
        raise ValueError("strap hull needs at least three points")
    perimeter = polygon_perimeter(points)
    spec, row, equivalent_diameter = select_strap_spec(perimeter)
    builder = StrapBuilder(points, spec)
    head_local = builder.head_shape.transformGeometry(
        App.Placement(builder.head_placement, builder.head_rotation).toMatrix()
    )
    shape = builder.strap_shape.fuse(head_local)
    if not shape.isValid() or not shape.Solids:
        shape = Part.makeCompound([builder.strap_shape, head_local])
    if not shape.isValid() or not shape.Solids:
        raise ValueError("strap geometry could not be built")
    utilized_length = builder.strap_path_length + spec.head_length
    return shape, builder, spec, row, equivalent_diameter, utilized_length


_STRAP_SIGNATURE_PREFIX = (
    "v1:"
    + hashlib.sha1(repr(STRAP_TABLE).encode("utf-8")).hexdigest()
)


def hull_signature(hull):
    """Stable signature for a local strap hull so unchanged straps can be reused."""
    text = "\n".join(
        "%.9f,%.9f" % (float(point.x), float(point.y))
        for point in hull
    )
    digest = hashlib.sha1(text.encode("ascii")).hexdigest()
    return _STRAP_SIGNATURE_PREFIX + ":" + digest


class WireStrapProxy:
    """Persistent strap object that only depends on its bundle segment hull."""

    Type = "WireStrap"

    def __init__(self, obj):
        obj.Proxy = self
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        properties = obj.PropertiesList
        if "Segment" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "Segment",
                "Strap",
                "Wrapped bundle segment",
            )
        if "StrapWidth" not in properties:
            obj.addProperty(
                "App::PropertyLength", "StrapWidth", "Strap", "Axial width"
            )
        if "StrapThickness" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "StrapThickness",
                "Strap",
                "Radial thickness",
            )
        if "StrapLength" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "StrapLength",
                "Strap",
                "Uncut strap length from the table",
            )
        if "MaxStrapDiameter" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "MaxStrapDiameter",
                "Strap",
                "Maximum bundle diameter",
            )
        if "StrapPathLength" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "StrapPathLength",
                "Strap",
                "Centerline length of the generated strap path",
            )
        if "UtilizedStrapLength" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "UtilizedStrapLength",
                "Strap",
                "Strap path length plus head length",
            )
        if "StrapSignature" not in properties:
            obj.addProperty(
                "App::PropertyString",
                "StrapSignature",
                "Strap",
                "Signature of the hull used to build this strap",
            )
            try:
                obj.setEditorMode("StrapSignature", 2)
            except Exception:
                pass

    @staticmethod
    def _segment_inputs(segment):
        start_obj = getattr(segment, "Start", None)
        end_obj = getattr(segment, "End", None)
        if start_obj is None or end_obj is None:
            return None
        if "HullCurve" not in segment.PropertiesList:
            return None
        hull_curve = segment.HullCurve
        if hull_curve is None or hull_curve.isNull():
            return None
        start = start_obj.getGlobalPlacement().Base
        end = end_obj.getGlobalPlacement().Base
        direction = end - start
        length = direction.Length
        if length < 1e-9:
            return None
        direction = direction / length
        side, normal = segment_basis(segment)
        hull = []
        for vertex in hull_curve.Vertexes:
            point = vertex.Point - start
            hull.append(
                App.Vector(
                    point.dot(side),
                    point.dot(normal),
                    0.0,
                )
            )
        if len(hull) < 3:
            return None
        midpoint = start + direction * (length / 2.0)
        rotation = App.Rotation(side, normal, direction, "XYZ")
        return hull, App.Placement(midpoint, rotation)

    def execute(self, obj):
        try:
            inputs = self._segment_inputs(obj.Segment)
        except Exception:
            inputs = None
        if inputs is None:
            obj.Shape = Part.Shape()
            return
        hull, placement = inputs
        signature = hull_signature(hull)
        if (
            getattr(obj, "StrapSignature", "") == signature
            and not obj.Shape.isNull()
        ):
            obj.Placement = placement
            return
        try:
            shape, builder, spec, _row, _diameter, utilized_length = build_strap(
                hull
            )
        except Exception:
            obj.Shape = Part.Shape()
            return
        obj.Shape = shape
        obj.Placement = placement
        obj.StrapWidth = spec.width
        obj.StrapThickness = spec.thickness
        obj.StrapLength = spec.length
        obj.MaxStrapDiameter = spec.max_bundle_diameter
        obj.StrapPathLength = builder.strap_path_length
        obj.UtilizedStrapLength = utilized_length
        obj.StrapSignature = signature

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
