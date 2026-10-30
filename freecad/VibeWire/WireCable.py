"""Persistent wire cable document object and view provider."""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from . import FerruleData
from .WireColors import (
    TRACER_NONE,
    color_rgb,
    is_multicolor,
    names as cable_color_names,
    parse_legacy,
    quadrants as cable_color_quadrants,
)
from .WireBundle import ancestor_groups
from .WireFrames import segment_basis
from .WireTypes import (
    is_bundle_segment,
    is_harness,
    is_lace_helper,
    segment_is_open,
)
from . import WireTransitions
from .WireCreator import Segment, WireCreator
from .WirePathMath import biarc_edges
from .WireRoute import decode_offset, layout_key
from .WireTip import TIP_OFFSET_MARGIN, create_wire_tip

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")

SUPPORT_OBJECT_PROPERTIES = (
    "PathObject",
    "BadRadiusObject",
    "BadLengthObject",
    "StartCoreObject",
    "EndCoreObject",
    "StartFerruleMetal",
    "EndFerruleMetal",
    "StartFerruleSleeve",
    "EndFerruleSleeve",
)


class WireCableProxy:
    """Document object that rebuilds path and cable geometry from bundle segments."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "WireCable"
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        properties = obj.PropertiesList

        _ensure_global_link_list(
            obj,
            "Points",
            "Wire",
            "Ordered bundle segments defining the cable route",
        )
        if "SegmentDirections" not in properties:
            obj.addProperty(
                "App::PropertyIntegerList",
                "SegmentDirections",
                "Wire",
                "Per-segment route direction (0 normal, 1 reversed)",
            )
        if "SegmentEntryParams" not in properties:
            obj.addProperty(
                "App::PropertyFloatList",
                "SegmentEntryParams",
                "Wire",
                "Per-segment entry parameter (0..1 along the oriented segment)",
            )
        if "SegmentExitParams" not in properties:
            obj.addProperty(
                "App::PropertyFloatList",
                "SegmentExitParams",
                "Wire",
                "Per-segment exit parameter (0..1 along the oriented segment)",
            )
        if "Harness" not in properties:
            obj.addProperty(
                "App::PropertyLinkGlobal",
                "Harness",
                "Wire",
                "Harness providing the cable lane layout",
            )
        if "Diameter" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "Diameter",
                "Wire",
                "Cable diameter",
            )
            obj.Diameter = 4.0
        if "CoreSizeMode" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "CoreSizeMode",
                "Wire",
                "Conductor core size input mode",
            )
            obj.CoreSizeMode = ["Diameter", "Area"]
            obj.CoreSizeMode = "Area"
        if "CoreArea" not in properties:
            obj.addProperty(
                "App::PropertyFloat",
                "CoreArea",
                "Wire",
                "Conductor core cross-section in square millimetres",
            )
            obj.CoreArea = 1.0
        if "CoreDiameter" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "CoreDiameter",
                "Wire",
                "Conductor core diameter",
            )
            area = max(0.0, getattr(obj, "CoreArea", 1.0))
            obj.CoreDiameter = 2.0 * math.sqrt(area / math.pi)
        if "WireSizeMM2" not in properties:
            obj.addProperty(
                "App::PropertyFloat",
                "WireSizeMM2",
                "Wire",
                "Selected standard wire size in square millimetres (0 = custom)",
            )
            obj.WireSizeMM2 = 0.0
        if "MinBendRadius" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "MinBendRadius",
                "Wire",
                "Minimum allowed bending radius",
            )
            obj.MinBendRadius = 12.0
        color_names = cable_color_names()
        if "CableColor" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "CableColor",
                "Wire",
                "Primary wire insulation color",
            )
            obj.CableColor = list(color_names)
            obj.CableColor = "Blue"
        if "CableColorTracer" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "CableColorTracer",
                "Wire",
                "Tracer wire insulation color (None for solid)",
            )
            obj.CableColorTracer = [TRACER_NONE] + list(color_names)
            obj.CableColorTracer = TRACER_NONE
        current = getattr(obj, "CableColor", "Blue")
        tracer = getattr(obj, "CableColorTracer", TRACER_NONE)
        if current not in color_names:
            current, legacy_tracer = parse_legacy(current)
            if tracer in (TRACER_NONE, None) and legacy_tracer != TRACER_NONE:
                tracer = legacy_tracer
        if current not in color_names:
            current = "Blue"
        if tracer not in (TRACER_NONE,) + color_names:
            tracer = TRACER_NONE
        try:
            obj.CableColor = list(color_names)
            obj.CableColor = current
        except Exception:
            pass
        try:
            obj.CableColorTracer = [TRACER_NONE] + list(color_names)
            obj.CableColorTracer = tracer
        except Exception:
            pass
        if "BuildCable" not in properties:
            obj.addProperty(
                "App::PropertyBool",
                "BuildCable",
                "Wire",
                "Create the swept cable solid (otherwise only the path is built)",
            )
            obj.BuildCable = True
        if "Preview" not in properties:
            obj.addProperty(
                "App::PropertyBool",
                "Preview",
                "Wire",
                "Preview mode: build the path but no cable/core/ferrule geometry",
            )
            obj.Preview = False
        for name, description in (
            ("StartTip", "Settings object for the cable start end"),
            ("EndTip", "Settings object for the cable end"),
        ):
            if name not in properties:
                obj.addProperty("App::PropertyLinkGlobal", name, "Tips", description)
        if "Length" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "Length",
                "Wire",
                "Computed total path length",
            )
        if "CableOnlyLength" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "CableOnlyLength",
                "Wire",
                "Computed cable length excluding connector length offsets",
            )
        for name, description in (
            ("StartTipLength", "Length of the first route piece available for the start tip"),
            ("EndTipLength", "Length of the last route piece available for the end tip"),
        ):
            if name not in properties:
                obj.addProperty("App::PropertyLength", name, "Tips", description)
                try:
                    obj.setEditorMode(name, 2)
                except Exception:
                    pass
        if "MinimumRadius" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "MinimumRadius",
                "Wire",
                "Computed minimum bend radius (0 if no curved edges)",
            )
        if "Status" not in properties:
            obj.addProperty(
                "App::PropertyString",
                "Status",
                "Wire",
                "Computed validation status",
            )
        if "Dependencies" not in properties:
            obj.addProperty(
                "App::PropertyLinkListGlobal",
                "Dependencies",
                "Wire",
                "Ancestor groups that affect the referenced placements",
            )
            try:
                obj.setEditorMode("Dependencies", 2)
            except Exception:
                pass
        for name, description in (
            ("PathObject", "Object displaying the path"),
            ("BadRadiusObject", "Object displaying bends below the minimum radius"),
            ("BadLengthObject", "Object displaying bi-arcs over the length limit"),
            ("StartCoreObject", "Object displaying the stripped core at the start"),
            ("EndCoreObject", "Object displaying the stripped core at the end"),
            ("StartFerruleMetal", "Metal tip at the start ferrule"),
            ("EndFerruleMetal", "Metal tip at the end ferrule"),
            ("StartFerruleSleeve", "Colored sleeve/cone at the start ferrule"),
            ("EndFerruleSleeve", "Colored sleeve/cone at the end ferrule"),
        ):
            if name not in properties:
                obj.addProperty("App::PropertyLink", name, "Wire", description)

    def _build_open_route(self, obj, route, directions):
        lines = []
        open_flags = []
        entry_params = list(getattr(obj, "SegmentEntryParams", []) or [])
        exit_params = list(getattr(obj, "SegmentExitParams", []) or [])
        entry_params = (entry_params + [0.0] * len(route))[: len(route)]
        exit_params = (exit_params + [1.0] * len(route))[: len(route)]

        for index, segment_obj in enumerate(route):
            if not is_bundle_segment(segment_obj):
                raise ValueError(
                    "Route item {} is not a bundle segment.".format(index + 1)
                )
            start, end = self._bundle_points(obj, segment_obj)
            if int(directions[index]) % 2:
                start, end = end, start
            is_tip = index == 0 or index == len(route) - 1
            is_open = segment_is_open(segment_obj) and not is_tip
            lines.append((start, end))
            open_flags.append(is_open)
            if not is_open and not is_tip:
                if (
                    abs(float(entry_params[index])) > 1e-9
                    or abs(float(exit_params[index]) - 1.0) > 1e-9
                ):
                    raise ValueError(
                        "Closed bundle segment '{}' only allows an end-to-end "
                        "connection. Set its type to Open or use the endpoints.".format(
                            segment_obj.Label
                        )
                    )

        if not any(open_flags):
            return None

        radius = max(4.0 * obj.Diameter.Value, obj.MinBendRadius.Value)
        if radius <= 0.0:
            raise ValueError(
                "Cable diameter or minimum bend radius must be positive for open routing."
            )

        entry_points = [line[0] for line in lines]
        exit_points = [line[1] for line in lines]
        transitions = [None] * (len(route) - 1)
        creator = WireCreator(min_bend_radius=obj.MinBendRadius.Value)

        for index in range(len(route) - 1):
            prev_start, prev_end = lines[index]
            next_start, next_end = lines[index + 1]
            prev_direction = WireTransitions.unit_vector(prev_end - prev_start)
            next_direction = WireTransitions.unit_vector(next_end - next_start)
            prev_open = open_flags[index]
            next_open = open_flags[index + 1]
            try:
                if prev_open and next_open:
                    result = WireTransitions.solve_segment_to_segment(
                        prev_start,
                        prev_end,
                        next_start,
                        next_end,
                        radius,
                    )
                    exit_points[index] = result["source_exit"]
                    entry_points[index + 1] = result["target_entry"]
                    transitions[index] = result["pieces"]
                elif not prev_open and next_open:
                    result = WireTransitions.solve_s5_point_to_segment(
                        prev_end,
                        prev_direction,
                        next_start,
                        next_end,
                        radius,
                    )
                    exit_points[index] = prev_end
                    entry_points[index + 1] = result["q"]
                    transitions[index] = result["pieces"]
                elif prev_open and not next_open:
                    result = WireTransitions.solve_s5_segment_to_point(
                        prev_start,
                        prev_end,
                        next_start,
                        next_direction,
                        radius,
                    )
                    exit_points[index] = result["source_departure"]
                    entry_points[index + 1] = next_start
                    transitions[index] = result["pieces"]
                else:
                    if (next_start - prev_end).Length > 1e-9:
                        arcs, _, _ = biarc_edges(
                            prev_end,
                            prev_direction,
                            next_start,
                            next_direction,
                        )
                        transition_pieces = []
                        for arc_index, arc in enumerate(arcs, start=1):
                            transition_pieces.append(
                                {
                                    "kind": "arc",
                                    "name": "Bi-arc {}.{}".format(
                                        index + 1, arc_index
                                    ),
                                    "edge": arc,
                                    "length": arc.Length,
                                    "start": arc.valueAt(arc.FirstParameter),
                                    "end": arc.valueAt(arc.LastParameter),
                                }
                            )
                        transitions[index] = transition_pieces
                    else:
                        transitions[index] = []
                    exit_points[index] = prev_end
                    entry_points[index + 1] = next_start
            except ValueError as error:
                raise ValueError(
                    "Open segment transition {}->{}: {}".format(
                        index + 1,
                        index + 2,
                        error,
                    )
                )

        for index, is_open in enumerate(open_flags):
            if not is_open:
                continue
            entry_param = WireTransitions.raw_segment_param(
                lines[index],
                entry_points[index],
            )
            exit_param = WireTransitions.raw_segment_param(
                lines[index],
                exit_points[index],
            )
            if not (0.0 <= entry_param <= 1.0 and 0.0 <= exit_param <= 1.0):
                raise ValueError(
                    "Open segment {} transition points lie outside the "
                    "segment.".format(index + 1)
                )
            if entry_param > exit_param + 1e-9:
                raise ValueError(
                    "Open segment {} entry lies after its exit. Move the "
                    "segments farther apart or reduce the radius.".format(
                        index + 1
                    )
                )

        pieces = []
        segments = []
        for index, (line_start, line_end) in enumerate(lines):
            run_start = entry_points[index]
            run_end = exit_points[index]
            run_length = (run_end - run_start).Length
            segments.append(Segment(run_start, run_end))
            if run_length > 1e-9:
                pieces.append(
                    {
                        "kind": "duct",
                        "name": "Segment {}".format(index + 1),
                        "edge": Part.makeLine(run_start, run_end),
                        "length": run_length,
                        "start": run_start,
                        "end": run_end,
                    }
                )
            if index < len(transitions) and transitions[index]:
                pieces.extend(transitions[index])

        if not pieces:
            raise ValueError("Open segment route does not contain any geometry.")

        for index in range(len(pieces) - 1):
            gap = (pieces[index]["end"] - pieces[index + 1]["start"]).Length
            if gap > 1e-6:
                raise ValueError(
                    "Open segment route is not continuous near piece {} "
                    "(gap {:.6f} mm).".format(index + 1, gap)
                )

        wire = Part.Wire([piece["edge"] for piece in pieces])
        if not wire.isValid():
            raise ValueError("Open segment route does not form a valid wire.")

        for piece in pieces:
            piece["label"] = piece.get("label", piece.get("name", "Open transition"))
            piece["type"] = "biarc" if piece["kind"] == "arc" else "segment"
        creator.pieces = pieces
        creator.arcs = [
            piece["edge"] for piece in pieces if piece["kind"] == "arc"
        ]
        creator.wire = wire
        return {
            "segments": segments,
            "pieces": pieces,
            "wire": wire,
            "creator": creator,
        }

    def execute(self, obj):
        if getattr(self, "_executing", False):
            return
        self._executing = True
        try:
            self._rebuild(obj)
        finally:
            self._executing = False

    def _rebuild(self, obj):
        route = list(obj.Points)
        if not route:
            self._set_error(obj, "Define at least one bundle segment.")
            return

        capacity_error = self._capacity_error(obj, route)
        if capacity_error is not None:
            self._set_error(obj, capacity_error)
            return

        directions = list(obj.SegmentDirections)
        if len(directions) < len(route):
            directions.extend([0] * (len(route) - len(directions)))

        needs_open_routing = any(
            index not in (0, len(route) - 1) and segment_is_open(segment_obj)
            for index, segment_obj in enumerate(route)
        )

        if needs_open_routing:
            try:
                open_route = self._build_open_route(obj, route, directions)
            except ValueError as error:
                self._set_error(obj, str(error))
                return
            if open_route is None:
                self._set_error(obj, "Open segment route could not be built.")
                return
            segments = open_route["segments"]
            full_wire = open_route["wire"]
            creator = open_route["creator"]
        else:
            entry_params = list(getattr(obj, "SegmentEntryParams", []) or [])
            exit_params = list(getattr(obj, "SegmentExitParams", []) or [])
            entry_params = (entry_params + [0.0] * len(route))[: len(route)]
            exit_params = (exit_params + [1.0] * len(route))[: len(route)]

            runs = []
            for index, segment_obj in enumerate(route):
                number = index + 1
                if not is_bundle_segment(segment_obj):
                    self._set_error(
                        obj,
                        f"Route item {number} is not a bundle segment. "
                        "Rebuild legacy point routes.",
                    )
                    return
                try:
                    segment_start, segment_end = self._bundle_points(obj, segment_obj)
                except ValueError as error:
                    self._set_error(obj, str(error))
                    return
                if int(directions[index]) % 2:
                    segment_start, segment_end = segment_end, segment_start

                is_tip_segment = index == 0 or index == len(route) - 1
                entry_param = 0.0
                exit_param = 1.0
                if not is_tip_segment:
                    entry_param = float(entry_params[index])
                    exit_param = float(exit_params[index])
                    if not (0.0 <= entry_param <= 1.0 and 0.0 <= exit_param <= 1.0):
                        self._set_error(
                            obj,
                            f"Route item {number} entry/exit parameters must be between 0 and 1.",
                        )
                        return
                    if entry_param > exit_param + 1e-9:
                        self._set_error(
                            obj,
                            f"Route item {number} entry parameter must not be after its exit parameter.",
                        )
                        return

                    is_open = segment_is_open(segment_obj)
                    if not is_open and (
                        abs(entry_param) > 1e-9 or abs(exit_param - 1.0) > 1e-9
                    ):
                        self._set_error(
                            obj,
                            f"Closed bundle segment '{segment_obj.Label}' only allows an "
                            "end-to-end connection. Set its type to Open or use the endpoints.",
                        )
                        return

                if entry_param > 1e-9 or exit_param < 1.0 - 1e-9:
                    direction = segment_end - segment_start
                    entry_point = segment_start + direction * entry_param
                    exit_point = segment_start + direction * exit_param
                else:
                    entry_point = segment_start
                    exit_point = segment_end
                if (exit_point - entry_point).Length >= 1e-9:
                    runs.append(
                        {
                            "start": entry_point,
                            "end": exit_point,
                            "segment": segment_obj,
                        }
                    )

            if not runs:
                self._set_error(obj, "The route does not contain any segments.")
                return

            def run_center(run):
                return (run["start"] + run["end"]) / 2.0

            def control_point(run, at_end):
                if is_lace_helper(run["segment"]):
                    return run_center(run)
                return run["end"] if at_end else run["start"]

            segments = []
            for index, run in enumerate(runs):
                if not is_lace_helper(run["segment"]):
                    segments.append(Segment(run["start"], run["end"]))
                    continue

                current = run_center(run)
                length = (run["end"] - run["start"]).Length
                tangent = run["end"] - run["start"]
                if tangent.Length < 1e-9 or length < 1e-9:
                    segments.append(Segment(run["start"], run["end"]))
                    continue
                tangent = tangent / tangent.Length

                previous_point = (
                    control_point(runs[index - 1], True) if index > 0 else None
                )
                next_point = (
                    control_point(runs[index + 1], False)
                    if index + 1 < len(runs)
                    else None
                )

                forward = (
                    next_point - current if next_point is not None else tangent
                )
                if forward.Length < 1e-9:
                    forward = tangent
                else:
                    forward = forward / forward.Length
                backward = (
                    current - previous_point
                    if previous_point is not None
                    else forward
                )
                if backward.Length < 1e-9:
                    backward = forward
                else:
                    backward = backward / backward.Length
                averaged = backward + forward
                if averaged.Length < 1e-9:
                    averaged = forward
                else:
                    averaged = averaged / averaged.Length

                segments.append(
                    Segment(
                        current - averaged * (length / 2.0),
                        current + averaged * (length / 2.0),
                    )
                )

            creator = WireCreator(min_bend_radius=obj.MinBendRadius.Value)
            try:
                full_wire = creator.create_wire(segments)
            except Exception as error:
                self._set_error(obj, str(error))
                return

        if not segments:
            self._set_error(obj, "The route does not contain any segments.")
            return

        start_tip_length = (segments[0].end - segments[0].start).Length
        end_tip_length = (segments[-1].end - segments[-1].start).Length
        obj.StartTipLength = start_tip_length
        obj.EndTipLength = end_tip_length

        start_settings = self._tip_settings(obj, "StartTip", start_tip_length)
        end_settings = self._tip_settings(obj, "EndTip", end_tip_length)
        start_offset = start_settings["trim"]
        end_offset = end_settings["trim"]
        geometry_creator = creator
        geometry_wire = full_wire
        if start_offset > 0.0 or end_offset > 0.0:
            if needs_open_routing:
                try:
                    geometry_wire = self._trim_open_route(
                        open_route["pieces"],
                        start_offset,
                        end_offset,
                    )
                except Exception as error:
                    self._set_error(obj, str(error))
                    return
            else:
                trimmed = self._trim_route(segments, start_offset, end_offset)
                if not trimmed:
                    self._set_error(
                        obj, "Tip length offsets exceed the cable route length."
                    )
                    return
                geometry_creator = WireCreator(
                    min_bend_radius=obj.MinBendRadius.Value
                )
                try:
                    geometry_wire = geometry_creator.create_wire(trimmed)
                except Exception as error:
                    self._set_error(obj, str(error))
                    return

        path_obj = obj.PathObject
        if _is_valid(path_obj, obj.Document):
            _set_shape(path_obj, geometry_wire)

        show_solid = obj.BuildCable and not getattr(obj, "Preview", False)
        if show_solid:
            cable = geometry_creator.make_cable(
                geometry_wire, diameter=obj.Diameter.Value
            )
            if is_multicolor(
                getattr(obj, "CableColor", "Blue"),
                getattr(obj, "CableColorTracer", TRACER_NONE),
            ):
                sectors = geometry_creator.make_cable_sectors(
                    geometry_wire, diameter=obj.Diameter.Value
                )
                if sectors is not None:
                    cable = sectors
            obj.Shape = cable if cable is not None else Part.Shape()
            start_core_shape = self._make_core(segments[0], start_settings, True)
            end_core_shape = self._make_core(segments[-1], end_settings, False)
        else:
            obj.Shape = Part.Shape()
            start_core_shape = Part.Shape()
            end_core_shape = Part.Shape()

        for property_name, shape in (
            ("StartCoreObject", start_core_shape),
            ("EndCoreObject", end_core_shape),
        ):
            link = getattr(obj, property_name, None)
            if _is_valid(link, obj.Document):
                _set_shape(link, shape)

        start_metal = Part.Shape()
        start_sleeve = Part.Shape()
        end_metal = Part.Shape()
        end_sleeve = Part.Shape()
        if show_solid:
            start_metal, start_sleeve = self._ferrule_shapes(
                obj, getattr(obj, "StartTip", None), segments[0], True
            )
            end_metal, end_sleeve = self._ferrule_shapes(
                obj, getattr(obj, "EndTip", None), segments[-1], False
            )
        for property_name, shape in (
            ("StartFerruleMetal", start_metal),
            ("EndFerruleMetal", end_metal),
            ("StartFerruleSleeve", start_sleeve),
            ("EndFerruleSleeve", end_sleeve),
        ):
            link = getattr(obj, property_name, None)
            if _is_valid(link, obj.Document):
                _set_shape(link, shape)

        bad_results = creator.check_wire()
        radius_shapes = []
        length_shapes = []
        for result in bad_results:
            shape = creator.make_bad_arc_shape(result, diameter=obj.Diameter.Value)
            if shape is None:
                continue
            if 1 in result["failed_tests"]:
                radius_shapes.append(shape)
            else:
                length_shapes.append(shape)
        self._set_bad_shapes(obj, radius_shapes, length_shapes)

        length, minimum_radius = creator.measure()
        cable_length = max(
            0.0,
            length
            - start_settings["connector"]
            - end_settings["connector"],
        )
        obj.Length = length
        obj.CableOnlyLength = cable_length
        obj.MinimumRadius = minimum_radius if minimum_radius is not None else 0.0
        status = (
            f"Total length: {length:.2f} mm | "
            f"Cable-only length: {cable_length:.2f} mm"
        )
        if minimum_radius is None:
            status += " | Minimum bend radius: none"
        else:
            status += f" | Minimum bend radius: {minimum_radius:.2f} mm"
        if bad_results:
            status += f" | WARNING: {len(bad_results)} bad bi-arc edge(s)"
        obj.Status = status
        apply_cable_color(obj)

    @staticmethod
    def _core_diameter(cable, maximum):
        try:
            if getattr(cable, "CoreSizeMode", "Area") == "Diameter":
                diameter = cable.CoreDiameter.Value
            else:
                area = max(0.0, cable.CoreArea)
                diameter = 2.0 * math.sqrt(area / math.pi)
        except Exception:
            diameter = 0.0
        return min(max(0.0, diameter), max(0.0, maximum))

    @classmethod
    def _tip_settings(cls, cable, property_name, maximum_length):
        settings = {
            "trim": 0.0,
            "connector": 0.0,
            "strip": False,
            "core_diameter": 0.0,
        }
        tip = getattr(cable, property_name, None)
        if not _is_valid(tip, cable.Document):
            return settings
        limit = max(0.0, maximum_length - TIP_OFFSET_MARGIN)
        tip_type = getattr(tip, "TipType", "Length offset")
        try:
            if tip_type == "Ferrule":
                variant_data = cls._ferrule_variant(cable, tip)
                if variant_data is not None:
                    settings["trim"] = min(
                        FerruleData.strip_length(variant_data), limit
                    )
                    settings["strip"] = True
                    settings["core_diameter"] = cls._core_diameter(
                        cable, cable.Diameter.Value
                    )
                else:
                    settings["trim"] = min(
                        max(0.0, tip.LengthOffset.Value), limit
                    )
                    settings["connector"] = settings["trim"]
            elif tip_type == "Stripped wire":
                settings["trim"] = min(
                    max(0.0, tip.StrippedLength.Value), limit
                )
                settings["strip"] = True
                settings["core_diameter"] = cls._core_diameter(
                    cable, cable.Diameter.Value
                )
            else:
                settings["trim"] = min(
                    max(0.0, tip.LengthOffset.Value), limit
                )
                settings["connector"] = settings["trim"]
        except Exception:
            pass
        return settings

    @staticmethod
    def _ferrule_info(cable, tip):
        entry = FerruleData.cross_section_for_size(
            getattr(cable, "WireSizeMM2", 0.0)
        )
        if entry is None:
            return None
        type_entry = FerruleData.ferrule_type(
            entry, getattr(tip, "FerruleType", "tube")
        )
        if type_entry is None:
            return None
        variant_data = FerruleData.variant(
            type_entry, getattr(tip, "FerruleVariant", 0)
        )
        if variant_data is None:
            return None
        return entry, type_entry, variant_data

    @staticmethod
    def _ferrule_variant(cable, tip):
        info = WireCableProxy._ferrule_info(cable, tip)
        return info[2] if info is not None else None

    def _ferrule_shapes(self, cable, tip, segment, at_start):
        if not _is_valid(tip, cable.Document):
            return Part.Shape(), Part.Shape()
        if getattr(tip, "TipType", "Length offset") != "Ferrule":
            return Part.Shape(), Part.Shape()
        info = self._ferrule_info(cable, tip)
        if info is None:
            return Part.Shape(), Part.Shape()
        entry, _, variant_data = info
        metal, sleeve = self._make_ferrule_meshes(
            variant_data, segment, at_start
        )
        if not sleeve.isNull():
            info_color, _ = FerruleData.color_for_system(
                entry, getattr(tip, "FerruleColorSystem", "DIN")
            )
            rgb = (
                FerruleData.hex_to_rgb(info_color.get("hex"))
                if info_color is not None
                else None
            )
            if rgb is not None:
                sleeve_link = getattr(
                    cable,
                    "StartFerruleSleeve" if at_start else "EndFerruleSleeve",
                    None,
                )
                if _is_valid(sleeve_link, cable.Document):
                    try:
                        sleeve_link.ViewObject.ShapeColor = rgb
                        sleeve_link.ViewObject.Transparency = 0
                    except Exception:
                        pass
        return metal, sleeve

    @staticmethod
    def _make_ferrule_meshes(variant_data, segment, at_start):
        direction = (
            segment.end - segment.start
            if at_start
            else segment.start - segment.end
        )
        length = direction.Length
        if length < 1e-9:
            return Part.Shape(), Part.Shape()
        axis = direction / length
        base = segment.start if at_start else segment.end

        l1 = variant_data["l1_mm"]
        l2 = variant_data["l2_mm"]
        d1 = variant_data["d1_mm"]
        s1 = variant_data["s1_mm"]
        d2 = variant_data["d2_mm"]
        s2 = variant_data["s2_mm"]
        if min(l1, l2, d1, d2, s1, s2) <= 0.0:
            return Part.Shape(), Part.Shape()

        metal_outer = d1 + 2.0 * s1
        sleeve_outer = d2 + 2.0 * s2
        cone_length = max(0.0, (sleeve_outer - metal_outer) / 2.0)
        sleeve_length = max(0.0, l1 - l2 - cone_length)

        metal = Part.Shape()
        if l2 > 1e-9:
            outer = Part.makeCylinder(metal_outer / 2.0, l2, base, axis)
            inner = Part.makeCylinder(d1 / 2.0, l2, base, axis)
            metal = outer.cut(inner)

        outer_parts = []
        inner_parts = []
        cone_start = base + axis * l2
        sleeve_start = cone_start + axis * cone_length
        if cone_length > 1e-9:
            outer_parts.append(
                Part.makeCone(
                    metal_outer / 2.0,
                    sleeve_outer / 2.0,
                    cone_length,
                    cone_start,
                    axis,
                )
            )
            inner_parts.append(
                Part.makeCone(
                    d1 / 2.0,
                    d2 / 2.0,
                    cone_length,
                    cone_start,
                    axis,
                )
            )
        if sleeve_length > 1e-9:
            outer_parts.append(
                Part.makeCylinder(
                    sleeve_outer / 2.0, sleeve_length, sleeve_start, axis
                )
            )
            inner_parts.append(
                Part.makeCylinder(
                    d2 / 2.0, sleeve_length, sleeve_start, axis
                )
            )

        if not outer_parts:
            return metal, Part.Shape()
        outer_sleeve = outer_parts[0]
        for part in outer_parts[1:]:
            outer_sleeve = outer_sleeve.fuse(part)
        if inner_parts:
            inner_sleeve = inner_parts[0]
            for part in inner_parts[1:]:
                inner_sleeve = inner_sleeve.fuse(part)
            sleeve = outer_sleeve.cut(inner_sleeve)
        else:
            sleeve = outer_sleeve
        return metal, sleeve

    @staticmethod
    def _make_core(segment, settings, at_start):
        trim = settings["trim"]
        diameter = settings["core_diameter"]
        if not settings["strip"] or trim <= 0.0 or diameter <= 0.0:
            return Part.Shape()
        direction = segment.end - segment.start
        length = direction.Length
        if length < 1e-9:
            return Part.Shape()
        direction = direction / length
        base = segment.start if at_start else segment.end - direction * trim
        return Part.makeCylinder(diameter / 2.0, trim, base, direction)

    @staticmethod
    def _trim_route(segments, start_offset, end_offset):
        trimmed = [Segment(item.start, item.end) for item in segments]

        remaining = start_offset
        while trimmed and remaining > 1e-12:
            segment = trimmed[0]
            length = (segment.end - segment.start).Length
            if length < 1e-12:
                trimmed.pop(0)
                continue
            if remaining >= length:
                remaining -= length
                trimmed.pop(0)
            else:
                direction = (segment.end - segment.start) / length
                trimmed[0] = Segment(
                    segment.start + direction * remaining, segment.end
                )
                remaining = 0.0

        remaining = end_offset
        while trimmed and remaining > 1e-12:
            segment = trimmed[-1]
            length = (segment.end - segment.start).Length
            if length < 1e-12:
                trimmed.pop()
                continue
            if remaining >= length:
                remaining -= length
                trimmed.pop()
            else:
                direction = (segment.end - segment.start) / length
                trimmed[-1] = Segment(
                    segment.start, segment.end - direction * remaining
                )
                remaining = 0.0

        return [
            item
            for item in trimmed
            if (item.end - item.start).Length >= 1e-9
        ]

    @staticmethod
    def _trim_open_route(pieces, start_offset, end_offset):
        trimmed = [dict(piece) for piece in pieces]

        if start_offset > 0.0:
            for piece in trimmed:
                if piece["kind"] != "duct":
                    continue
                if start_offset >= piece["length"] - 1e-9:
                    raise ValueError("Tip length offset exceeds the first run.")
                direction = WireTransitions.unit_vector(
                    piece["end"] - piece["start"]
                )
                new_start = piece["start"] + direction * start_offset
                piece["edge"] = Part.makeLine(new_start, piece["end"])
                piece["length"] = piece["edge"].Length
                piece["start"] = new_start
                break

        if end_offset > 0.0:
            for piece in reversed(trimmed):
                if piece["kind"] != "duct":
                    continue
                if end_offset >= piece["length"] - 1e-9:
                    raise ValueError("Tip length offset exceeds the last run.")
                direction = WireTransitions.unit_vector(
                    piece["end"] - piece["start"]
                )
                new_end = piece["end"] - direction * end_offset
                piece["edge"] = Part.makeLine(piece["start"], new_end)
                piece["length"] = piece["edge"].Length
                piece["end"] = new_end
                break

        return Part.Wire([piece["edge"] for piece in trimmed])

    @staticmethod
    def _bundle_offset(cable, bundle_segment):
        harness = getattr(cable, "Harness", None)
        if not is_harness(harness):
            return App.Vector(0.0, 0.0, 0.0)
        try:
            if bundle_segment not in harness.Segments:
                return App.Vector(0.0, 0.0, 0.0)
            raw = harness.Layout.get(layout_key(bundle_segment, cable), "0,0,0")
        except Exception:
            return App.Vector(0.0, 0.0, 0.0)
        side, normal = segment_basis(bundle_segment)
        return decode_offset(raw, side, normal)

    def _bundle_points(self, cable, bundle_segment):
        start_obj = bundle_segment.Start
        end_obj = bundle_segment.End
        if start_obj is None or end_obj is None:
            raise ValueError(
                f"Bundle segment {bundle_segment.Label} needs start and end references."
            )
        start = start_obj.getGlobalPlacement().Base
        end = end_obj.getGlobalPlacement().Base
        if (end - start).Length < 1e-9:
            raise ValueError(
                f"Bundle segment {bundle_segment.Label} has identical start and end points."
            )
        offset = self._bundle_offset(cable, bundle_segment)
        return start + offset, end + offset

    @staticmethod
    def _capacity_error(cable, route):
        document = cable.Document
        if document is None:
            return None
        for segment in route:
            if not is_bundle_segment(segment):
                continue
            limit = int(getattr(segment, "MaxCables", 0) or 0)
            if limit <= 0:
                continue
            users = [
                other
                for other in document.Objects
                if getattr(getattr(other, "Proxy", None), "Type", None) == "WireCable"
                and all(
                    is_bundle_segment(item)
                    for item in getattr(other, "Points", [])
                )
                and any(item is segment for item in getattr(other, "Points", []))
            ]
            if len(users) > limit:
                return (
                    f"Bundle segment {segment.Label} is used by "
                    f"{len(users)} cables (limit {limit})."
                )
        return None

    @staticmethod
    def _append_segment(segments, start, end):
        if (end - start).Length >= 1e-9:
            segments.append(Segment(start, end))

    @staticmethod
    def _set_bad_shapes(obj, radius_shapes, length_shapes):
        for link, shapes in (
            (obj.BadRadiusObject, radius_shapes),
            (obj.BadLengthObject, length_shapes),
        ):
            if not _is_valid(link, obj.Document):
                continue
            _set_shape(link, Part.makeCompound(shapes) if shapes else Part.Shape())

    @staticmethod
    def _set_error(obj, message):
        obj.Shape = Part.Shape()
        path_obj = obj.PathObject
        if _is_valid(path_obj, obj.Document):
            _set_shape(path_obj, Part.Shape())
        for link in (
            obj.BadRadiusObject,
            obj.BadLengthObject,
            getattr(obj, "StartCoreObject", None),
            getattr(obj, "EndCoreObject", None),
            getattr(obj, "StartFerruleMetal", None),
            getattr(obj, "EndFerruleMetal", None),
            getattr(obj, "StartFerruleSleeve", None),
            getattr(obj, "EndFerruleSleeve", None),
        ):
            if _is_valid(link, obj.Document):
                _set_shape(link, Part.Shape())
        obj.Length = 0.0
        obj.CableOnlyLength = 0.0
        obj.StartTipLength = 0.0
        obj.EndTipLength = 0.0
        obj.MinimumRadius = 0.0
        obj.Status = f"Error: {message}"
        try:
            obj.ViewObject.ShapeAppearance = []
            apply_cable_color(obj)
        except Exception:
            pass

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        update_cable_dependencies(obj)
        _remove_legacy_container(obj)
        hide_support_objects(obj)

    def onChanged(self, obj, prop):
        if prop == "Points":
            update_cable_dependencies(obj)
        if prop in (
            "CableColor",
            "CableColorTracer",
            "SegmentEntryParams",
            "SegmentExitParams",
        ):
            obj.touch()
        if prop == "WireSizeMM2":
            self._reset_ferrule_variants(obj)
        if prop in ("Points", "Diameter", "Harness"):
            self._touch_harness(obj)

    @staticmethod
    def _reset_ferrule_variants(cable):
        entry = FerruleData.cross_section_for_size(
            getattr(cable, "WireSizeMM2", 0.0)
        )
        if entry is None:
            return
        available = FerruleData.ferrule_types(entry)
        for name in ("StartTip", "EndTip"):
            tip = getattr(cable, name, None)
            if not _is_valid(tip, cable.Document):
                continue
            if getattr(tip, "TipType", "Length offset") != "Ferrule":
                continue
            type_entry = FerruleData.ferrule_type(
                entry, getattr(tip, "FerruleType", "tube")
            )
            if type_entry is None:
                type_entry = available[0] if available else None
            if type_entry is None:
                continue
            if getattr(tip, "FerruleType", None) != type_entry["type"]:
                tip.FerruleType = type_entry["type"]
            tip.FerruleVariant = FerruleData.default_variant_index(type_entry)

    @staticmethod
    def _touch_harness(cable):
        harness = getattr(cable, "Harness", None)
        if is_harness(harness):
            try:
                harness.touch()
            except Exception:
                pass


class ViewProviderWireCable:
    """View provider that opens the segment editor on double-click."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

    def getIcon(self):
        return ICON

    def attach(self, vobj):
        self.Object = vobj.Object
        apply_cable_color(vobj.Object)

    def setEdit(self, vobj, mode):
        if mode != 0:
            return False
        from .WireTaskPanel import WireTaskPanel

        Gui.Control.showDialog(WireTaskPanel(cable=vobj.Object))
        try:
            from .WireSelection import schedule_select_tool_object

            schedule_select_tool_object(vobj.Object)
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

    def setupContextMenu(self, vobj, menu):
        from PySide import QtGui

        recompute_action = QtGui.QAction("Recompute Wire", menu)
        recompute_action.triggered.connect(
            lambda: self._recompute(vobj.Object)
        )
        menu.addAction(recompute_action)

    @staticmethod
    def _recompute(cable):
        try:
            cable.touch()
            cable.Document.recompute()
        except Exception:
            pass

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        document = obj.Document
        group = find_container(obj)
        document_name = document.Name
        support_names = [
            link.Name
            for link in (
                obj.PathObject,
                obj.BadRadiusObject,
                obj.BadLengthObject,
                getattr(obj, "StartCoreObject", None),
                getattr(obj, "EndCoreObject", None),
                getattr(obj, "StartFerruleMetal", None),
                getattr(obj, "EndFerruleMetal", None),
                getattr(obj, "StartFerruleSleeve", None),
                getattr(obj, "EndFerruleSleeve", None),
                getattr(obj, "StartTip", None),
                getattr(obj, "EndTip", None),
            )
            if _is_valid(link, document)
        ]
        group_name = group.Name if _is_valid(group, document) else None
        harness = getattr(obj, "Harness", None)
        if is_harness(harness):
            try:
                harness.CableOrder = [
                    name for name in harness.CableOrder if name != obj.Name
                ]
                harness.touch()
            except Exception:
                pass

        def cleanup():
            doc = App.getDocument(document_name)
            if doc is None:
                return
            for name in support_names:
                if doc.getObject(name) is not None:
                    try:
                        doc.removeObject(name)
                    except Exception:
                        pass
            if group_name:
                grp = doc.getObject(group_name)
                if grp is not None:
                    try:
                        if not grp.Group:
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


