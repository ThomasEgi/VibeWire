"""Workbench definition for Wire Plugin."""
import sys
import FreeCADGui

print("=== WIREPLUGIN WORKBENCH MODULE LOADED ===")

# Define the workbench class
class WirePluginWorkbench(FreeCADGui.Workbench):
    MenuText = "WirePlugin"
    ToolTip = "Wire and Cable Routing"
    Icon = ""

    def __init__(self):
        self._initialized = False
        print("  WirePluginWorkbench.__init__() called")

    def Initialize(self):
        print("  WirePluginWorkbench.Initialize() called")
        try:
            print("  Importing WirePluginCmd...")
            import WirePlugin.WirePluginCmd
            print("  ✓ WirePluginCmd imported")
        except Exception as e:
            print(f"  ✗ Failed to import WirePluginCmd: {e}")
            import traceback
            traceback.print_exc()

    def Activated(self):
        pass

    def Deactivated(self):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"

# Get existing workbench names using FreeCADGui.listWorkbenches() - getWorkbench() requires a name arg
wb_names = FreeCADGui.listWorkbenches().keys()
print(f"About to register workbench. Workbench names before: {list(wb_names)}")

# Create and register the workbench
wb = WirePluginWorkbench()
wb.Initialize()

print(f"About to call addWorkbench()")
print(f"Workbench object: {wb}")
print(f"Workbench class name: {wb.GetClassName()}")

# DEBUG: Print workbench registry using FreeCADGui.listWorkbenches()
wb_names = FreeCADGui.listWorkbenches()
print(f"Workbenches registered after addWorkbench(): {wb_names}")

FreeCADGui.addWorkbench(wb)

# DEBUG: Print workbench registry again
wb_names = FreeCADGui.listWorkbenches()
print(f"Workbenches after addWorkbench(): {wb_names}")

# Check if our workbench is in the list
found = False
for name in wb_names:
    wb_obj = FreeCADGui.getWorkbench(name)
    if wb_obj and "WirePlugin" in str(wb_obj):
        print(f"✓ Found WirePlugin workbench: {name}")
        found = True

if not found:
    print("✗ WirePlugin workbench NOT found in registry!")

# Add the workbench to FreeCAD's workbench registry ONLY if it doesn't exist
# FreeCADGui.getWorkbench() returns None if not found, or raises KeyError if exists
try:
    wb_existing = FreeCADGui.getWorkbench("WirePluginWorkbench")
    print(f"  ⚠ WirePluginWorkbench already exists: {wb_existing}")
except KeyError:
    print(f"  ✓ WirePluginWorkbench not found, adding it...")
    FreeCADGui.addWorkbench(wb)
    print(f"  ✓ WirePluginWorkbench added successfully")

# Final check using FreeCADGui.listWorkbenches()
wb_names = FreeCADGui.listWorkbenches()
print(f"=== FINAL WORKBENCH REGISTRY ===")
print(f"Total workbenches: {len(wb_names)}")
print(f"Workbench names: {list(wb_names.keys())}")

# Print each workbench's MenuText
for name in wb_names:
    wb_obj = FreeCADGui.getWorkbench(name)
    if wb_obj and hasattr(wb_obj, 'MenuText'):
        print(f"  {name}: {wb_obj.MenuText}")

print("=== WIREPLUGIN WORKBENCH MODULE END ===")
