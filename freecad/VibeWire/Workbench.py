"""Workbench definition for VibeWire."""
import os

import FreeCADGui

from . import WireSelection, WireTaskWatchers

WireSelection.install()

ICON_DIR = os.path.join(os.path.dirname(__file__), "Resources", "Icons")


class VibeWireWorkbench(FreeCADGui.Workbench):
    """VibeWire workbench for cable and harness routing operations."""

    MenuText = "VibeWire"
    ToolTip = "A cable/wireharness plugin for FreeCAD"
    Icon = os.path.join(ICON_DIR, "wire_icon.png")

    def __init__(self):
        self._initialized = False

    def Initialize(self):
        if self._initialized:
            return

        import freecad.VibeWire.VibeWireCmd  # noqa: F401

        wire_cmds = ["VibeWire_CreateWire"]
        bundle_cmds = ["VibeWire_DefineHarness"]
        self.appendToolbar("Wire", wire_cmds)
        self.appendToolbar("Harness", bundle_cmds)
        self.appendMenu("VibeWire", wire_cmds + bundle_cmds)
        self._initialized = True

    def ContextMenu(self, recipient):
        if recipient not in ("View", "Tree"):
            return
        selection = FreeCADGui.Selection.getSelection()
        if len(selection) != 1:
            return
        kind = getattr(getattr(selection[0], "Proxy", None), "Type", None)
        commands = {
            "WireCable": [
                "VibeWire_EditWire",
                "VibeWire_EditStartTip",
                "VibeWire_EditEndTip",
            ],
            "WireTip": ["VibeWire_EditTip"],
            "WireBundleSegment": [
                "VibeWire_EditHarness",
                "VibeWire_MoveSegmentStart",
                "VibeWire_MoveSegmentEnd",
            ],
            "WireHarness": ["VibeWire_EditHarness"],
        }.get(kind)
        if commands:
            self.appendContextMenu("", "Separator")
            self.appendContextMenu("", commands)

    def Activated(self):
        WireTaskWatchers.install()

    def Deactivated(self):
        WireTaskWatchers.uninstall()

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(VibeWireWorkbench())
