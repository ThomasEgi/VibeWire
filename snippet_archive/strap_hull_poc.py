import importlib
import math
import os
import sys

import FreeCAD as App
import Part

SNIPPET_DIR = (
    os.path.dirname(os.path.abspath(__file__))
    if "__file__" in globals()
    else "/home/mx/opencaudetest/WirePlugin-main/snippet_archive"
)
if SNIPPET_DIR not in sys.path:
    sys.path.insert(0, SNIPPET_DIR)

import strap_builder
importlib.reload(strap_builder)
from strap_builder import StrapBuilder, polygon_perimeter, select_strap_spec

DOC_PATH = os.path.join(os.path.dirname(SNIPPET_DIR), "StrapHullPoC.FCStd")
DOC_NAME = "StrapHullPoC"
SOURCE_DOC = "BranchingMergePoC_packedbundles"
SOURCE_SEGMENT = "SegmentC_1_1"
BUNDLE_LENGTH = 25.0
SCALE_STEP = 1.2
GRID_COLUMNS = 5

source = App.getDocument(SOURCE_DOC)
segment = next(
    item
    for item in source.Objects
    if getattr(item, "Label", "") == SOURCE_SEGMENT
)
hull_shape = segment.HullCurve
if hull_shape is None or hull_shape.isNull():
    raise RuntimeError("source hull is empty")

start = segment.Start.getGlobalPlacement().Base
end = segment.End.getGlobalPlacement().Base
normal = end - start
normal.normalize()
x_axis = App.Vector(1.0, 0.0, 0.0)
x_axis = x_axis - normal * x_axis.dot(normal)
if x_axis.Length < 1e-9:
    x_axis = App.Vector(0.0, 1.0, 0.0)
    x_axis = x_axis - normal * x_axis.dot(normal)
x_axis.normalize()
y_axis = normal.cross(x_axis)
y_axis.normalize()

source_points = [vertex.Point for vertex in hull_shape.Vertexes]
centroid = App.Vector()
for point in source_points:
    centroid += point
centroid = centroid / len(source_points)
hull = [
    App.Vector(
        (point - centroid).dot(x_axis),
        (point - centroid).dot(y_axis),
        0.0,
    )
    for point in source_points
]

results = []
scale = 1.0
while True:
    scaled_hull = [point * scale for point in hull]
    circumference = polygon_perimeter(scaled_hull)
    try:
        spec, row, equivalent_diameter = select_strap_spec(circumference)
    except ValueError as exc:
        print("Stopped at scale %.6f: %s" % (scale, exc))
        break
    builder = StrapBuilder(scaled_hull, spec)
    results.append(
        (
            scale,
            scaled_hull,
            circumference,
            equivalent_diameter,
            spec,
            row,
            builder,
        )
    )
    scale *= SCALE_STEP

if not results:
    raise RuntimeError("no strap fits the original hull")

widths = [
    max(point.x for point in item[1]) - min(point.x for point in item[1])
    for item in results
]
heights = [
    max(point.y for point in item[1]) - min(point.y for point in item[1])
    for item in results
]
row_groups = [
    results[index : index + GRID_COLUMNS]
    for index in range(0, len(results), GRID_COLUMNS)
]
row_sizes = []
for row_group in row_groups:
    row_widths = [
        max(point.x for point in item[1]) - min(point.x for point in item[1])
        for item in row_group
    ]
    row_heights = [
        max(point.y for point in item[1]) - min(point.y for point in item[1])
        for item in row_group
    ]
    row_sizes.append(max(max(row_widths), max(row_heights)) * 1.5)
offsets = []
y_position = sum(row_sizes) / 2.0
for row_group, row_size in zip(row_groups, row_sizes):
    y_position -= row_size / 2.0
    for column in range(len(row_group)):
        offsets.append(
            App.Vector(
                (column - (len(row_group) - 1) / 2.0) * row_size,
                y_position,
                0.0,
            )
        )
    y_position -= row_size / 2.0

stop_scale = scale
stop_diameter = (
    polygon_perimeter([point * stop_scale for point in hull]) / math.pi
)

doc = App.listDocuments().get(DOC_NAME)
if doc is None:
    doc = App.newDocument(DOC_NAME)
for obj in list(doc.Objects):
    if obj.Name.startswith(("HullBase", "HullStrap", "HullHead", "WrapHull")):
        doc.removeObject(obj.Name)

