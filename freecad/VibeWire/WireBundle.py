"""Persistent bundle and bundle-segment objects."""

import math
import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from .WirePacking import packed_fit_radius, packed_positions

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")
BUNDLE_SEGMENT_TYPE = "WireBundleSegment"
ROUTE_SEGMENT_ROLE = "Route"
LACE_HELPER_ROLE = "Lace Helper"
_PACKING_FALLBACK_WARNED = False


def is_bundle_segment(obj):
    """Return True if obj is a WireBundleSegment document object."""
    return getattr(getattr(obj, "Proxy", None), "Type", None) == BUNDLE_SEGMENT_TYPE


def segment_is_open(segment):
    """Return True when a bundle segment allows arbitrary wire entry/exit."""
    return getattr(segment, "SegmentType", "Closed") == "Open"


def is_lace_helper(obj):
    """Return True for auto-generated lace helper segments."""
    if getattr(obj, "SegmentRole", None) == LACE_HELPER_ROLE:
        return True
    return getattr(obj, "Label", "").startswith("Lace Helper ")


def _cross_2d(origin, first, second):
    return (
        (first[0] - origin[0]) * (second[1] - origin[1])
        - (first[1] - origin[1]) * (second[0] - origin[0])
    )


def _convex_hull_2d(points):
    unique = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(unique) <= 1:
        return unique
    lower = []
    for point in unique:
        while (
            len(lower) >= 2
            and _cross_2d(lower[-2], lower[-1], point) <= 0.0
        ):
            lower.pop()
        lower.append(point)
    upper = []
    for point in reversed(unique):
        while (
            len(upper) >= 2
            and _cross_2d(upper[-2], upper[-1], point) <= 0.0
        ):
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _bundle_hull_shape(start, side, normal, positions, diameters, samples=64):
    if not positions:
        return Part.Shape()
    angles = [
        2.0 * math.pi * index / samples
        for index in range(samples)
    ]
    points = []
    for (x, y), diameter in zip(positions, diameters):
        radius = max(0.0, diameter) / 2.0
        for angle in angles:
            points.append(
                (
                    x + radius * math.cos(angle),
                    y + radius * math.sin(angle),
                )
            )
    hull = _convex_hull_2d(points)
    if len(hull) < 3:
        return Part.Shape()
    points3d = [
        start + side * x + normal * y
        for x, y in hull
    ]
    points3d.append(points3d[0])
    return Part.makePolygon(points3d)