def update_cable_dependencies(cable):
    """Depend on ancestor groups of bundle segment endpoint references."""
    dependencies = []
    seen = set()
    for segment in cable.Points:
        if not is_bundle_segment(segment):
            continue
        for ref in (getattr(segment, "Start", None), getattr(segment, "End", None)):
            if ref is None:
                continue
            for group in ancestor_groups(ref):
                if group.Name in seen:
                    continue
                seen.add(group.Name)
                dependencies.append(group)
    if "Dependencies" in cable.PropertiesList:
        cable.Dependencies = dependencies


def _ensure_global_link_list(obj, name, group, description):
    """Migrate link lists to global so App::Part-scoped references are allowed."""
    if name in obj.PropertiesList:
        if obj.getTypeIdOfProperty(name) == "App::PropertyLinkListGlobal":
            return
        value = list(getattr(obj, name))
        obj.removeProperty(name)
    else:
        value = []
    obj.addProperty("App::PropertyLinkListGlobal", name, group, description)
    if value:
        setattr(obj, name, value)


def _is_valid(obj, document):
    try:
        return obj is not None and obj.isValid() and obj.Document is document
    except Exception:
        return False


def _set_shape(obj, shape):
    obj.Shape = shape
    try:
        obj.purgeTouched()
    except Exception:
        pass