for index, item in enumerate(results):
    (
        scale,
        scaled_hull,
        circumference,
        equivalent_diameter,
        spec,
        row,
        builder,
    ) = item
    offset = offsets[index]
    suffix = ("%.3f" % scale).replace(".", "p")

    base_face = Part.Face(Part.makePolygon(list(scaled_hull) + [scaled_hull[0]]))
    base_shape = base_face.extrude(App.Vector(0.0, 0.0, BUNDLE_LENGTH))
    base = doc.addObject("Part::Feature", "HullBase_%s" % suffix)
    base.Label = "%.3fx Base" % scale
    base.Shape = base_shape
    base.Placement.Base = offset + App.Vector(0.0, 0.0, -BUNDLE_LENGTH / 2.0)
    base.addProperty(
        "App::PropertyFloat",
        "HullScale",
        "Hull",
        "Scale relative to the source hull",
    )
    base.addProperty(
        "App::PropertyLength",
        "HullCircumference",
        "Hull",
        "Circumference of the scaled hull",
    )
    base.addProperty(
        "App::PropertyLength",
        "EquivalentBundleDiameter",
        "Hull",
        "Equivalent diameter from the circumference",
    )
    base.addProperty(
        "App::PropertyString",
        "StrapSelection",
        "Hull",
        "Selected CSV strap row",
    )
    base.HullScale = scale
    base.HullCircumference = circumference
    base.EquivalentBundleDiameter = equivalent_diameter
    base.StrapSelection = (
        "width=%s, length=%s, thickness=%s, max_bundle_diameter=%s" % row
    )

    head_local = builder.head_shape.transformGeometry(
        App.Placement(
            builder.head_placement,
            builder.head_rotation,
        ).toMatrix()
    )
    combined = builder.strap_shape.fuse(head_local)
    if not combined.isValid() or not combined.Solids:
        combined = Part.makeCompound([builder.strap_shape, head_local])
    utilized_length = builder.strap_path_length + spec.head_length

    strap = doc.addObject("Part::Feature", "HullStrap_%s" % suffix)
    strap.Label = "%.3fx Strap %.1f x %.1f" % (
        scale,
        spec.width,
        spec.thickness,
    )
    strap.Shape = combined
    strap.Placement.Base = offset
    strap.addProperty("App::PropertyFloat", "HullScale", "Strap", "Hull scale")
    strap.addProperty("App::PropertyLength", "StrapWidth", "Strap", "Axial width")
    strap.addProperty(
        "App::PropertyLength", "StrapThickness", "Strap", "Radial thickness"
    )
    strap.addProperty(
        "App::PropertyLength",
        "StrapLength",
        "Strap",
        "Uncut strap length from the table",
    )
    strap.addProperty(
        "App::PropertyLength",
        "MaxStrapDiameter",
        "Strap",
        "Maximum strap diameter",
    )
    strap.addProperty(
        "App::PropertyLength",
        "StrapPathLength",
        "Strap",
        "Centerline length of the generated strap path",
    )
    strap.addProperty(
        "App::PropertyLength",
        "UtilizedStrapLength",
        "Strap",
        "Strap path length plus head length",
    )
    strap.addProperty("App::PropertyAngle", "HeadDraftAngle", "Head", "Draft angle")
    strap.addProperty(
        "App::PropertyVector", "StrapStartPoint", "Strap", "Strap start on the hull"
    )
    strap.addProperty(
        "App::PropertyVector",
        "StrapStartCenter",
        "Strap",
        "First sweep center point at the head",
    )
    strap.addProperty(
        "App::PropertyVector", "StrapEdge4Point", "Strap", "Raised head edge point"
    )
    strap.addProperty(
        "App::PropertyVector",
        "StrapBendPoint",
        "Strap",
        "Bend point added below the head",
    )
    strap.addProperty(
        "App::PropertyVector",
        "StrapTerminationPoint",
        "Strap",
        "Termination point at the head top",
    )
    strap.HullScale = scale
    strap.StrapWidth = spec.width
    strap.StrapThickness = spec.thickness
    strap.StrapLength = spec.length
    strap.MaxStrapDiameter = spec.max_bundle_diameter
    strap.StrapPathLength = builder.strap_path_length
    strap.UtilizedStrapLength = utilized_length
    strap.HeadDraftAngle = spec.draft_angle
    strap.StrapStartPoint = builder.head_start + offset
    strap.StrapStartCenter = builder.strap_start_center + offset
    strap.StrapEdge4Point = builder.edge4 + offset
    strap.StrapBendPoint = builder.bend_point + offset
    strap.StrapTerminationPoint = builder.hole_top + offset

    if App.GuiUp:
        base.ViewObject.ShapeColor = (0.62, 0.62, 0.66)
        base.ViewObject.LineColor = (0.35, 0.35, 0.40)
        base.ViewObject.Transparency = 65
        strap.ViewObject.ShapeColor = (0.08, 0.28, 0.62)
        strap.ViewObject.LineColor = (0.03, 0.12, 0.35)
        strap.ViewObject.Transparency = 0

    print(
        "scale %.6f circumference %.3f D %.3f -> width %.1f x %.1f, faces %d, used %.1f/%.1f mm"
        % (
            scale,
            circumference,
            equivalent_diameter,
            spec.width,
            spec.thickness,
            len(builder.strap_shape.Faces),
            utilized_length,
            spec.length,
        )
    )

doc.recompute()
if App.GuiUp:
    try:
        App.setActiveDocument(doc.Name)
    except Exception:
        pass
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.SendMsgToActiveView("ViewFit")

print(
    "Next scale %.6f would need D %.3f (> widest strap maximum)"
    % (stop_scale, stop_diameter)
)
print("Assemblies:", len(results), "Active document:", doc.Name)
doc.saveAs(DOC_PATH)
print("Saved:", DOC_PATH)
