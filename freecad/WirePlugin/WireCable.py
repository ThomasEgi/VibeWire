"""Persistent wire cable document object and view provider."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

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

        if "Points" not in properties:
            obj.addProperty(
                "App::PropertyLinkList",
                "Points",
                "Wire",
                "Ordered start/end coordinate systems (start 1, end 1, start 2, ...)",
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
            if start_obj is None or end_obj is None:
                self._set_error(
                    obj, f"Segment {index // 2 + 1} is missing a start or end point."
                )
                return
            start = start_obj.getGlobalPlacement().Base
            end = end_obj.getGlobalPlacement().Base
            if (end - start).Length < 1e-9:
                self._set_error(
                    obj,
                    f"Segment {index // 2 + 1} has identical start and end points.",
                )
                return
            segments.append(Segment(start, end))

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
        _remove_legacy_container(obj)


class ViewProviderWireCable:
    """View provider that opens the segment editor on double-click."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

    def getIcon(self):
        return ICON

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
    cable.Diameter = diameter
    cable.MinBendRadius = min_bend_radius
    cable.BuildCable = build_cable
    if _is_valid(container, document):
        container.addObject(cable)

    ensure_support_objects(cable)
    return cable