def _remove_legacy_container(obj):
    """Break the old Container link that formed a cycle with the owning group."""
    if "Container" not in obj.PropertiesList:
        return
    try:
        if obj.getTypeIdOfProperty("Container") == "App::PropertyLink":
            obj.Container = None
    except Exception:
        pass
    try:
        obj.removeProperty("Container")
    except Exception:
        pass


def find_container(cable):
    for parent in cable.InList:
        try:
            if parent.TypeId in ("App::DocumentObjectGroup", "App::Part"):
                if cable in parent.Group:
                    return parent
        except Exception:
            continue
    return None


def ensure_core_properties(cable):
    """Ensure wire-level core-size properties and migrate old tip values."""
    properties = cable.PropertiesList
    if "CoreSizeMode" not in properties:
        cable.addProperty(
            "App::PropertyEnumeration",
            "CoreSizeMode",
            "Wire",
            "Conductor core size input mode",
        )
        cable.CoreSizeMode = ["Diameter", "Area"]
        cable.CoreSizeMode = "Area"
    if "CoreArea" not in properties:
        cable.addProperty(
            "App::PropertyFloat",
            "CoreArea",
            "Wire",
            "Conductor core cross-section in square millimetres",
        )
        cable.CoreArea = 1.0
    if "CoreDiameter" not in properties:
        cable.addProperty(
            "App::PropertyLength",
            "CoreDiameter",
            "Wire",
            "Conductor core diameter",
        )
        cable.CoreDiameter = 2.0 * math.sqrt(max(0.0, cable.CoreArea) / math.pi)

    for property_name in ("StartTip", "EndTip"):
        tip = getattr(cable, property_name, None)
        if not _is_valid(tip, cable.Document):
            continue
        if "CoreArea" in tip.PropertiesList:
            try:
                cable.CoreSizeMode = tip.CoreSizeMode
                cable.CoreArea = tip.CoreArea
                cable.CoreDiameter = tip.CoreDiameter
            except Exception:
                pass
        for name in ("CoreSizeMode", "CoreArea", "CoreDiameter"):
            if name in tip.PropertiesList:
                try:
                    tip.removeProperty(name)
                except Exception:
                    pass


