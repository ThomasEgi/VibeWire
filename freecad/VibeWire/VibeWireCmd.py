"""Commands for VibeWire."""

import os

import FreeCADGui as Gui
from PySide import QtGui

from freecad.VibeWire.WireBundleTaskPanel import WireBundleTaskPanel
from freecad.VibeWire.WireTaskPanel import WireTaskPanel

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")


class CreateWireCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Create Wire",
            "ToolTip": "Create a bundle-segment cable route",
        }

    def Activated(self):
        try:
            Gui.Control.showDialog(WireTaskPanel())
        except Exception as error:
            QtGui.QMessageBox.critical(None, "VibeWire", str(error))

    def IsActive(self):
        return True


Gui.addCommand("VibeWire_CreateWire", CreateWireCommand())


class DefineHarnessCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Define Harness",
            "ToolTip": "Define harness bundle segments and cable arrangement",
        }

    def Activated(self):
        try:
            Gui.Control.showDialog(WireBundleTaskPanel())
        except Exception as error:
            QtGui.QMessageBox.critical(None, "VibeWire", str(error))

    def IsActive(self):
        return True


Gui.addCommand("VibeWire_DefineHarness", DefineHarnessCommand())


def _selected_one():
    selection = Gui.Selection.getSelection()
    return selection[0] if len(selection) == 1 else None


def _type(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None)


def _selected_of_type(kind):
    obj = _selected_one()
    return obj if obj is not None and _type(obj) == kind else None


def _cable_for_tip(tip):
    for parent in getattr(tip, "InList", []):
        if _type(parent) == "WireCable":
            return parent
    return None


def _harness_for_segment(segment):
    for parent in getattr(segment, "InList", []):
        if _type(parent) == "WireHarness":
            return parent
    return None


def _open_tool(obj):
    if obj is None:
        return
    try:
        Gui.ActiveDocument.setEdit(obj, 0)
    except Exception as error:
        QtGui.QMessageBox.critical(None, "VibeWire", str(error))


class EditWireCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Edit Wire",
            "ToolTip": "Open the wire tool for the selected cable",
        }

    def Activated(self):
        _open_tool(_selected_of_type("WireCable"))

    def IsActive(self):
        return _selected_of_type("WireCable") is not None


class EditStartTipCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Edit Start Tip",
            "ToolTip": "Open the tool for the start tip of the selected cable",
        }

    def Activated(self):
        cable = _selected_of_type("WireCable")
        _open_tool(getattr(cable, "StartTip", None))

    def IsActive(self):
        cable = _selected_of_type("WireCable")
        return cable is not None and getattr(cable, "StartTip", None) is not None


class EditEndTipCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Edit End Tip",
            "ToolTip": "Open the tool for the end tip of the selected cable",
        }

    def Activated(self):
        cable = _selected_of_type("WireCable")
        _open_tool(getattr(cable, "EndTip", None))

    def IsActive(self):
        cable = _selected_of_type("WireCable")
        return cable is not None and getattr(cable, "EndTip", None) is not None


class EditTipCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Edit Tip",
            "ToolTip": "Open the tool for the selected cable tip",
        }

    def Activated(self):
        _open_tool(_selected_of_type("WireTip"))

    def IsActive(self):
        return _selected_of_type("WireTip") is not None


class EditHarnessCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Edit Harness",
            "ToolTip": "Open the harness tool",
        }

    def Activated(self):
        harness = _selected_of_type("WireHarness")
        if harness is None:
            segment = _selected_of_type("WireBundleSegment")
            harness = _harness_for_segment(segment) if segment is not None else None
        _open_tool(harness)

    def IsActive(self):
        if _selected_of_type("WireHarness") is not None:
            return True
        segment = _selected_of_type("WireBundleSegment")
        return segment is not None and _harness_for_segment(segment) is not None


class MoveSegmentStartCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Move Start Point",
            "ToolTip": "Select the bundle segment start node and transform it",
        }

    def Activated(self):
        segment = _selected_of_type("WireBundleSegment")
        point = getattr(segment, "Start", None) if segment is not None else None
        _move_point(point)

    def IsActive(self):
        segment = _selected_of_type("WireBundleSegment")
        return segment is not None and getattr(segment, "Start", None) is not None


class MoveSegmentEndCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Move End Point",
            "ToolTip": "Select the bundle segment end node and transform it",
        }

    def Activated(self):
        segment = _selected_of_type("WireBundleSegment")
        point = getattr(segment, "End", None) if segment is not None else None
        _move_point(point)

    def IsActive(self):
        segment = _selected_of_type("WireBundleSegment")
        return segment is not None and getattr(segment, "End", None) is not None


def _move_point(point):
    if point is None:
        return
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(point)
    if Gui.isCommandActive("Std_TransformManip"):
        Gui.runCommand("Std_TransformManip", 0)
        try:
            if Gui.ActiveDocument.getInEdit() is not None:
                return
        except Exception:
            pass
    Gui.runCommand("Std_Placement", 0)


Gui.addCommand("VibeWire_EditWire", EditWireCommand())
Gui.addCommand("VibeWire_EditStartTip", EditStartTipCommand())
Gui.addCommand("VibeWire_EditEndTip", EditEndTipCommand())
Gui.addCommand("VibeWire_EditTip", EditTipCommand())
Gui.addCommand("VibeWire_EditHarness", EditHarnessCommand())
Gui.addCommand("VibeWire_MoveSegmentStart", MoveSegmentStartCommand())
Gui.addCommand("VibeWire_MoveSegmentEnd", MoveSegmentEndCommand())
