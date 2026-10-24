"""Test WireCreator with segments from PoC."""

from WireCreator import WireCreator, Segment
import FreeCAD as App
import Part

V = App.Vector

TWO_SEGMENTS_GOOD = [
    Segment(V(0, 0, 0), V(40, 0, 0)),
    Segment(V(55, 15, 5), V(55, 55, 5)),
]

ARC_LENGTH_FAIL = [
    Segment(V(1, 0, 0), V(20, 0, 0)),
    Segment(V(-20, 0, 1), V(-1, 0, 1)),
]

MIN_RADIUS_PARTIAL_FAIL = [
    Segment(V(1, 0, 0), V(50, 0, 0)),
    Segment(V(90, 0, 11), V(40, 0, 10)),
]

if not getattr(App, "GuiUp", False):
    raise SystemExit

doc = App.ActiveDocument
if doc is None:
    doc = App.newDocument("WireCreatorTests")

for obj in list(doc.Objects):
    try:
        if obj.Name.startswith("TestPart_"):
            doc.removeObject(obj.Name)
    except Exception:
        continue

tests = [
    ("TwoSegmentsGood", TWO_SEGMENTS_GOOD),
    ("ArcLengthFail", ARC_LENGTH_FAIL),
    ("MinRadiusPartialFail", MIN_RADIUS_PARTIAL_FAIL),
]

for name, segs in tests:
    wc = WireCreator(min_bend_radius=12.0)
    wire = wc.create_wire(segs)
    results = wc.check_wire()
    print(f"{name} bad arcs:", len(results))
    for r in results:
        print(r["label"], "failed_tests:", r["failed_tests"])

    part = doc.addObject("App::Part", f"TestPart_{name}")
    part.Label = f"TestPart_{name}"

    wire_obj = doc.addObject("Part::Feature", f"Wire_{name}")
    wire_obj.Shape = wire
    part.addObject(wire_obj)

    cable = wc.make_cable(wire=wire, diameter=4.0)
    if cable is not None:
        cable_obj = doc.addObject("Part::Feature", f"Cable_{name}")
        cable_obj.Shape = cable
        try:
            cable_obj.ViewObject.ShapeColor = (0.2, 0.45, 0.8)
            cable_obj.ViewObject.Transparency = 20
        except Exception:
            pass
        part.addObject(cable_obj)

    bad_objs = wc.visualize_bad_arcs(diameter=4.0)
    for bad_obj in bad_objs:
        try:
            part.addObject(bad_obj)
        except Exception:
            pass

doc.recompute()
import FreeCADGui as Gui
Gui.activeDocument().activeView().fitAll()