def ensure_support_objects(cable):
    """Create the path and bad-arc display objects if they are missing."""
    document = cable.Document
    _remove_legacy_container(cable)
    container = find_container(cable)

    def ensure(property_name, type_id, name, label):
        obj = getattr(cable, property_name)
        if _is_valid(obj, document):
            return obj
        obj = document.addObject(type_id, name)
        obj.Label = label
        setattr(cable, property_name, obj)
        return obj

    path_obj = ensure("PathObject", "Part::Feature", "WirePath", "Wire Path")
    bad_radius = ensure(
        "BadRadiusObject", "Part::Feature", "WireBadRadius", "Bad Bends (Radius)"
    )
    bad_length = ensure(
        "BadLengthObject", "Part::Feature", "WireBadLength", "Bad Bends (Length)"
    )
    start_core = ensure(
        "StartCoreObject", "Part::Feature", "WireStartCore", "Start Core"
    )
    end_core = ensure("EndCoreObject", "Part::Feature", "WireEndCore", "End Core")
    start_ferrule_metal = ensure(
        "StartFerruleMetal",
        "Part::Feature",
        "WireStartFerruleMetal",
        "Start Ferrule Metal",
    )
    end_ferrule_metal = ensure(
        "EndFerruleMetal",
        "Part::Feature",
        "WireEndFerruleMetal",
        "End Ferrule Metal",
    )
    start_ferrule_sleeve = ensure(
        "StartFerruleSleeve",
        "Part::Feature",
        "WireStartFerruleSleeve",
        "Start Ferrule Sleeve",
    )
    end_ferrule_sleeve = ensure(
        "EndFerruleSleeve",
        "Part::Feature",
        "WireEndFerruleSleeve",
        "End Ferrule Sleeve",
    )

    def ensure_tip(property_name, end, name, label):
        tip = getattr(cable, property_name)
        if _is_valid(tip, document):
            if "End" in tip.PropertiesList:
                tip.End = end
            return tip
        tip = create_wire_tip(document, end, name=name, label=label)
        setattr(cable, property_name, tip)
        if container is not None:
            container.addObject(tip)
        return tip

    ensure_tip(
        "StartTip", "Start", "WireStartTip", f"{cable.Label} Start Tip"
    )
    ensure_tip("EndTip", "End", "WireEndTip", f"{cable.Label} End Tip")
    ensure_core_properties(cable)

    try:
        path_obj.ViewObject.LineColor = (0.85, 0.1, 0.1)
        path_obj.ViewObject.LineWidth = 3
    except Exception:
        pass
    try:
        bad_radius.ViewObject.ShapeColor = (1.0, 0.0, 0.0)
        bad_radius.ViewObject.Transparency = 0
        bad_length.ViewObject.ShapeColor = (1.0, 0.55, 0.0)
        bad_length.ViewObject.Transparency = 0
    except Exception:
        pass
    hide_support_objects(cable)

    try:
        start_core.ViewObject.ShapeColor = (0.8, 0.45, 0.2)
        start_core.ViewObject.Transparency = 0
        end_core.ViewObject.ShapeColor = (0.8, 0.45, 0.2)
        end_core.ViewObject.Transparency = 0
    except Exception:
        pass
    try:
        for obj in (
            start_ferrule_metal,
            end_ferrule_metal,
        ):
            obj.ViewObject.ShapeColor = (0.75, 0.75, 0.78)
            obj.ViewObject.Transparency = 0
        for obj in (
            start_ferrule_sleeve,
            end_ferrule_sleeve,
        ):
            obj.ViewObject.Transparency = 0
    except Exception:
        pass

    return path_obj, bad_radius, bad_length