class WireHarnessProxy:
    """Harness container and layout authority for bundle segments and cables."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "WireHarness"
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        properties = obj.PropertiesList
        if "Segments" not in properties:
            obj.addProperty(
                "App::PropertyLinkList",
                "Segments",
                "Harness",
                "Independent straight bundle segments",
            )
        if "SegmentGroup" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "SegmentGroup",
                "Harness",
                "Group containing the harness bundle segments",
            )
        if "HelperGroup" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "HelperGroup",
                "Harness",
                "Group containing the lace helper segments",
            )
        if "CableOrder" not in properties:
            obj.addProperty(
                "App::PropertyStringList",
                "CableOrder",
                "Harness",
                "Preferred cable order inside the harness",
            )
        if "Gap" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "Gap",
                "Harness",
                "Edge-to-edge gap between cables",
            )
            obj.Gap = 1.0
        if "Pattern" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "Pattern",
                "Harness",
                "Cable arrangement pattern",
            )
        current_pattern = getattr(obj, "Pattern", "Circular")
        obj.Pattern = ["Circular", "Linear", "Packed"]
        obj.Pattern = (
            current_pattern
            if current_pattern in ("Circular", "Linear", "Packed")
            else "Circular"
        )
        if "Layout" not in properties:
            obj.addProperty(
                "App::PropertyMap",
                "Layout",
                "Harness",
                "Computed cable lane offsets keyed by segment|cable",
            )
            try:
                obj.setEditorMode("Layout", 2)
            except Exception:
                pass

    def execute(self, obj):
        cables = [item for item in obj.InList if is_wire_cable(item)]
        order = list(obj.CableOrder)
        order_index = {name: index for index, name in enumerate(order)}
        cables.sort(
            key=lambda cable: (
                order_index.get(cable.Name, len(order)),
                cable.Name,
            )
        )

        gap = obj.Gap.Value
        pattern = getattr(obj, "Pattern", "Circular")
        layout = {}
        for segment in obj.Segments:
            if not is_bundle_segment(segment):
                continue
            users = [
                cable for cable in cables if cable_uses_segment(cable, segment)
            ]
            if not users:
                if "HullCurve" in segment.PropertiesList:
                    try:
                        segment.HullCurve = Part.Shape()
                    except Exception:
                        pass
                continue

            diameters = [max(0.0, cable.Diameter.Value) for cable in users]
            count = len(users)
            if pattern == "Linear":
                positions = self._linear_positions(diameters, gap)
            elif pattern == "Packed":
                positions = packed_positions(diameters)
                if positions is None:
                    global _PACKING_FALLBACK_WARNED
                    if not _PACKING_FALLBACK_WARNED:
                        App.Console.PrintWarning(
                            "VibeWire: pymunk is unavailable; Packed harness "
                            "pattern is falling back to Circular.\n"
                        )
                        _PACKING_FALLBACK_WARNED = True
                    positions = self._circular_positions(diameters, gap)
                else:
                    fit_radius = packed_fit_radius(diameters)
                    if fit_radius is not None:
                        if abs(segment.Radius.Value - fit_radius) > 1e-6:
                            segment.Radius = fit_radius
                            try:
                                segment.Proxy.execute(segment)
                            except Exception:
                                segment.touch()
            else:
                positions = self._circular_positions(diameters, gap)

            side, normal = segment_basis(segment)
            for cable, (x, y) in zip(users, positions):
                offset = side * x + normal * y
                layout[f"{segment.Name}|{cable.Name}"] = (
                    f"{offset.x:.9f},{offset.y:.9f},{offset.z:.9f}"
                )

            if "HullCurve" not in segment.PropertiesList:
                try:
                    WireBundleSegmentProxy._add_properties(segment)
                except Exception:
                    pass
            try:
                start = segment.Start.getGlobalPlacement().Base
                segment.HullCurve = _bundle_hull_shape(
                    start,
                    side,
                    normal,
                    positions,
                    diameters,
                )
            except Exception:
                try:
                    segment.HullCurve = Part.Shape()
                except Exception:
                    pass
        obj.Layout = layout

    @staticmethod
    def _linear_positions(diameters, gap):
        total = sum(diameters) + gap * (len(diameters) - 1)
        position = -total / 2.0
        positions = []
        for diameter in diameters:
            positions.append((position + diameter / 2.0, 0.0))
            position += diameter + gap
        return positions

    @staticmethod
    def _circular_positions(diameters, gap):
        count = len(diameters)
        if count == 1:
            return [(0.0, 0.0)]
        angle_step = 2.0 * math.pi / count
        required = [
            diameters[i] / 2.0
            + gap
            + diameters[(i + 1) % count] / 2.0
            for i in range(count)
        ]
        radius = max(required) / (2.0 * math.sin(math.pi / count))
        positions = []
        for index in range(count):
            angle = index * angle_step
            positions.append((radius * math.cos(angle), radius * math.sin(angle)))
        return positions


    def dumps(self):
        return self.Type

    def loads(self, state):
        self.Type = "WireHarness"

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        ensure_segment_group(obj)
        ensure_helper_group(obj)
        if "Cables" in obj.PropertiesList:
            try:
                obj.removeProperty("Cables")
            except Exception:
                pass


WireBundleProxy = WireHarnessProxy


def segment_basis(segment):
    start_obj = segment.Start
    end_obj = segment.End
    if start_obj is None or end_obj is None:
        return App.Vector(1.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0)
    start = start_obj.getGlobalPlacement().Base
    end = end_obj.getGlobalPlacement().Base
    direction = end - start
    length = direction.Length
    if length < 1e-9:
        return App.Vector(1.0, 0.0, 0.0), App.Vector(0.0, 1.0, 0.0)
    direction = direction / length
    orientation = 0.0
    if "Orientation" in segment.PropertiesList:
        orientation = math.radians(segment.Orientation.Value)
    side = segment_side_vector(start, end, orientation, start_obj, end_obj)
    normal = direction.cross(side)
    if normal.Length < 1e-9:
        normal = App.Vector(0.0, 0.0, 1.0)
    else:
        normal = normal.normalize()
    return side, normal


def is_harness(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) in (
        "WireHarness",
        "WireBundle",
    )


def is_wire_cable(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable"


def cable_uses_segment(cable, segment):
    points = list(getattr(cable, "Points", []))
    if not points or not all(is_bundle_segment(node) for node in points):
        return False
    return any(node is segment for node in points)


def find_harness_for_segments(nodes):
    for node in nodes:
        if not is_bundle_segment(node):
            continue
        for parent in node.InList:
            if is_harness(parent):
                return parent
    return None


def add_cable_to_harness(harness, cable):
    if not is_harness(harness):
        try:
            cable.Harness = None
        except Exception:
            pass
        return
    cable.Harness = harness
    order = list(harness.CableOrder)
    if cable.Name not in order:
        order.append(cable.Name)
        harness.CableOrder = order
    harness.touch()


def _reference_axis(ref, axis):
    if ref is None:
        return None
    try:
        return ref.getGlobalPlacement().Rotation.multVec(axis)
    except Exception:
        return None


def _averaged_reference_axis(start_ref, end_ref, axis):
    start_axis = _reference_axis(start_ref, axis)
    end_axis = _reference_axis(end_ref, axis)
    if start_axis is None and end_axis is None:
        return None
    if start_axis is None:
        return end_axis.normalize() if end_axis.Length > 1e-9 else None
    if end_axis is None:
        return start_axis.normalize() if start_axis.Length > 1e-9 else None
    combined = start_axis + end_axis
    if combined.Length < 1e-9:
        return start_axis.normalize()
    return combined.normalize()


def segment_side_vector(
    start, end, orientation=0.0, start_ref=None, end_ref=None
):
    """Lateral axis from the averaged reference frames plus manual roll."""
    direction = end - start
    length = direction.Length
    if length < 1e-9:
        return App.Vector(0.0, 0.0, 0.0)
    direction = direction / length

    side = None
    for axis in (
        App.Vector(0.0, 0.0, 1.0),
        App.Vector(0.0, 1.0, 0.0),
        App.Vector(1.0, 0.0, 0.0),
    ):
        up = _averaged_reference_axis(start_ref, end_ref, axis)
        if up is None:
            continue
        candidate = direction.cross(up)
        if candidate.Length > 1e-9:
            side = candidate.normalize()
            break

    if side is None:
        up = App.Vector(0.0, 0.0, 1.0)
        if abs(direction.dot(up)) > 0.99:
            up = App.Vector(0.0, 1.0, 0.0)
        side = direction.cross(up)
        if side.Length < 1e-9:
            side = direction.cross(App.Vector(1.0, 0.0, 0.0))
        side = side.normalize()

    if abs(orientation) > 1e-12:
        normal = direction.cross(side)
        if normal.Length > 1e-9:
            normal = normal.normalize()
            side = side * math.cos(orientation) + normal * math.sin(orientation)
    return side


class ViewProviderWireBundle:
    """Bundle view provider with tree children and editor entry point."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object
        self._setup_display_mode(vobj)

    def getIcon(self):
        return ICON

    def attach(self, vobj):
        self.Object = vobj.Object
        self._setup_display_mode(vobj)
        self._sync_visibility_mode(vobj)
        try:
            vobj.signalChangeIcon()
        except Exception:
            pass

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            self._sync_visibility_mode(vobj)
            try:
                vobj.signalChangeIcon()
            except Exception:
                pass

    @staticmethod
    def _mode_switch(vobj):
        try:
            from pivy import coin

            root = vobj.RootNode
            for i in range(root.getNumChildren()):
                node = root.getChild(i)
                if isinstance(node, coin.SoSwitch):
                    return node
        except Exception:
            pass
        return None

    def _setup_display_mode(self, vobj):
        switch = self._mode_switch(vobj)
        if switch is not None:
            try:
                if switch.getNumChildren() == 0:
                    from pivy import coin

                    self._coin_node = coin.SoSeparator()
                    vobj.addDisplayMode(self._coin_node, "Default")
            except Exception:
                self._coin_node = None
        try:
            vobj.DefaultMode = 0
        except Exception:
            pass

    @staticmethod
    def _sync_visibility_mode(vobj):
        switch = ViewProviderWireBundle._mode_switch(vobj)
        if switch is None:
            return
        try:
            switch.whichChild = 0 if vobj.Visibility else -1
        except Exception:
            pass

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return []
        children = []
        for property_name in ("SegmentGroup", "HelperGroup"):
            group = getattr(obj, property_name, None)
            if group is not None and group.isValid() and group not in children:
                children.append(group)
        if not children:
            children = list(obj.Segments)
        try:
            from .WireCable import find_container

            for cable in obj.InList:
                if not is_wire_cable(cable):
                    continue
                group = find_container(cable)
                if group is not None and group not in children:
                    children.append(group)
        except Exception:
            pass
        return children

    def setEdit(self, vobj, mode):
        if mode != 0:
            return False
        from .WireBundleTaskPanel import WireBundleTaskPanel

        harness = vobj.Object
        selected_segment = None
        for selected in Gui.Selection.getSelection():
            if is_bundle_segment(selected) and selected in harness.Segments:
                selected_segment = selected
                break
        Gui.Control.showDialog(WireBundleTaskPanel(bundle=harness))
        try:
            from .WireSelection import schedule_select_tool_object

            schedule_select_tool_object(selected_segment or harness)
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

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        document = obj.Document
        document_name = document.Name
        segment_names = [
            segment.Name for segment in obj.Segments if segment.isValid()
        ]
        group_names = []
        for property_name in ("SegmentGroup", "HelperGroup"):
            group = getattr(obj, property_name, None)
            if group is not None and group.isValid():
                group_names.append(group.Name)

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
            for group_name in group_names:
                if doc.getObject(group_name) is not None:
                    try:
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


