"""Script to load WirePlugin workbench in FreeCAD."""
import sys
sys.path.insert(0, "/home/mx/.local/share/FreeCAD/v1-1/Mod/WirePlugin")

# Import and initialize the workbench
from WirePlugin.Workbench import WirePluginWorkbench
wb = WirePluginWorkbench()
wb.Initialize()
import FreeCADGui as Gui
Gui.addWorkbench(wb)
