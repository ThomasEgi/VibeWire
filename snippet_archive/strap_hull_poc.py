import csv
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
from strap_builder import StrapBuilder, StrapSpec

CSV_PATH = os.path.join(SNIPPET_DIR, "strapsizes.csv")
DOC_PATH = os.path.join(os.path.dirname(SNIPPET_DIR), "StrapHullPoC.FCStd")
DOC_NAME = "StrapHullPoC"
SOURCE_DOC = "BranchingMergePoC_packedbundles"
SOURCE_SEGMENT = "SegmentC_1_1"

with open(CSV_PATH, encoding="utf-8-sig", newline="") as handle:
    row = next(csv.DictReader(handle))

spec = StrapSpec(
    width=float(row["width"]),
    length=float(row["length"]),
    thickness=float(row["thickness"]),
    max_bundle_diameter=float(row["Max. bundle diameter [mm]"]),
)

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

builder = StrapBuilder(hull, spec)
strap_shape = builder.strap_shape
head_shape = builder.head_shape

base_face = Part.Face(Part.makePolygon(list(hull) + [hull[0]]))
base_shape = base_face.extrude(App.Vector(0.0, 0.0, 20.0))
base_shape.translate(App.Vector(0.0, 0.0, -10.0))

doc = App.listDocuments().get(DOC_NAME)
if doc is None:
    doc = App.newDocument(DOC_NAME)
for object_name in ("HullBase", "WrapHull", "HullStrap", "HullHead"):
    existing = doc.getObject(object_name)
    if existing is not None:
        doc.removeObject(object_name)

base = doc.addObject("Part::Feature", "HullBase")
base.Label = "Hull Base %s" % SOURCE_SEGMENT
base.Shape = base_shape

wrap_hull = doc.addObject("Part::Feature", "WrapHull")
wrap_hull.Label = "Strap Hull"
wrap_hull.Shape = Part.makePolygon(
    list(builder.strap_hull) + [builder.strap_hull[0]]
)

strap = doc.addObject("Part::Feature", "HullStrap")
strap.Label = "Hull Strap %s" % SOURCE_SEGMENT
strap.Shape = strap_shape

head = doc.addObject("Part::Feature", "HullHead")
head.Label = "Hull Strap Head"
head.Shape = head_shape
head.Placement = App.Placement(builder.head_placement, builder.head_rotation)
head.addProperty("App::PropertyVector", "StrapStartPoint", "Strap", "Strap start on the hull")
head.addProperty("App::PropertyVector", "StrapStartCenter", "Strap", "First sweep center point at the head")
head.addProperty("App::PropertyVector", "StrapEdge4Point", "Strap", "Raised head edge point")
head.addProperty("App::PropertyVector", "StrapBendPoint", "Strap", "Bend point added below the head")
head.addProperty("App::PropertyVector", "StrapTerminationPoint", "Strap", "Termination point at the head top")
head.StrapStartPoint = builder.head_start
head.StrapStartCenter = builder.strap_start_center
head.StrapEdge4Point = builder.edge4
head.StrapBendPoint = builder.bend_point
head.StrapTerminationPoint = builder.hole_top

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
    wrap_hull.ViewObject.LineColor = (0.9, 0.55, 0.05)
    wrap_hull.ViewObject.LineWidth = 2
    wrap_hull.ViewObject.Visibility = False

doc.recompute()
if App.GuiUp:
    try:
        App.setActiveDocument(doc.Name)
    except Exception:
        pass
    Gui.activeDocument().activeView().viewAxonometric()
    Gui.SendMsgToActiveView("ViewFit")

print("source", SOURCE_SEGMENT, "hull vertices", len(hull))
print("head index", builder.head_index, "edge4 index", builder.end_index)
print("strap hull vertices", len(builder.strap_hull), "bend index", builder.bend_index)
print("head start", builder.head_start)
print("strap start center", builder.strap_start_center)
print("edge4", builder.edge4)
print("bend point", builder.bend_point)
print("termination", builder.hole_top)
print("wrap path points", len(builder.wrap_path))
for obj in (base, wrap_hull, strap, head):
    shape = obj.Shape
    box = shape.BoundBox
    print(
        "%s: valid=%s solids=%d faces=%d volume=%.3f bbox=(%.3f, %.3f, %.3f)-(%.3f, %.3f, %.3f)"
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
        )
    )

doc.saveAs(DOC_PATH)
print("Saved:", DOC_PATH)