ViewProviderWireHarness = ViewProviderWireBundle


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
        if "Orientation" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyAngle",
                "Orientation",
                "Segment",
                "Rotation of the cable arrangement about the segment axis",
            )
            obj.Orientation = 0.0
        if "MaxCables" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyInteger",
                "MaxCables",
                "Segment",
                "Maximum cables allowed in this segment (0 = unlimited)",
            )
            obj.MaxCables = 0
        if "SegmentType" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "SegmentType",
                "Segment",
                "Closed = end-to-end connections only; Open = wires may enter/exit anywhere",
            )
            obj.SegmentType = ["Closed", "Open"]
            obj.SegmentType = "Closed"
        if "SegmentRole" not in obj.PropertiesList:
            role = LACE_HELPER_ROLE if obj.Label.startswith("Lace Helper ") else ROUTE_SEGMENT_ROLE
            obj.addProperty(
                "App::PropertyEnumeration",
                "SegmentRole",
                "Segment",
                "Route = user routing segment; Lace Helper = auto-generated helper",
            )
            obj.SegmentRole = [ROUTE_SEGMENT_ROLE, LACE_HELPER_ROLE]
            obj.SegmentRole = role
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
        if "HullCurve" not in obj.PropertiesList:
            obj.addProperty(
                "Part::PropertyPartShape",
                "HullCurve",
                "Segment",
                "Convex hull of the cable bundle at the segment start",
            )
            try:
                obj.setEditorMode("HullCurve", 2)
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
        if App.GuiUp:
            try:
                view = obj.ViewObject
                if getattr(view, "Proxy", None) is None:
                    view.Proxy = 1
                    view.Visibility = True
                view.signalChangeIcon()
            except Exception:
                pass

    def onChanged(self, obj, prop):
        if prop not in ("MaxCables", "SegmentType"):
            return
        for parent in obj.InList:
            if getattr(getattr(parent, "Proxy", None), "Type", None) in (
                "WireCable",
                "WireHarness",
            ):
                try:
                    parent.touch()
                except Exception:
                    pass

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


