"""Persistent bundle and bundle-segment objects."""

import os

import FreeCAD as App
import FreeCADGui as Gui
import Part

from .WireFrames import segment_basis
from . import WireLayout, WireReducedDisplay, WireStrap
from .WireGeometry import circles_hull
from .WireRoute import (
    build_route_graph,
    layout_positions,
)
from .WireTypes import (
    BUNDLE_SEGMENT_TYPE,
    LACE_HELPER_ROLE,
    ROUTE_SEGMENT_ROLE,
    is_bundle_segment,
    is_harness,
    is_lace_helper,
    is_wire_cable,
)
ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")

def _bundle_hull_shape(start, side, normal, positions, diameters, samples=64):
    hull, _center = circles_hull(
        positions,
        diameters,
        samples=samples,
        margin=0.0,
        center_hull=False,
    )
    if not hull or len(hull) < 3:
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
        self._applied_display_mode = None
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
        if "StrapGroup" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "StrapGroup",
                "Harness",
                "Group containing the generated wrapping straps",
            )
        if "BundleHullObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "BundleHullObject",
                "Harness",
                "Display object for packed bundle hulls",
            )
        if "OverallHullObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "OverallHullObject",
                "Harness",
                "Display object for overall segment hulls",
            )
        if "CableCircleObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "CableCircleObject",
                "Harness",
                "Display object for cable cross-section circles",
            )
        if "ReducedBundleObject" not in properties:
            obj.addProperty(
                "App::PropertyLink",
                "ReducedBundleObject",
                "Harness",
                "Display object for reduced bundle geometry",
            )
        if "DisplayMode" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "DisplayMode",
                "Harness",
                "Harness display detail",
            )
        current_display = getattr(obj, "DisplayMode", "Full Detail")
        obj.DisplayMode = ["Full Detail", "Reduced Bundle"]
        obj.DisplayMode = (
            current_display
            if current_display in ("Full Detail", "Reduced Bundle")
            else "Full Detail"
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
        obj.Pattern = ["Circular", "Linear", "Packed", "Packed Bundles"]
        obj.Pattern = (
            current_pattern
            if current_pattern in ("Circular", "Linear", "Packed", "Packed Bundles")
            else "Circular"
        )
        if "WrappingType" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "WrappingType",
                "Harness",
                "Bundle wrapping type",
            )
        current_wrapping = getattr(obj, "WrappingType", "None")
        obj.WrappingType = ["None", "Straps"]
        obj.WrappingType = (
            current_wrapping
            if current_wrapping in ("None", "Straps")
            else "None"
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
        bundle_mode = pattern == "Packed Bundles"
        if pattern in ("Packed", "Packed Bundles"):
            result = WireLayout.packed_layout(
                obj,
                cables,
                gap,
                bundle_mode=bundle_mode,
            )
        else:
            result = WireLayout.simple_layout(obj, cables, gap, pattern)
        self._apply_layout_result(obj, result, bundle_mode)
        self._update_reduced_display(obj, cables)
        self._refresh_strap_objects(obj)

    def _apply_layout_result(self, obj, result, bundle_mode):
        for segment, radius in result.radii.items():
            self._set_segment_radius(segment, radius)
        for segment, segment_positions in result.positions_by_segment.items():
            positions = []
            diameters = []
            for cable in result.users.get(segment, []):
                position = segment_positions.get(cable)
                if position is None:
                    continue
                positions.append(position)
                diameters.append(max(0.0, cable.Diameter.Value))
            self._update_segment_section(segment, positions, diameters)
        for segment in result.segments:
            if result.users.get(segment):
                continue
            if "HullCurve" in segment.PropertiesList:
                try:
                    segment.HullCurve = Part.Shape()
                except Exception:
                    pass
        if bundle_mode:
            overall_hull_wires = []
            for segment in result.ordered:
                if is_lace_helper(segment):
                    continue
                if "HullCurve" not in segment.PropertiesList:
                    continue
                shape = segment.HullCurve
                if shape is None or shape.isNull():
                    continue
                overall_hull_wires.append(shape)
            circle_wires = []
            if getattr(obj, "DisplayMode", "Full Detail") == "Reduced Bundle":
                for segment, positions in result.positions_by_segment.items():
                    if is_lace_helper(segment):
                        continue
                    start_obj = segment.Start
                    end_obj = segment.End
                    if start_obj is None or end_obj is None:
                        continue
                    start = start_obj.getGlobalPlacement().Base
                    end = end_obj.getGlobalPlacement().Base
                    direction = end - start
                    length = direction.Length
                    if length < 1e-9:
                        continue
                    direction = direction / length
                    side, normal = segment_basis(segment)
                    for cable, (x, y) in positions.items():
                        radius = max(0.0, cable.Diameter.Value) / 2.0
                        if radius <= 1e-9:
                            continue
                        for base in (start, end):
                            center = base + side * x + normal * y
                            try:
                                circle_wires.append(
                                    Part.makeCircle(radius, center, direction)
                                )
                            except Exception:
                                pass
            self._set_hull_overlays(
                obj,
                result.bundle_hull_wires,
                overall_hull_wires,
                circle_wires,
            )
        else:
            self._set_hull_overlays(obj, [], [], [])
        self._packed_placements = result.placements
        obj.Layout = result.layout

    @staticmethod
    def _set_segment_radius(segment, radius):
        if abs(segment.Radius.Value - radius) <= 1e-6:
            return
        segment.Radius = radius
        try:
            segment.Proxy.execute(segment)
        except Exception:
            segment.touch()

    @staticmethod
    def _update_segment_section(segment, positions, diameters):
        if "HullCurve" not in segment.PropertiesList:
            try:
                WireBundleSegmentProxy._add_properties(segment)
            except Exception:
                pass
        try:
            start = segment.Start.getGlobalPlacement().Base
            side, normal = segment_basis(segment)
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


    @staticmethod
    def _set_hull_overlays(
        harness,
        bundle_wires,
        overall_wires,
        circle_wires=None,
    ):
        bundle_object, overall_object, circle_object = ensure_hull_objects(
            harness
        )

        def apply_shape(target, wires):
            if target is None:
                return
            try:
                target.Shape = (
                    Part.makeCompound(wires) if wires else Part.Shape()
                )
            except Exception:
                try:
                    target.Shape = Part.Shape()
                except Exception:
                    pass

        apply_shape(bundle_object, bundle_wires)
        apply_shape(overall_object, overall_wires)
        apply_shape(circle_object, circle_wires or [])

    def _update_reduced_display(self, obj, cables):
        mode = getattr(obj, "DisplayMode", "Full Detail")
        if getattr(obj, "Pattern", "Circular") != "Packed Bundles":
            mode = "Full Detail"
        reduced_object = ensure_reduced_bundle_object(obj)
        if mode == "Reduced Bundle":
            segments = [
                segment for segment in obj.Segments if is_bundle_segment(segment)
            ]
            (
                routes,
                directions,
                users,
                counts,
                adjacency,
                connections,
                ordered,
            ) = build_route_graph(cables, segments)
            positions_by_segment = layout_positions(
                obj,
                segments,
                users,
            )
            hulls = WireReducedDisplay.reduced_bundle_hulls(
                users,
                counts,
                adjacency,
                connections,
                positions_by_segment,
                ordered,
            )
            shapes = WireReducedDisplay.reduced_bundle_solids(hulls)
            shapes.extend(
                WireReducedDisplay.reduced_transition_shapes(
                    hulls,
                    counts,
                    connections,
                    positions_by_segment,
                    getattr(self, "_packed_placements", {}),
                    routes,
                    directions,
                )
            )
            if reduced_object is not None:
                try:
                    reduced_object.Shape = (
                        Part.makeCompound(shapes)
                        if shapes
                        else Part.Shape()
                    )
                except Exception:
                    pass
        elif reduced_object is not None:
            try:
                reduced_object.Shape = Part.Shape()
            except Exception:
                pass
        applied = getattr(self, "_applied_display_mode", None)
        if mode != applied or mode == "Reduced Bundle":
            self._apply_display_visibility(obj, mode)
        self._applied_display_mode = mode

    @staticmethod
    def _set_visibility(target, visible):
        if target is None:
            return
        try:
            view = target.ViewObject
            if bool(view.Visibility) != bool(visible):
                view.Visibility = bool(visible)
        except Exception:
            pass

    def _apply_display_visibility(self, obj, mode):
        if not App.GuiUp:
            return
        from .WireCable import (
            DIAGNOSTIC_HELPER_PROPERTIES,
            SUPPORT_OBJECT_PROPERTIES,
            find_container,
        )

        reduced = mode == "Reduced Bundle"
        cables = [item for item in obj.InList if is_wire_cable(item)]
        containers = set()
        for cable in cables:
            container = find_container(cable)
            if container is not None:
                containers.add(container)
            self._set_visibility(cable, not reduced)
            for property_name in ("StartTip", "EndTip"):
                tip = getattr(cable, property_name, None)
                if tip is not None:
                    self._set_visibility(tip, not reduced)
            for property_name in SUPPORT_OBJECT_PROPERTIES:
                helper = getattr(cable, property_name, None)
                if helper is None:
                    continue
                if property_name in DIAGNOSTIC_HELPER_PROPERTIES:
                    self._set_visibility(helper, False)
                elif reduced:
                    self._set_visibility(helper, False)
        for container in containers:
            self._set_visibility(container, not reduced)
        helper_group = getattr(obj, "HelperGroup", None)
        if helper_group is not None and reduced:
            self._set_visibility(helper_group, False)
        reduced_object = getattr(obj, "ReducedBundleObject", None)
        if reduced_object is not None:
            self._set_visibility(
                reduced_object,
                reduced and not reduced_object.Shape.isNull(),
            )
        if reduced:
            for property_name in ("BundleHullObject", "OverallHullObject"):
                overlay = getattr(obj, property_name, None)
                self._set_visibility(overlay, False)
        circle_object = getattr(obj, "CableCircleObject", None)
        if circle_object is not None:
            self._set_visibility(
                circle_object,
                reduced and not circle_object.Shape.isNull(),
            )

    @staticmethod
    def _refresh_strap_objects(obj):
        """Rebuild existing strap proxies after this pass has refreshed hulls."""
        group = getattr(obj, "StrapGroup", None)
        if group is None or not group.isValid():
            return
        for strap in list(group.Group):
            proxy = getattr(strap, "Proxy", None)
            if getattr(proxy, "Type", None) != WireStrap.WireStrapProxy.Type:
                continue
            try:
                proxy.execute(strap)
            except Exception:
                pass

    def onChanged(self, obj, prop):
        if prop == "WrappingType":
            ensure_strap_objects(obj)
            obj.touch()
        elif prop == "DisplayMode":
            self._applied_display_mode = None
            obj.touch()
        elif prop == "Pattern":
            if (
                getattr(obj, "Pattern", "Circular") != "Packed Bundles"
                and getattr(obj, "DisplayMode", "Full Detail")
                == "Reduced Bundle"
            ):
                obj.DisplayMode = "Full Detail"
            self._applied_display_mode = None
            obj.touch()

    def dumps(self):
        return self.Type

    def loads(self, state):
        self.Type = "WireHarness"

    def onDocumentRestored(self, obj):
        self._add_properties(obj)
        ensure_segment_group(obj)
        ensure_helper_group(obj)
        ensure_strap_group(obj)
        ensure_strap_objects(obj)
        ensure_hull_objects(obj)
        ensure_reduced_bundle_object(obj)
        if "Cables" in obj.PropertiesList:
            try:
                obj.removeProperty("Cables")
            except Exception:
                pass


WireBundleProxy = WireHarnessProxy


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
        for property_name in ("SegmentGroup", "HelperGroup", "StrapGroup"):
            group = getattr(obj, property_name, None)
            if group is not None and group.isValid() and group not in children:
                children.append(group)
        for property_name in (
            "BundleHullObject",
            "OverallHullObject",
            "CableCircleObject",
        ):
            hull_object = getattr(obj, property_name, None)
            if (
                hull_object is not None
                and hull_object.isValid()
                and hull_object not in children
            ):
                children.append(hull_object)
        reduced_object = getattr(obj, "ReducedBundleObject", None)
        if (
            reduced_object is not None
            and reduced_object.isValid()
            and reduced_object not in children
        ):
            children.append(reduced_object)
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
        strap_group = getattr(obj, "StrapGroup", None)
        strap_names = []
        if strap_group is not None and strap_group.isValid():
            strap_names = [
                child.Name for child in strap_group.Group if child.isValid()
            ]
        group_names = []
        for property_name in (
            "SegmentGroup",
            "HelperGroup",
            "StrapGroup",
            "BundleHullObject",
            "OverallHullObject",
            "CableCircleObject",
            "ReducedBundleObject",
        ):
            group = getattr(obj, property_name, None)
            if group is not None and group.isValid():
                group_names.append(group.Name)

        def cleanup():
            doc = App.getDocument(document_name)
            if doc is None:
                return
            for name in segment_names + strap_names:
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
        if App.GuiUp:
            try:
                group.ViewObject.Visibility = False
            except Exception:
                pass
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


def ensure_strap_group(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    group = getattr(harness, "StrapGroup", None)
    if group is None or not group.isValid() or group.Document is not document:
        name = "Straps"
        index = 1
        while document.getObject(name) is not None:
            name = f"Straps{index:03d}"
            index += 1
        group = document.addObject("App::DocumentObjectGroup", name)
        group.Label = "Straps"
        harness.StrapGroup = group
        if App.GuiUp:
            try:
                group.ViewObject.Visibility = False
            except Exception:
                pass
    return group


def _remove_strap_object(strap):
    if strap is None:
        return
    try:
        document = strap.Document
    except Exception:
        return
    if document is not None and document.getObject(strap.Name) is strap:
        try:
            document.removeObject(strap.Name)
        except Exception:
            pass


def ensure_strap_objects(harness):
    """Create/remove strap objects without touching the harness itself."""
    group = ensure_strap_group(harness)
    if group is None:
        return []
    if getattr(harness, "WrappingType", "None") != "Straps":
        for child in list(group.Group):
            _remove_strap_object(child)
        group.Group = []
        if App.GuiUp:
            try:
                group.ViewObject.Visibility = False
            except Exception:
                pass
        return []

    segments = [
        segment
        for segment in harness.Segments
        if is_bundle_segment(segment) and not is_lace_helper(segment)
    ]
    existing = {}
    for child in list(group.Group):
        segment = getattr(child, "Segment", None)
        if segment is not None:
            existing[segment] = child

    ordered = []
    for segment in segments:
        strap = existing.pop(segment, None)
        proxy = getattr(strap, "Proxy", None) if strap is not None else None
        needs_init = strap is not None and getattr(
            getattr(strap, "ViewObject", None), "Proxy", None
        ) is None
        if (
            strap is None
            or not strap.isValid()
            or strap.Document is not harness.Document
            or getattr(proxy, "Type", None) != WireStrap.WireStrapProxy.Type
        ):
            if strap is not None:
                _remove_strap_object(strap)
            strap = harness.Document.addObject(
                "Part::FeaturePython",
                "HarnessStrap",
            )
            WireStrap.WireStrapProxy(strap)
            needs_init = True
            if App.GuiUp:
                try:
                    strap.ViewObject.ShapeColor = (0.08, 0.28, 0.62)
                    strap.ViewObject.LineColor = (0.03, 0.12, 0.35)
                    strap.ViewObject.Transparency = 0
                except Exception:
                    pass
        strap.Segment = segment
        strap.Label = "Strap %s" % segment.Label
        if App.GuiUp and needs_init:
            try:
                view = strap.ViewObject
                if getattr(view, "Proxy", None) is None:
                    view.Proxy = 1
                if getattr(view, "DisplayMode", None) is None:
                    view.DisplayMode = "Flat Lines"
                view.Visibility = True
            except Exception:
                pass
        ordered.append(strap)

    for strap in existing.values():
        _remove_strap_object(strap)
    for child in list(group.Group):
        if child not in ordered:
            _remove_strap_object(child)
    group.Group = ordered
    if App.GuiUp:
        try:
            group.ViewObject.Visibility = bool(ordered)
        except Exception:
            pass
    return ordered


def ensure_hull_objects(harness):
    if harness is None or harness.Document is None:
        return None, None, None
    document = harness.Document

    def ensure(property_name, name, label, color, line_width=2):
        obj = getattr(harness, property_name, None)
        if obj is None or not obj.isValid() or obj.Document is not document:
            obj = document.addObject("Part::Feature", name)
            obj.Label = label
            setattr(harness, property_name, obj)
            if App.GuiUp:
                try:
                    obj.ViewObject.Visibility = False
                except Exception:
                    pass
        if App.GuiUp:
            try:
                obj.ViewObject.Selectable = False
                obj.ViewObject.LineColor = color
                obj.ViewObject.LineWidth = line_width
                obj.ViewObject.ShapeColor = color
            except Exception:
                pass
        return obj

    bundle_object = ensure(
        "BundleHullObject",
        "BundleHulls",
        "Bundle Hulls",
        (0.1, 0.85, 0.2),
    )
    overall_object = ensure(
        "OverallHullObject",
        "OverallHull",
        "Overall Hull",
        (1.0, 0.55, 0.0),
    )
    circle_object = ensure(
        "CableCircleObject",
        "CableCircles",
        "Cable Circles",
        (0.1, 0.65, 1.0),
        1.5,
    )
    return bundle_object, overall_object, circle_object


def ensure_reduced_bundle_object(harness):
    if harness is None or harness.Document is None:
        return None
    document = harness.Document
    obj = getattr(harness, "ReducedBundleObject", None)
    if obj is not None and obj.isValid() and obj.Document is document:
        return obj
    obj = document.addObject("Part::Feature", "ReducedBundles")
    obj.Label = "Reduced Bundles"
    harness.ReducedBundleObject = obj
    if App.GuiUp:
        try:
            obj.ViewObject.Selectable = False
            obj.ViewObject.ShapeColor = (0.5, 0.55, 0.62)
            obj.ViewObject.LineColor = (0.35, 0.4, 0.48)
            obj.ViewObject.Transparency = 0
            obj.ViewObject.Visibility = False
        except Exception:
            pass
    return obj


def create_wire_harness(document, label="Harness"):
    harness = document.addObject("App::FeaturePython", "WireHarness")
    harness.Label = label
    WireHarnessProxy(harness)
    ensure_segment_group(harness)
    ensure_helper_group(harness)
    ensure_strap_group(harness)
    ensure_hull_objects(harness)
    ensure_reduced_bundle_object(harness)
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