def rename_cable(cable, label):
    """Set the cable label and keep its owning group and tips in sync."""
    cable.Label = label
    group = find_container(cable)
    if _is_valid(group, cable.Document):
        group.Label = f"{label} Group"
    for property_name, end in (("StartTip", "Start"), ("EndTip", "End")):
        tip = getattr(cable, property_name, None)
        if _is_valid(tip, cable.Document):
            tip.Label = f"{label} {end} Tip"
    for property_name, end in (
        ("StartCoreObject", "Start"),
        ("EndCoreObject", "End"),
    ):
        core = getattr(cable, property_name, None)
        if _is_valid(core, cable.Document):
            core.Label = f"{label} {end} Core"


def hide_support_objects(cable):
    """Keep only the cable and its tips visible in the tree view."""
    document = cable.Document
    helpers = []
    for property_name in SUPPORT_OBJECT_PROPERTIES:
        obj = getattr(cable, property_name, None)
        if _is_valid(obj, document):
            helpers.append(obj)
            try:
                obj.ViewObject.ShowInTree = False
            except Exception:
                pass

    container = find_container(cable)
    if _is_valid(container, document):
        children = [child for child in container.Group if child not in helpers]
        if len(children) != len(container.Group):
            container.Group = children


def _color_material(name):
    rgb = color_rgb(name)
    if rgb is None:
        return None
    material = App.Material()
    material.DiffuseColor = (rgb[0], rgb[1], rgb[2], 1.0)
    material.Transparency = 0
    return material