def ensure_segment_group(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    group = getattr(harness, "SegmentGroup", None)
    if group is None or not group.isValid() or group.Document is not document:
        name = "Segments"
        index = 1
        while document.getObject(name) is not None:
            name = f"Segments{index:03d}"
            index += 1
        group = document.addObject("App::DocumentObjectGroup", name)
        group.Label = "Segments"
        harness.SegmentGroup = group
    desired = [
        segment for segment in harness.Segments if not is_lace_helper(segment)
    ]
    current = list(group.Group)
    if current != desired:
        group.Group = desired
    return group


def ensure_helper_group(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    group = getattr(harness, "HelperGroup", None)
    if group is None or not group.isValid() or group.Document is not document:
        name = "LaceHelpers"
        index = 1
        while document.getObject(name) is not None:
            name = f"LaceHelpers{index:03d}"
            index += 1
        group = document.addObject("App::DocumentObjectGroup", name)
        group.Label = "Lace Helpers"
        harness.HelperGroup = group
    desired = [
        segment for segment in harness.Segments if is_lace_helper(segment)
    ]
    desired_set = set(desired)
    for child in list(group.Group):
        if is_bundle_segment(child) and child not in desired_set:
            group.removeObject(child)
    current_names = {child.Name for child in group.Group}
    for segment in desired:
        if segment.Name not in current_names:
            group.addObject(segment)
    return group


def create_wire_harness(document, label="Harness"):
    harness = document.addObject("App::FeaturePython", "WireHarness")
    harness.Label = label
    WireHarnessProxy(harness)
    ensure_segment_group(harness)
    ensure_helper_group(harness)
    if App.GuiUp:
        ViewProviderWireHarness(harness.ViewObject)
    return harness


def create_wire_bundle(document, label="Harness"):
    return create_wire_harness(document, label=label)


def create_bundle_segment(bundle, start, end, radius=10.0, segment_type="Closed"):
    document = bundle.Document
    segment = document.addObject("Part::FeaturePython", "BundleSegment")
    segment.Label = "Bundle Segment"
    WireBundleSegmentProxy(segment)
    segment.Start = start
    segment.End = end
    segment.Radius = radius
    segment.SegmentType = segment_type
    update_segment_dependencies(segment)
    if App.GuiUp:
        try:
            segment.ViewObject.ShapeColor = (0.33, 0.33, 0.36)
            segment.ViewObject.Transparency = 65
            segment.ViewObject.Visibility = True
            segment.ViewObject.signalChangeIcon()
        except Exception:
            pass
    segments = list(bundle.Segments)
    segments.append(segment)
    bundle.Segments = segments
    ensure_segment_group(bundle)
    ensure_helper_group(bundle)
    return segment


def remove_bundle_segment(bundle, segment):
    segments = [item for item in bundle.Segments if item is not segment]
    bundle.Segments = segments
    ensure_segment_group(bundle)
    ensure_helper_group(bundle)
    document = bundle.Document
    if document.getObject(segment.Name) is segment:
        document.removeObject(segment.Name)
