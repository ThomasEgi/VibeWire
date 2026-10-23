"""Test WireCreator with segments from PoC."""

from WireCreator import WireCreator, Segment
import FreeCAD as App
import Part

V = App.Vector

# Segments from PoC
TWO_SEGMENTS = [
    Segment(V(0, 0, 0), V(40, 0, 0)),
    Segment(V(55, 15, 5), V(55, 55, 5)),
]

COLINEAR_AWAY = [
    Segment(V(1, 0, 0), V(20, 0, 0)),
    Segment(V(-20, 0, 1), V(-1, 0, 1)),
]

if __name__ == "__main__":
    wc = WireCreator(min_bend_radius=12.0)
    wire = wc.create_wire(COLINEAR_AWAY)
    results = wc.check_wire()
    print("Bad arcs:", len(results))
    for r in results:
        print(r["label"], "failed_tests:", r["failed_tests"], "radius:", r["radius"])
    wc.visualize_bad_arcs(diameter=4.0)
