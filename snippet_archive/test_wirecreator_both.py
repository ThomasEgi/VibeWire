"""Test WireCreator with both segment sets."""

from WireCreator import WireCreator, Segment
import FreeCAD as App
import Part

V = App.Vector

TWO_SEGMENTS = [
    Segment(V(0, 0, 0), V(40, 0, 0)),
    Segment(V(55, 15, 5), V(55, 55, 5)),
]

COLINEAR_AWAY = [
    Segment(V(1, 0, 0), V(20, 0, 0)),
    Segment(V(-20, 0, 1), V(-1, 0, 1)),
]

if not getattr(App, "GuiUp", False):
    raise SystemExit

doc = App.ActiveDocument
if doc is None:
    doc = App.newDocument("WireCreatorTests")

for obj in list(doc.Objects):
    if obj.Name.startswith("Test_"):
        doc.removeObject(obj.Name)

wc1 = WireCreator(min_bend_radius=12.0)
wire1 = wc1.create_wire(TWO_SEGMENTS)
res1 = wc1.check_wire()
print("TWO_SEGMENTS bad arcs:", len(res1))
for r in res1:
    print(r["label"], r["failed_tests"])
obj1 = doc.addObject("Part::Feature", "Test_TwoSegments")
obj1.Shape = wire1
wc1.visualize_bad_arcs(diameter=4.0)

wc2 = WireCreator(min_bend_radius=12.0)
wire2 = wc2.create_wire(COLINEAR_AWAY)
res2 = wc2.check_wire()
print("COLINEAR_AWAY bad arcs:", len(res2))
for r in res2:
    print(r["label"], r["failed_tests"])
obj2 = doc.addObject("Part::Feature", "Test_ColinearAway")
obj2.Shape = wire2
wc2.visualize_bad_arcs(diameter=4.0)

doc.recompute()
import FreeCADGui as Gui
Gui.activeDocument().activeView().fitAll()
