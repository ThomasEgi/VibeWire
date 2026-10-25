"""Workbench definition for Wire Plugin."""
import os

import FreeCADGui

from . import WireSelection, WireTaskWatchers

WireSelection.install()

ICON_DIR = os.path.join(os.path.dirname(__file__), "Resources", "Icons")


class WirePluginWorkbench(FreeCADGui.Workbench):
    """WirePlugin workbench for cable and bundle routing operations."""

    MenuText = "WirePlugin"
    ToolTip = "Wire and Cable Routing"
    Icon = os.path.join(ICON_DIR, "wire_icon.png")

    def __init__(self):
        self._initialized = False

    def Initialize(self):
        if self._initialized:
            return

        import freecad.WirePlugin.WirePluginCmd  # noqa: F401

        wire_cmds = ["WirePlugin_CreateWire"]
        bundle_cmds = ["WirePlugin_DefineHarness"]
        self.appendToolbar("Wire", wire_cmds)
        self.appendToolbar("Harness", bundle_cmds)
        self.appendMenu("WirePlugin", wire_cmds + bundle_cmds)
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
                "WirePlugin_EditWire",
                "WirePlugin_EditStartTip",
                "WirePlugin_EditEndTip",
            ],
            "WireTip": ["WirePlugin_EditTip"],
            "WireBundleSegment": [
                "WirePlugin_EditHarness",
                "WirePlugin_MoveSegmentStart",
                "WirePlugin_MoveSegmentEnd",
            ],
            "WireHarness": ["WirePlugin_EditHarness"],
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


FreeCADGui.addWorkbench(WirePluginWorkbench())
