"""Cable end tip settings object."""

import os

import FreeCAD as App
import FreeCADGui as Gui

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")
TIP_OFFSET_MARGIN = 0.01


class WireTipProxy:
    """Settings object for one cable end (connector/tip)."""

    def __init__(self, obj):
        obj.Proxy = self
        self.Type = "WireTip"
        self._add_properties(obj)

    @staticmethod
    def _add_properties(obj):
        properties = obj.PropertiesList
        if "TipType" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "TipType",
                "Tip",
                "Cable end treatment",
            )
            obj.TipType = ["Length offset", "Stripped wire"]
            obj.TipType = "Length offset"
        if "LengthOffset" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "LengthOffset",
                "Tip",
                "Visual cable shortening at this end",
            )
            obj.LengthOffset = 0.0
        if "StrippedLength" not in properties:
            obj.addProperty(
                "App::PropertyLength",
                "StrippedLength",
                "Tip",
                "Length of exposed conductor at this end",
            )
            obj.StrippedLength = 0.0
        if "End" not in properties:
            obj.addProperty(
                "App::PropertyEnumeration",
                "End",
                "Tip",
                "Cable end represented by this tip",
            )
            obj.End = ["Start", "End"]
            obj.End = "Start"

    def execute(self, obj):
        pass

    def dumps(self):
        return self.Type

    def loads(self, state):
        if state:
            self.Type = state

    def onDocumentRestored(self, obj):
        self._add_properties(obj)


class ViewProviderWireTip:
    """View provider that opens the tip settings editor."""

    def __init__(self, vobj):
        vobj.Proxy = self
        self.Object = vobj.Object

    def getIcon(self):
        return ICON

    def attach(self, vobj):
        self.Object = vobj.Object

    def setEdit(self, vobj, mode):
        if mode != 0:
            return False
        from .WireTipTaskPanel import WireTipTaskPanel

        Gui.Control.showDialog(WireTipTaskPanel(tip=vobj.Object))
        return True

    def unsetEdit(self, vobj, mode):
        if mode != 0:
            return False
        Gui.Control.closeDialog()
        return True

    def doubleClicked(self, vobj):
        Gui.ActiveDocument.setEdit(vobj.Object, 0)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def create_wire_tip(document, end, name="WireTip", label=None):
    tip = document.addObject("App::FeaturePython", name)
    tip.Label = label or f"{end} Tip"
    WireTipProxy(tip)
    tip.End = end
    if App.GuiUp:
        ViewProviderWireTip(tip.ViewObject)
    return tip
