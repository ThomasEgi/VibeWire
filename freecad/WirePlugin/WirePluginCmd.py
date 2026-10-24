"""Commands for Wire Plugin."""

import os

import FreeCADGui as Gui
from PySide import QtGui

from freecad.WirePlugin.WireTaskPanel import WireTaskPanel

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")


class CreateWireCommand:
    def GetResources(self):
        return {
            "Pixmap": ICON,
            "MenuText": "Create Wire",
            "ToolTip": "Create a wire from coordinate system start/end points",
        }

    def Activated(self):
        try:
            Gui.Control.showDialog(WireTaskPanel())
        except Exception as error:
            QtGui.QMessageBox.critical(None, "WirePlugin", str(error))

    def IsActive(self):
        return True


Gui.addCommand("WirePlugin_CreateWire", CreateWireCommand())
