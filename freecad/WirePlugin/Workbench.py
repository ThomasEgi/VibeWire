"""Workbench definition for Wire Plugin."""
import os

import FreeCADGui

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
        bundle_cmds = ["WirePlugin_DefineBundle"]
        self.appendToolbar("Wire", wire_cmds)
        self.appendToolbar("Bundle", bundle_cmds)
        self.appendMenu("WirePlugin", wire_cmds + bundle_cmds)
        self._initialized = True

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(WirePluginWorkbench())
