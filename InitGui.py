"""Wire Plugin InitGui."""
import FreeCADGui as Gui
import os

class WirePluginWorkbench(Gui.Workbench):
    MenuText = "WirePlugin"
    ToolTip = "Wire and Cable Routing"

    def Initialize(self):
        import sys
        plugin_dir = os.path.dirname(__file__)
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)
        import WirePluginCommands
        self.appendToolbar("Wire Tools", ["WirePlugin_CreateCable", "WirePlugin_RunTest"])
        self.appendMenu("WirePlugin", ["WirePlugin_CreateCable", "WirePlugin_RunTest"])

    def Activated(self):
        pass

    def Deactivated(self):
        pass

Gui.addWorkbench(WirePluginWorkbench())
