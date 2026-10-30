import csv
import math
import os

import Part

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
CSV_PATH = os.path.join(SNIPPET_DIR, "strapsizes.csv")
DOC_PATH = os.path.join(os.path.dirname(SNIPPET_DIR), "BundleWrappingPoC.FCStd")
DOC_NAME = "BundleWrappingPoC"

with open(CSV_PATH, encoding="utf-8-sig", newline="") as handle:
    row = next(csv.DictReader(handle))

width = float(row["width"])
length = float(row["length"])
thickness = float(row["thickness"])
max_bundle_diameter = float(row["Max. bundle diameter [mm]"])
head_width = width + 2.0 * thickness
head_height = width
head_length = head_width
hole_width = width + 0.8
hole_length = thickness + 0.8
head_clearance = 0.1
head_start_y = -1.7673787374119105

print("CSV row:", row)
print(
    "Strap: width %.3f mm, length %.3f mm, thickness %.3f mm, max bundle Ø %.3f mm"
    % (width, length, thickness, max_bundle_diameter)
)
print(
    "Head: width %.3f mm, height %.3f mm, length %.3f mm"
    % (head_width, head_height, head_length)
)
print(
    "Hole: width %.3f mm, length %.3f mm"
    % (hole_width, hole_length)
)


def regular_polygon(sides, radius, z, phase=0.0):
    points = []
    for index in range(sides):
        angle = phase + 2.0 * math.pi * index / sides
        points.append(
            App.Vector(
                radius * math.cos(angle),
                radius * math.sin(angle),
                z,
            )
        )
    return points


def polygon_area(points):
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point.x * nxt.y - nxt.x * point.y
    return area / 2.0


def line_intersection(a1, a2, b1, b2):
    da = a2 - a1
    db = b2 - b1
    denominator = da.x * db.y - da.y * db.x
    if abs(denominator) < 1e-12:
        raise ValueError("parallel offset edges")
    t = ((b1.x - a1.x) * db.y - (b1.y - a1.y) * db.x) / denominator
    return App.Vector(a1.x + da.x * t, a1.y + da.y * t, a1.z)


def offset_convex_polygon(points, distance):
    points = list(points)
    if polygon_area(points) < 0.0:
        points.reverse()
    lines = []
    count = len(points)
    for index in range(count):
        start = points[index]
        end = points[(index + 1) % count]
        edge = end - start
        edge_length = edge.Length
        if edge_length < 1e-12:
            continue
        normal = App.Vector(edge.y / edge_length, -edge.x / edge_length, 0.0)
        lines.append((start + normal * distance, end + normal * distance))
    if len(lines) != count:
        raise ValueError("degenerate polygon edge")
    result = []
    for index in range(count):
        previous = lines[index - 1]
        current = lines[index]
        result.append(
            line_intersection(
                previous[0],
                previous[1],
                current[0],
                current[1],
            )
        )
    return result


def closed_wire(points):
    return Part.makePolygon(list(points) + [points[0]])


def make_prism(points, height):
    face = Part.Face(closed_wire(points))
    return face.extrude(App.Vector(0.0, 0.0, height))


def make_band(inner_points, outer_points, axial_width):
    inner_wire = closed_wire(inner_points)
    outer_wire = closed_wire(outer_points)
    ring_face = None
    try:
        candidate = Part.Face([outer_wire, inner_wire])
        if len(candidate.Wires) == 2 and candidate.isValid():
            ring_face = candidate
    except Exception as exc:
        print("Two-wire face failed:", exc)
    if ring_face is None:
        ring_face = Part.Face(outer_wire).cut(Part.Face(inner_wire))
    solid = ring_face.extrude(App.Vector(0.0, 0.0, axial_width))
    if isinstance(solid, list):
        solid = Part.makeCompound(solid)
    return solid


def make_head(head_inner_x):
    head_y = -head_length / 2.0
    head_z = -head_width / 2.0
    head_box = Part.makeBox(
        head_height,
        head_length,
        head_width,
        App.Vector(head_inner_x, head_y, head_z),
    )
    hole_y = 0.0
    hole_z = -hole_width / 2.0
    hole_box = Part.makeBox(
        head_height + 2.0 * head_clearance,
        hole_length,
        hole_width,
        App.Vector(head_inner_x - head_clearance, hole_y, hole_z),
    )
    return head_box.cut(hole_box)


base_radius = max_bundle_diameter / 2.0
bundle_length = 20.0
base_phase = math.pi / 8.0
base_inner = regular_polygon(8, base_radius, -bundle_length / 2.0, base_phase)
strap_inner = regular_polygon(8, base_radius, -width / 2.0, base_phase)
strap_outer = offset_convex_polygon(strap_inner, thickness)
base_outer = base_radius * math.cos(base_phase)

