"""Persistent wire cable document object and view provider."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from .WireBundle import (
    ancestor_groups,
    is_bundle_segment,
    is_harness,
    segment_basis,
)
from .WireCreator import Segment, WireCreator

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")


class WireCableProxy:
    """Document object that rebuilds path and cable geometry from linked points."""

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
            "Ordered start/end node references (start 1, end 1, start 2, ...)",
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
        if "MinBendRadius" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "MinBendRadius",
                "Wire",
                "Minimum allowed bending radius",
            )
            obj.MinBendRadius = 12.0
        if "BuildCable" not in properties:
            obj.addProperty(
                "App::PropertyBool",
                "BuildCable",
                "Wire",
                "Create the swept cable solid (otherwise only the path is built)",
            )
            obj.BuildCable = True
        if "Length" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "Length",
                "Wire",
                "Computed total path length",
            )
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
        ):
            if name not in properties:
                obj.addProperty("App::PropertyLink", name, "Wire", description)

    def execute(self, obj):
        if getattr(self, "_executing", False):
            return
        self._executing = True
        try:
            self._rebuild(obj)
        finally:
            self._executing = False

    def _rebuild(self, obj):
        points = list(obj.Points)
        if not points or len(points) % 2:
            self._set_error(obj, "Define at least one complete segment.")
            return

        segments = []
        for index in range(0, len(points), 2):
            start_obj = points[index]
            end_obj = points[index + 1]
            number = index // 2 + 1
            if start_obj is None or end_obj is None:
                self._set_error(
                    obj, f"Segment {number} is missing a start or end point."
                )
                return

            start_is_bundle = is_bundle_segment(start_obj)
            end_is_bundle = is_bundle_segment(end_obj)
            if start_is_bundle and end_is_bundle and start_obj is end_obj:
                try:
                    bundle_start, bundle_end = self._bundle_points(obj, start_obj)
                    self._append_segment(segments, bundle_start, bundle_end)
                except ValueError as error:
                    self._set_error(obj, str(error))
                    return
                continue

            try:
                if start_is_bundle:
                    bundle_start, bundle_end = self._bundle_points(obj, start_obj)
                    self._append_segment(segments, bundle_start, bundle_end)
                    connection = bundle_end
                else:
                    connection = start_obj.getGlobalPlacement().Base

                if end_is_bundle:
                    bundle_start, bundle_end = self._bundle_points(obj, end_obj)
                    if not start_is_bundle:
                        if start_obj is not end_obj.End:
                            self._append_segment(segments, connection, bundle_end)
                    self._append_segment(segments, bundle_end, bundle_start)
                else:
                    end_point = end_obj.getGlobalPlacement().Base
                    if start_is_bundle and end_obj is start_obj.End:
                        pass
                    else:
                        if not start_is_bundle and (
                            end_point - connection
                        ).Length < 1e-9:
                            raise ValueError(
                                f"Segment {number} has identical start and end points."
                            )
                        self._append_segment(segments, connection, end_point)
            except ValueError as error:
                self._set_error(obj, str(error))
                return

        if not segments:
            self._set_error(obj, "The route does not contain any segments.")
            return

        creator = WireCreator(min_bend_radius=obj.MinBendRadius.Value)
        try:
            wire = creator.create_wire(segments)
        except Exception as error:
            self._set_error(obj, str(error))
            return

        path_obj = obj.PathObject
        if _is_valid(path_obj, obj.Document):
            _set_shape(path_obj, wire)

        if obj.BuildCable:
            cable = creator.make_cable(wire, diameter=obj.Diameter.Value)
            obj.Shape = cable if cable is not None else Part.Shape()
        else:
            obj.Shape = Part.Shape()

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
        obj.Length = length
        obj.MinimumRadius = minimum_radius if minimum_radius is not None else 0.0
        status = f"Path length: {length:.2f} mm"
        if minimum_radius is None:
            status += " | Minimum bend radius: none"
        else:
            status += f" | Minimum bend radius: {minimum_radius:.2f} mm"
        if bad_results:
            status += f" | WARNING: {len(bad_results)} bad bi-arc edge(s)"
        obj.Status = status

    @staticmethod
    def _bundle_offset(cable, bundle_segment):
        harness = getattr(cable, "Harness", None)
        if not is_harness(harness):
            return App.Vector(0.0, 0.0, 0.0)
        try:
            if bundle_segment not in harness.Segments:
                return App.Vector(0.0, 0.0, 0.0)
            key = f"{bundle_segment.Name}|{cable.Name}"
            raw = harness.Layout.get(key, "0,0,0")
            parts = [
                float(value)
                for value in raw.replace(";", ",").split(",")
                if value.strip()
            ]
        except Exception:
            return App.Vector(0.0, 0.0, 0.0)

        if len(parts) >= 3:
            return App.Vector(parts[0], parts[1], parts[2])
        side, normal = segment_basis(bundle_segment)
        if len(parts) == 2:
            return side * parts[0] + normal * parts[1]
        if len(parts) == 1:
            return side * parts[0]
        return App.Vector(0.0, 0.0, 0.0)

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
        for link in (obj.BadRadiusObject, obj.BadLengthObject):
            if _is_valid(link, obj.Document):
                _set_shape(link, Part.Shape())
        obj.Length = 0.0
        obj.MinimumRadius = 0.0
        obj.Status = f"Error: {message}"

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        update_cable_dependencies(obj)
        _remove_legacy_container(obj)

    def onChanged(self, obj, prop):
        if prop == "Points":
            update_cable_dependencies(obj)
        if prop in ("Points", "Diameter", "Harness"):
            self._touch_harness(obj)

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

    def setEdit(self, vobj, mode):
        if mode != 0:
            return False
        from .WireTaskPanel import WireTaskPanel

        Gui.Control.showDialog(WireTaskPanel(cable=vobj.Object))
        return True

    def unsetEdit(self, vobj, mode):
        if mode != 0:
            return False
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object, 0)
        return True

    def setupContextMenu(self, vobj, menu):
        from PySide import QtGui

        edit_action = QtGui.QAction("Edit Wire", menu)
        edit_action.triggered.connect(lambda: self.doubleClicked(vobj))
        menu.addAction(edit_action)

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
            for link in (obj.PathObject, obj.BadRadiusObject, obj.BadLengthObject)
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
    """Depend on ancestor groups of direct point references."""
    dependencies = []
    seen = set()
    for node in cable.Points:
        if node is None or is_bundle_segment(node):
            continue
        for group in ancestor_groups(node):
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
        if container is not None:
            container.addObject(obj)
        return obj

    path_obj = ensure("PathObject", "Part::Feature", "WirePath", "Wire Path")
    bad_radius = ensure(
        "BadRadiusObject", "Part::Feature", "WireBadRadius", "Bad Bends (Radius)"
    )
    bad_length = ensure(
        "BadLengthObject", "Part::Feature", "WireBadLength", "Bad Bends (Length)"
    )

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

    return path_obj, bad_radius, bad_length


def rename_cable(cable, label):
    """Set the cable label and keep its owning group label in sync."""
    cable.Label = label
    group = find_container(cable)
    if _is_valid(group, cable.Document):
        group.Label = f"{label} Group"


def create_wire_cable(
    document,
    points,
    diameter=4.0,
    min_bend_radius=12.0,
    container=None,
    build_cable=True,
    name=None,
    label=None,
):
    """Create a persistent cable object with its path and bad-arc helpers."""
    cable = document.addObject("Part::FeaturePython", name or "WireCable")
    cable.Label = label or "Wire Cable"
    WireCableProxy(cable)

    if App.GuiUp:
        ViewProviderWireCable(cable.ViewObject)
        try:
            cable.ViewObject.ShapeColor = (0.2, 0.45, 0.8)
            cable.ViewObject.Transparency = 20
        except Exception:
            pass

    cable.Points = list(points)
    update_cable_dependencies(cable)
    cable.Diameter = diameter
    cable.MinBendRadius = min_bend_radius
    cable.BuildCable = build_cable
    if _is_valid(container, document):
        container.addObject(cable)

    ensure_support_objects(cable)
    return cable