def apply_cable_color(cable):
    """Apply the cable's insulation colors to the 3D view."""
    primary_name = getattr(cable, "CableColor", "Blue")
    tracer_name = getattr(cable, "CableColorTracer", TRACER_NONE)
    colors = cable_color_quadrants(primary_name, tracer_name)
    primary = color_rgb(primary_name)
    if primary is None:
        return
    view = getattr(cable, "ViewObject", None)
    if view is None:
        return
    transparency = getattr(view, "Transparency", 0)
    shape = getattr(cable, "Shape", None)
    if colors and len(set(colors)) > 1 and shape is not None:
        solids = list(getattr(shape, "Solids", []) or [])
        if len(solids) == len(colors):
            materials = []
            for color, solid in zip(colors, solids):
                material = _color_material(color)
                if material is None:
                    break
                materials.extend([material] * len(solid.Faces))
            if len(materials) == len(shape.Faces):
                try:
                    view.ShapeColor = primary
                    view.ShapeAppearance = materials
                    view.Transparency = transparency
                    return
                except Exception:
                    pass
    try:
        view.ShapeAppearance = []
        view.ShapeColor = primary
        view.Transparency = transparency
    except Exception:
        pass


def create_wire_cable(
    document,
    points,
    directions=None,
    diameter=4.0,
    min_bend_radius=12.0,
    container=None,
    build_cable=True,
    name=None,
    label=None,
):
    """Create a persistent cable object from ordered bundle segments."""
    cable = document.addObject("Part::FeaturePython", name or "WireCable")
    cable.Label = label or "Wire Cable"
    WireCableProxy(cable)

    if App.GuiUp:
        ViewProviderWireCable(cable.ViewObject)
        apply_cable_color(cable)
        try:
            cable.ViewObject.Transparency = 0
        except Exception:
            pass

    cable.Points = list(points)
    cable.SegmentDirections = list(
        directions if directions is not None else [0] * len(points)
    )
    update_cable_dependencies(cable)
    cable.Diameter = diameter
    cable.MinBendRadius = min_bend_radius
    cable.BuildCable = build_cable
    if _is_valid(container, document):
        container.addObject(cable)

    ensure_support_objects(cable)
    return cable
