"""Workbench definition for Wire Plugin."""
import FreeCADGui

# Define the workbench class
class WirePluginWorkbench(FreeCADGui.Workbench):
    MenuText = "WirePlugin"
    ToolTip = "Wire and Cable Routing"
    Icon = ""

    def __init__(self):
        self._initialized = False

    def Initialize(self):
        import WirePluginCommands

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"

# AUTO-REGISTER THE WORKBENCH (key difference from Detessellate)
wb = WirePluginWorkbench()
wb.Initialize()
FreeCADGui.addWorkbench(wb)

# Add the workbench to FreeCAD's workbench registry
FreeCADGui.AddWorkbench("WirePlugin")
