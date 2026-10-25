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
            obj.TipType = ["Length offset", "Stripped wire", "Ferrule"]
            obj.TipType = "Length offset"
        else:
            current = getattr(obj, "TipType", "Length offset")
            options = ["Length offset", "Stripped wire", "Ferrule"]
            try:
                available = list(obj.getEnumerationsOfProperty("TipType"))
            except Exception:
                available = []
            if available != options:
                obj.TipType = options
                try:
                    obj.TipType = current if current in options else "Length offset"
                except Exception:
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
        if "FerruleType" not in properties:
            obj.addProperty(
                "App::PropertyString",
                "FerruleType",
                "Ferrule",
                "Selected ferrule geometry type",
            )
            obj.FerruleType = "tube"
        if "FerruleVariant" not in properties:
            obj.addProperty(
                "App::PropertyInteger",
                "FerruleVariant",
                "Ferrule",
                "Selected variant index for the ferrule type",
            )
            obj.FerruleVariant = 0
        if "FerruleColorSystem" not in properties:
            obj.addProperty(
                "App::PropertyString",
                "FerruleColorSystem",
                "Ferrule",
                "Color code system for the ferrule sleeve",
            )
            obj.FerruleColorSystem = "DIN"
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
        self._sync_geometry_visibility(vobj)

    def getIcon(self):
        return ICON

    def attach(self, vobj):
        self.Object = vobj.Object
        self._setup_display_mode(vobj)
        self._sync_visibility_mode(vobj)
        self._sync_geometry_visibility(vobj)
        try:
            vobj.signalChangeIcon()
        except Exception:
            pass

    @staticmethod
    def _mode_switch(vobj):
        try:
            from pivy import coin

            root = vobj.RootNode
            for i in range(root.getNumChildren()):
                node = root.getChild(i)
                if isinstance(node, coin.SoSwitch):
                    return node
        except Exception:
            pass
        return None

    def _setup_display_mode(self, vobj):
        switch = self._mode_switch(vobj)
        if switch is not None:
            try:
                if switch.getNumChildren() == 0:
                    from pivy import coin

                    self._coin_node = coin.SoSeparator()
                    vobj.addDisplayMode(self._coin_node, "Default")
            except Exception:
                self._coin_node = None
        try:
            vobj.DefaultMode = 0
        except Exception:
            pass

    def getDisplayModes(self, vobj):
        return ["Default"]

    def getDefaultDisplayMode(self):
        return "Default"

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            self._sync_visibility_mode(vobj)
            self._sync_geometry_visibility(vobj)
            try:
                vobj.signalChangeIcon()
            except Exception:
                pass

    @staticmethod
    def _sync_visibility_mode(vobj):
        switch = ViewProviderWireTip._mode_switch(vobj)
        if switch is None:
            return
        try:
            switch.whichChild = 0 if vobj.Visibility else -1
        except Exception:
            pass

    @staticmethod
    def _sync_geometry_visibility(vobj):
        tip = vobj.Object
        cable = None
        for parent in tip.InList:
            if getattr(getattr(parent, "Proxy", None), "Type", None) == "WireCable":
                cable = parent
                break
        if cable is None:
            return
        if getattr(cable, "StartTip", None) is tip:
            names = (
                "StartCoreObject",
                "StartFerruleMetal",
                "StartFerruleSleeve",
            )
        else:
            names = (
                "EndCoreObject",
                "EndFerruleMetal",
                "EndFerruleSleeve",
            )
        visible = bool(vobj.Visibility)
        for name in names:
            helper = getattr(cable, name, None)
            if helper is not None and helper.isValid():
                try:
                    helper.ViewObject.Visibility = visible
                except Exception:
                    pass

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