base_solid = make_prism(base_inner, bundle_length)
head_inner_x = base_outer + thickness
hole_center = App.Vector(
    head_inner_x + head_height / 2.0,
    hole_length / 2.0,
    0.0,
)
head_move = App.Matrix()
head_move.move(-hole_center)
head_solid = make_head(head_inner_x).transformGeometry(head_move)

strap_start = App.Vector(base_outer, head_start_y, 0.0)
strap_end_radius = base_outer + 1.5 * thickness
start_radius = strap_start.Length
projection = (
    strap_end_radius**2 + start_radius**2 - head_length**2
) / (2.0 * start_radius)
height = math.sqrt(max(0.0, strap_end_radius**2 - projection**2))
unit = strap_start / start_radius
strap_end_candidates = []
for sign in (1.0, -1.0):
    strap_end_candidates.append(
        App.Vector(
            projection * unit.x + sign * height * -unit.y,
            projection * unit.y + sign * height * unit.x,
            0.0,
        )
    )
strap_end = max(strap_end_candidates, key=lambda point: point.y)
direction = strap_end - strap_start
rotation_angle = math.atan2(-direction.x, direction.y)
head_rotation = App.Rotation(
    App.Vector(0, 0, 1),
    math.degrees(rotation_angle),
)
local_start = App.Vector(
    -head_height / 2.0,
    -(head_length + hole_length) / 2.0,
    0.0,
)
head_placement = strap_start - head_rotation.multVec(local_start)

center_apothem = base_outer + thickness / 2.0
center_radius = center_apothem / math.cos(base_phase)
half_face = center_apothem * math.tan(base_phase)
wrap_start = App.Vector(center_apothem, strap_start.y, 0.0)
wrap_lower = App.Vector(center_apothem, -half_face, 0.0)
wrap_upper = App.Vector(center_apothem, half_face, 0.0)
wrap_end = App.Vector(center_apothem, strap_end.y, 0.0)
wrap_path = [wrap_start, wrap_lower]
for index in (6, 5, 4, 3, 2, 1):
    angle = base_phase + 2.0 * math.pi * index / 8.0
    wrap_path.append(
        App.Vector(
            center_radius * math.cos(angle),
            center_radius * math.sin(angle),
            0.0,
        )
    )
wrap_path.append(wrap_upper)
wrap_path.append(wrap_end)

radial = head_rotation.multVec(App.Vector(1.0, 0.0, 0.0))
hole_inner = head_placement - radial * (head_height / 2.0)
hole_top = head_placement + radial * (head_height / 2.0)
wrap_path.append(hole_inner)
wrap_path.append(hole_top)

profile = Part.makePolygon(
    [
        wrap_start + App.Vector(-thickness / 2.0, 0.0, -width / 2.0),
        wrap_start + App.Vector(thickness / 2.0, 0.0, -width / 2.0),
        wrap_start + App.Vector(thickness / 2.0, 0.0, width / 2.0),
        wrap_start + App.Vector(-thickness / 2.0, 0.0, width / 2.0),
        wrap_start + App.Vector(-thickness / 2.0, 0.0, -width / 2.0),
    ]
)
wrap_wire = Part.Wire(Part.makePolygon(wrap_path))
strap_solid = wrap_wire.makePipeShell([profile], True, False, 2)
if not strap_solid.isValid() or not strap_solid.Solids:
    strap_solid = wrap_wire.makePipeShell([profile], True, False, 1)

doc = App.getDocument(DOC_NAME)
if doc is None:
    doc = App.newDocument(DOC_NAME)
for object_name in ("OctagonBase", "PlasticStrap", "StrapHead", "StrapWrapTest"):
    existing = doc.getObject(object_name)
    if existing is not None:
        doc.removeObject(object_name)

base = doc.addObject("Part::Feature", "OctagonBase")
base.Label = "Octagon Base Ø%.1f" % max_bundle_diameter
base.Shape = base_solid

