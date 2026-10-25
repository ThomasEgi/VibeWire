"""Contextual task-panel tools for WirePlugin selections."""

import FreeCAD as App
import FreeCADGui as Gui


def _selection():
    return Gui.Selection.getSelection()


def _kind(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None)


def _single(kind):
    selection = _selection()
    if len(selection) != 1:
        return False
    return _kind(selection[0]) == kind


class WireCreateWatcher:
    def __init__(self):
        self.commands = [
            "WirePlugin_CreateWire",
            "WirePlugin_DefineHarness",
        ]
        self.title = "Create"

    def shouldShow(self):
        return App.ActiveDocument is not None and not _selection()


class WireCableWatcher:
    def __init__(self):
        self.commands = [
            "WirePlugin_EditWire",
            "WirePlugin_EditStartTip",
            "WirePlugin_EditEndTip",
        ]
        self.title = "Wire Tools"

    def shouldShow(self):
        return _single("WireCable")


class WireTipWatcher:
    def __init__(self):
        self.commands = ["WirePlugin_EditTip"]
        self.title = "Tip Tools"

    def shouldShow(self):
        return _single("WireTip")


class WireBundleWatcher:
    def __init__(self):
        self.commands = [
            "WirePlugin_EditHarness",
            "WirePlugin_MoveSegmentStart",
            "WirePlugin_MoveSegmentEnd",
        ]
        self.title = "Bundle Tools"

    def shouldShow(self):
        return _single("WireBundleSegment")


class WireHarnessWatcher:
    def __init__(self):
        self.commands = ["WirePlugin_EditHarness"]
        self.title = "Harness Tools"

    def shouldShow(self):
        return _single("WireHarness")


def install():
    Gui.Control.clearTaskWatcher()
    Gui.Control.addTaskWatcher(
        [
            WireCreateWatcher(),
            WireCableWatcher(),
            WireTipWatcher(),
            WireBundleWatcher(),
            WireHarnessWatcher(),
        ]
    )


def uninstall():
    Gui.Control.clearTaskWatcher()
