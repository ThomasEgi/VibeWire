"""GUI initialization for Wire Plugin."""
import FreeCADGui as Gui
from PySide import QtGui

class WirePluginWorkbench(Gui.Workbench):
    MenuText = "WirePlugin"
    ToolTip = "Wire and Cable Routing"
    Icon = ""

    def Initialize(self):
        import WirePluginCommands
        self.appendToolbar("Wire Tools", ["WirePlugin_RunTest"])
        self.appendMenu("WirePlugin", ["WirePlugin_RunTest"])

    def Activated(self):
        pass

    def Deactivated(self):
        pass

Gui.addWorkbench(WirePluginWorkbench())
