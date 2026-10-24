"""Persistent bundle and bundle-segment objects."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")
BUNDLE_SEGMENT_TYPE = "WireBundleSegment"


def is_bundle_segment(obj):
    """Return True if obj is a WireBundleSegment document object."""
    return getattr(getattr(obj, "Proxy", None), "Type", None) == BUNDLE_SEGMENT_TYPE


class WireBundleProxy:
    """Bundle container for independent straight routing segments."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "WireBundle"
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        properties = obj.PropertiesList
        if "Segments" not in properties:
            obj.addProperty(
                "App::PropertyLinkList",
                "Segments",
                "Bundle",
                "Independent straight bundle segments",
            )
        if "Cables" not in properties:
            obj.addProperty(
                "App::PropertyLinkList",
                "Cables",
                "Bundle",
                "Cables routed on this bundle",
            )

    def execute(self, obj):
        pass

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)


class ViewProviderWireBundle:
    """Bundle view provider with tree children and editor entry point."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

    def getIcon(self):
        return ICON

    def attach(self, vobj):
        self.Object = vobj.Object

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        return list(obj.Segments) if obj is not None else []

    def setEdit(self, vobj, mode):
        if mode != 0:
            return False
        from .WireBundleTaskPanel import WireBundleTaskPanel

        Gui.Control.showDialog(WireBundleTaskPanel(bundle=vobj.Object))
        return True

    def unsetEdit(self, vobj, mode):
        if mode != 0:
            return False
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object, 0)
        return True

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        document = obj.Document
        document_name = document.Name
        segment_names = [
            segment.Name for segment in obj.Segments if segment.isValid()
        ]

        def cleanup():
            doc = App.getDocument(document_name)
            if doc is None:
                return
            for name in segment_names:
                if doc.getObject(name) is not None:
                    try:
                        doc.removeObject(name)
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


class WireBundleSegmentProxy:
    """Straight bundle segment displayed as a pickable cylinder."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = BUNDLE_SEGMENT_TYPE
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        _ensure_global_link(obj, "Start", "Segment start point reference")
        _ensure_global_link(obj, "End", "Segment end point reference")
        if "Radius" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyLength",
                "Radius",
                "Segment",
                "Visualization radius",
            )
            obj.Radius = 10.0
        if "Dependencies" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyLinkListGlobal",
                "Dependencies",
                "Segment",
                "Ancestor groups that affect the reference placements",
            )
            try:
                obj.setEditorMode("Dependencies", 2)
            except Exception:
                pass

    def execute(self, obj):
        start_obj = obj.Start
        end_obj = obj.End
        if start_obj is None or end_obj is None:
            obj.Shape = Part.Shape()
            return
        start = start_obj.getGlobalPlacement().Base
        end = end_obj.getGlobalPlacement().Base
        direction = end - start
        length = direction.Length
        if length < 1e-9 or obj.Radius.Value <= 0.0:
            obj.Shape = Part.Shape()
            return
        obj.Shape = Part.makeCylinder(
            obj.Radius.Value, length, start, direction / length
        )

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)



def _ensure_global_link(obj, name, description):
    """Use global links so segment references may point into App::Part scopes."""
    if name in obj.PropertiesList:
        if obj.getTypeIdOfProperty(name) == "App::PropertyLinkGlobal":
            return
        value = getattr(obj, name)
        obj.removeProperty(name)
    else:
        value = None
    obj.addProperty("App::PropertyLinkGlobal", name, "Segment", description)
    if value is not None:
        setattr(obj, name, value)


def ancestor_groups(obj):
    groups = []
    seen = set()
    try:
        parent = obj.getParentGeoFeatureGroup()
    except Exception:
        parent = None
    while parent is not None:
        if parent.Name in seen:
            break
        seen.add(parent.Name)
        groups.append(parent)
        try:
            parent = parent.getParentGeoFeatureGroup()
        except Exception:
            parent = None
    return groups


def update_segment_dependencies(segment):
    """Depend on ancestor groups so moving an enclosing Part recomputes us."""
    dependencies = []
    seen = set()
    for ref in (segment.Start, segment.End):
        if ref is None:
            continue
        for group in ancestor_groups(ref):
            if group.Name in seen:
                continue
            seen.add(group.Name)
            dependencies.append(group)
    if "Dependencies" in segment.PropertiesList:
        segment.Dependencies = dependencies


def create_wire_bundle(document, label="Bundle"):
    bundle = document.addObject("App::FeaturePython", "WireBundle")
    bundle.Label = label
    WireBundleProxy(bundle)
    if App.GuiUp:
        ViewProviderWireBundle(bundle.ViewObject)
    return bundle


def create_bundle_segment(bundle, start, end, radius=10.0):
    document = bundle.Document
    segment = document.addObject("Part::FeaturePython", "BundleSegment")
    segment.Label = "Bundle Segment"
    WireBundleSegmentProxy(segment)
    segment.Start = start
    segment.End = end
    segment.Radius = radius
    update_segment_dependencies(segment)
    if App.GuiUp:
        try:
            segment.ViewObject.ShapeColor = (0.35, 0.7, 0.9)
            segment.ViewObject.Transparency = 60
        except Exception:
            pass
    segments = list(bundle.Segments)
    segments.append(segment)
    bundle.Segments = segments
    return segment


def remove_bundle_segment(bundle, segment):
    segments = [item for item in bundle.Segments if item is not segment]
    bundle.Segments = segments
    document = bundle.Document
    if document.getObject(segment.Name) is segment:
        document.removeObject(segment.Name)