strap = doc.addObject("Part::Feature", "PlasticStrap")
strap.Label = "Plastic Strap %.1f x %.1f" % (width, thickness)
strap.Shape = strap_solid
strap.addProperty("App::PropertyLength", "StrapWidth", "Strap", "Axial width")
strap.addProperty("App::PropertyLength", "StrapThickness", "Strap", "Radial thickness")
strap.addProperty("App::PropertyLength", "StrapLength", "Strap", "Nominal strap length")
strap.addProperty(
    "App::PropertyLength",
    "MaxBundleDiameter",
    "Strap",
    "Maximum bundle diameter from the strap table",
)
strap.addProperty("App::PropertyString", "SourceRow", "Strap", "CSV source row")
strap.StrapWidth = width
strap.StrapThickness = thickness
strap.StrapLength = length
strap.MaxBundleDiameter = max_bundle_diameter
strap.SourceRow = "width=%s, length=%s, thickness=%s, max_bundle_diameter=%s" % (
    row["width"],
    row["length"],
    row["thickness"],
    row["Max. bundle diameter [mm]"],
)

head = doc.addObject("Part::Feature", "StrapHead")
head.Label = "Strap Head %.1f x %.1f x %.1f" % (
    head_width,
    head_height,
    head_length,
)
head.Shape = head_solid
head.Placement = App.Placement(head_placement, head_rotation)
head.addProperty("App::PropertyLength", "HeadWidth", "Head", "Axial head width")
head.addProperty("App::PropertyLength", "HeadHeight", "Head", "Radial head height")
head.addProperty("App::PropertyLength", "HeadLength", "Head", "Tangential head length")
head.addProperty("App::PropertyLength", "HoleWidth", "Head", "Axial hole width")
head.addProperty("App::PropertyLength", "HoleLength", "Head", "Radial hole length")
head.addProperty("App::PropertyVector", "StrapStartPoint", "Strap", "Start point for the strap sweep")
head.addProperty("App::PropertyVector", "StrapEndPoint", "Strap", "End point on the head")
head.addProperty("App::PropertyVector", "StrapTerminationPoint", "Strap", "Termination point at the head top")
head.HeadWidth = head_width
head.HeadHeight = head_height
head.HeadLength = head_length
head.HoleWidth = hole_width
head.HoleLength = hole_length
head.StrapStartPoint = strap_start
head.StrapEndPoint = strap_end
head.StrapTerminationPoint = hole_top

if App.GuiUp:
    base.ViewObject.ShapeColor = (0.62, 0.62, 0.66)
    base.ViewObject.LineColor = (0.35, 0.35, 0.40)
    base.ViewObject.Transparency = 65
    strap.ViewObject.ShapeColor = (0.08, 0.28, 0.62)
    strap.ViewObject.LineColor = (0.03, 0.12, 0.35)
    strap.ViewObject.Transparency = 0
    head.ViewObject.ShapeColor = (0.05, 0.20, 0.50)
    head.ViewObject.LineColor = (0.02, 0.08, 0.25)
    head.ViewObject.Transparency = 0

doc.recompute()

if App.GuiUp:
    try:
        App.setActiveDocument(doc.Name)
    except Exception:
        pass
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.SendMsgToActiveView("ViewFit")

for obj in (base, strap, head):
    shape = obj.Shape
    box = shape.BoundBox
    print(
        "%s: valid=%s solids=%d faces=%d volume=%.3f bbox=(%.3f, %.3f, %.3f)-(%.3f, %.3f, %.3f) placement=(%.3f, %.3f, %.3f)"
        % (
            obj.Name,
            shape.isValid(),
            len(shape.Solids),
            len(shape.Faces),
            shape.Volume,
            box.XMin,
            box.YMin,
            box.ZMin,
            box.XMax,
            box.YMax,
            box.ZMax,
            obj.Placement.Base.x,
            obj.Placement.Base.y,
            obj.Placement.Base.z,
        )
    )

inner_perimeter = sum(
    (base_inner[(index + 1) % len(base_inner)] - base_inner[index]).Length
    for index in range(len(base_inner))
)
print("Octagon inner perimeter: %.3f mm (strap length %.3f mm)" % (inner_perimeter, length))
print(
    "Strap start: (%.3f, %.3f, %.3f) radius %.3f"
    % (strap_start.x, strap_start.y, strap_start.z, strap_start.Length)
)
print(
    "Strap end:   (%.3f, %.3f, %.3f) radius %.3f"
    % (strap_end.x, strap_end.y, strap_end.z, strap_end.Length)
)
print(
    "Strap termination: (%.3f, %.3f, %.3f)"
    % (hole_top.x, hole_top.y, hole_top.z)
)
print("Strap path points: %d" % len(wrap_path))
print(
    "Head placement: (%.3f, %.3f, %.3f) rotation %.3f deg"
    % (
        head_placement.x,
        head_placement.y,
        head_placement.z,
        math.degrees(head_rotation.Angle),
    )
)
print("Active document:", doc.Name)

doc.saveAs(DOC_PATH)
print("Saved:", DOC_PATH)
