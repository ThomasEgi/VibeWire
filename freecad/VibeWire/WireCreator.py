"""WireCreator for bi-arc cable routing."""

import math
from collections import namedtuple

import FreeCAD as App
import Part

V = App.Vector

Segment = namedtuple("Segment", ["start", "end"])


class WireCreator:
    def __init__(self, min_bend_radius=12.0):
        self.min_bend_radius = min_bend_radius
        self.segments = []
        self.arcs = []
        self.wire = None
        self.pieces = []
        self.joints = []
        self.test_results = []
        self.tests = [
            {"index": 1, "name": "min_bend_radius", "color": (1.0, 0.0, 0.0)},
            {"index": 2, "name": "length_vs_2pi_chord", "color": (1.0, 0.55, 0.0)},
        ]

    @staticmethod
    def _unit(vector):
        if vector.Length < 1e-12:
            raise ValueError("Cannot normalize a zero vector")
        return V(vector).normalize()

    @staticmethod
    def _bend_radius(edge):
        curve = edge.Curve
        if isinstance(curve, Part.Circle):
            return curve.Radius

        first = edge.FirstParameter
        last = edge.LastParameter
        max_curvature = 0.0
        for step in range(1, 9):
            parameter = first + (last - first) * step / 9.0
            try:
                max_curvature = max(max_curvature, abs(edge.curvatureAt(parameter)))
            except Exception:
                pass

        if max_curvature < 1e-12:
            return None
        return 1.0 / max_curvature

    def _arc_edge(self, start, end, start_tangent):
        chord = end - start
        chord_length = chord.Length
        if chord_length < 1e-9:
            return None

        cross = chord.cross(start_tangent)
        offset = cross.Length
        if offset < 1e-9 * max(1.0, chord_length):
            return Part.makeLine(start, end)

        normal = self._unit(start_tangent.cross(cross))
        radius = chord_length * chord_length / (2.0 * offset)
        center = start + normal * radius

        radial_start = start - center
        radial_end = end - center
        axis = self._unit(radial_start.cross(start_tangent))

        angle = radial_start.getAngle(radial_end)
        if radial_start.cross(radial_end).dot(axis) < 0.0:
            angle = 2.0 * math.pi - angle

        circle = Part.Circle(center, axis, radius)
        circle.XAxis = self._unit(radial_start)
        return Part.ArcOfCircle(circle, 0.0, angle).toShape()

    def _biarc(self, start, start_tangent, end, end_tangent):
        tangent_start = self._unit(start_tangent)
        tangent_end = self._unit(end_tangent)

        chord = end - start
        tangent_sum = tangent_start + tangent_end

        chord_length_sq = chord.dot(chord)
        if chord_length_sq < 1e-18:
            return [], start, tangent_start

        dot_product = chord.dot(tangent_sum)
        constant = tangent_sum.dot(tangent_sum) - 4.0
        discriminant = max(
            0.0,
            4.0 * (dot_product * dot_product - chord_length_sq * constant),
        )

        inverse_joint_scale = (
            2.0 * dot_product + math.sqrt(discriminant)
        ) / (2.0 * chord_length_sq)
        if abs(inverse_joint_scale) < 1e-18:
            chord_len = math.sqrt(chord_length_sq)
            arcs = [self._arc_edge(start, end, tangent_start)]
            if arcs[0] is None:
                arcs = [Part.makeLine(start, end)]
            return [a for a in arcs if a is not None], start + tangent_start * chord_len * 0.5, tangent_start

        try:
            joint_tangent = self._unit(chord * inverse_joint_scale - tangent_sum)
        except Exception:
            chord_len = math.sqrt(chord_length_sq)
            arcs = [self._arc_edge(start, end, tangent_start)]
            if arcs[0] is None:
                arcs = [Part.makeLine(start, end)]
            return [a for a in arcs if a is not None], start + tangent_start * chord_len * 0.5, tangent_start

        joint_scale = 1.0 / inverse_joint_scale
        joint = start + (tangent_start + joint_tangent) * joint_scale

        arcs = [
            self._arc_edge(start, joint, tangent_start),
            self._arc_edge(joint, end, joint_tangent),
        ]
        return [arc for arc in arcs if arc is not None], joint, joint_tangent

    def create_wire(self, segments):
        self.segments = segments
        self.pieces = []
        self.joints = []
        self.arcs = []

        for index, segment in enumerate(segments):
            direction = self._unit(segment.end - segment.start)

            if index:
                previous = segments[index - 1]
                gap = (segment.start - previous.end).Length
                if gap > 1e-9:
                    previous_direction = self._unit(previous.end - previous.start)
                    chord_start = previous.end
                    chord_end = segment.start
                    chord_len = (chord_end - chord_start).Length
                    arcs, joint, _ = self._biarc(
                        chord_start,
                        previous_direction,
                        chord_end,
                        direction,
                    )
                    joints = self.joints
                    joints.append(joint)
                    self.joints = joints
                    biarc_total_len = sum(arc.Length for arc in arcs)
                    for arc_index, arc in enumerate(arcs, start=1):
                        self.arcs.append(arc)
                        self.pieces.append(
                            {
                                "label": f"Bi-arc {index}.{arc_index}",
                                "edge": arc,
                                "type": "biarc",
                                "biarc_total_len": biarc_total_len,
                                "chord_len": chord_len,
                                "arc_index": arc_index,
                                "biarc_index": index,
                            }
                        )

            line = Part.makeLine(segment.start, segment.end)
            self.pieces.append(
                {
                    "label": f"Segment {index + 1}",
                    "edge": line,
                    "type": "segment",
                }
            )

        self.wire = Part.Wire([item["edge"] for item in self.pieces])
        return self.wire

    def check_wire(self):
        self.test_results = []
        for piece in self.pieces:
            if piece.get("type") != "biarc":
                continue

            edge = piece["edge"]
            label = piece["label"]
            biarc_total_len = piece.get("biarc_total_len")
            chord_len = piece.get("chord_len")

            failed_tests = []

            radius = self._bend_radius(edge)
            if radius is not None and self.min_bend_radius is not None:
                if radius < self.min_bend_radius - 1e-9:
                    failed_tests.append(1)

            if biarc_total_len is not None and chord_len is not None and chord_len > 1e-12:
                if biarc_total_len > 2.0 * math.pi * chord_len + 1e-9:
                    if 2 not in failed_tests:
                        failed_tests.append(2)

            if failed_tests:
                self.test_results.append(
                    {
                        "label": label,
                        "edge": edge,
                        "failed_tests": failed_tests,
                        "biarc_total_len": biarc_total_len,
                        "chord_len": chord_len,
                        "radius": radius,
                    }
                )

        return self.test_results

    def measure(self):
        """Return total path length and the smallest bend radius."""
        total_length = 0.0
        minimum_radius = None
        for piece in self.pieces:
            edge = piece["edge"]
            total_length += edge.Length
            radius = self._bend_radius(edge)
            if radius is None:
                continue
            if minimum_radius is None or radius < minimum_radius:
                minimum_radius = radius
        return total_length, minimum_radius

    def get_test_color(self, test_index):
        for test in self.tests:
            if test["index"] == test_index:
                return test["color"]
        return (1.0, 0.0, 0.0)

    def make_bad_arc_shape(self, result, diameter=4.0, use_frenet=True):
        """Build a slightly oversized tube around a failed bi-arc edge."""
        try:
            edge = result["edge"]
            if hasattr(edge, "Edges") and edge.Edges:
                edge = edge.Edges[0]
            elif hasattr(edge, "Wires") and edge.Wires and edge.Wires[0].Edges:
                edge = edge.Wires[0].Edges[0]

            start = edge.valueAt(edge.FirstParameter)
            tangent = edge.tangentAt(edge.FirstParameter)
            failed_diameter = diameter * 1.05
            profile = Part.Wire(
                [Part.Circle(start, tangent, failed_diameter / 2.0).toShape()]
            )
            return Part.Wire([edge]).makePipeShell([profile], True, use_frenet, 0)
        except Exception:
            try:
                return result["edge"]
            except Exception:
                return None

    def visualize_bad_arcs(self, diameter=4.0, use_frenet=True):
        if not getattr(App, "GuiUp", False):
            return []

        document = App.ActiveDocument
        if document is None:
            document = App.newDocument("WireCreator")

        results = self.check_wire()
        created = []

        for result in results:
            failed_tests = result["failed_tests"]
            if not failed_tests:
                continue

            # Red takes priority (test 1)
            if 1 in failed_tests:
                color = self.get_test_color(1)
            elif 2 in failed_tests:
                color = self.get_test_color(2)
            else:
                color = self.get_test_color(failed_tests[0])

            edge = result["edge"]
            label = result["label"]

            try:
                failed_edge = edge
                if hasattr(failed_edge, "Edges") and len(failed_edge.Edges) > 0:
                    failed_edge = failed_edge.Edges[0]
                elif hasattr(failed_edge, "Wires") and len(failed_edge.Wires) > 0 and failed_edge.Wires[0].Edges:
                    failed_edge = failed_edge.Wires[0].Edges[0]

                start = failed_edge.valueAt(failed_edge.FirstParameter)
                tangent = failed_edge.tangentAt(failed_edge.FirstParameter)
                failed_diameter = diameter * 1.05
                profile = Part.Wire([Part.Circle(start, tangent, failed_diameter / 2.0).toShape()])
                edge_wire = Part.Wire([failed_edge])
                failed_cable = edge_wire.makePipeShell([profile], True, use_frenet, 0)
                obj = document.addObject("Part::Feature", "Bad_" + label.replace(" ", "_").replace(".", "_"))
                obj.Shape = failed_cable
                obj.ViewObject.ShapeColor = color
                obj.ViewObject.Transparency = 0
                created.append(obj)
            except Exception:
                try:
                    obj = document.addObject("Part::Feature", "Bad_" + label.replace(" ", "_").replace(".", "_"))
                    obj.Shape = edge
                    obj.ViewObject.LineColor = color
                    obj.ViewObject.LineWidth = 6
                    created.append(obj)
                except Exception:
                    pass

        document.recompute()
        return created


    def make_cable(self, wire=None, diameter=4.0, use_frenet=True):
        if wire is None:
            wire = self.wire
        if wire is None:
            return None
        try:
            first_edge = wire.Edges[0]
            start = first_edge.valueAt(first_edge.FirstParameter)
            tangent = first_edge.tangentAt(first_edge.FirstParameter)
            profile = Part.Wire([Part.Circle(start, tangent, diameter / 2.0).toShape()])
            return wire.makePipeShell([profile], True, use_frenet, 0)
        except Exception:
            return None

    def make_cable_sectors(self, wire=None, diameter=4.0, use_frenet=True):
        """Build four longitudinal quadrant solids for multi-color cables."""
        if wire is None:
            wire = self.wire
        if wire is None:
            return None
        try:
            first_edge = wire.Edges[0]
            start = first_edge.valueAt(first_edge.FirstParameter)
            tangent = first_edge.tangentAt(first_edge.FirstParameter)
            circle = Part.Circle(start, tangent, diameter / 2.0)
            shapes = []
            for index in range(4):
                first = math.pi * index / 2.0
                last = math.pi * (index + 1) / 2.0
                arc = Part.Arc(circle, first, last).toShape()
                arc_start = arc.valueAt(arc.FirstParameter)
                arc_end = arc.valueAt(arc.LastParameter)
                profile = Part.Wire(
                    [
                        Part.makeLine(start, arc_start),
                        arc,
                        Part.makeLine(arc_end, start),
                    ]
                )
                shape = wire.makePipeShell([profile], True, use_frenet, 0)
                if not shape.Solids:
                    return None
                shapes.append(shape)
            return Part.makeCompound(shapes)
        except Exception:
            return None
