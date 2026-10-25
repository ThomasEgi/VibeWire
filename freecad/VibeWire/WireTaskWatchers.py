"""Contextual task-panel tools for VibeWire selections."""

import os

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import WireSelection

ICON = os.path.join(os.path.dirname(__file__), "Resources", "Icons", "wire_icon.png")


def _selection():
    return Gui.Selection.getSelection()


def _kind(obj):
    return getattr(getattr(obj, "Proxy", None), "Type", None)


def _single(kind):
    selection = _selection()
    if len(selection) != 1:
        return False
    return _kind(selection[0]) == kind


class HoverToolButton(QtWidgets.QToolButton):
    def __init__(self, text, command, enter=None, tooltip=None):
        super().__init__()
        self._command = command
        self._enter = enter
        self.setText(text)
        self.setIcon(QtGui.QIcon(ICON))
        self.setIconSize(QtCore.QSize(16, 16))
        self.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.setAutoRaise(True)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        if tooltip:
            self.setToolTip(tooltip)
        self.clicked.connect(self._clicked)

    def enterEvent(self, event):
        try:
            if self._enter is not None:
                self._enter()
            else:
                WireSelection.clear_hover_preview()
        except Exception:
            pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        try:
            WireSelection.clear_hover_preview()
        except Exception:
            pass
        super().leaveEvent(event)

    def _clicked(self):
        try:
            WireSelection.clear_hover_preview()
        except Exception:
            pass
        if self._command:
            Gui.runCommand(self._command, 0)


def _button_container(buttons):
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    for button in buttons:
        layout.addWidget(button)
    return [widget]


class WireCreateWatcher:
    def __init__(self):
        self.commands = [
            "VibeWire_CreateWire",
            "VibeWire_DefineHarness",
        ]
        self.title = "Create"

    def shouldShow(self):
        return App.ActiveDocument is not None and not _selection()


class WireCableWatcher:
    def __init__(self):
        self.title = "Wire Tools"
        self.widgets = _button_container(
            [
                HoverToolButton(
                    "Edit Wire",
                    "VibeWire_EditWire",
                    WireSelection.preview_selected_cable,
                    "Preview and edit the selected cable",
                ),
                HoverToolButton(
                    "Edit Start Tip",
                    "VibeWire_EditStartTip",
                    WireSelection.preview_start_tip,
                    "Preview and edit the start tip",
                ),
                HoverToolButton(
                    "Edit End Tip",
                    "VibeWire_EditEndTip",
                    WireSelection.preview_end_tip,
                    "Preview and edit the end tip",
                ),
            ]
        )

    def shouldShow(self):
        return _single("WireCable")


class WireTipWatcher:
    def __init__(self):
        self.title = "Tip Tools"
        self.widgets = _button_container(
            [
                HoverToolButton(
                    "Edit Tip",
                    "VibeWire_EditTip",
                    WireSelection.preview_selected_tip,
                    "Preview and edit the selected tip",
                )
            ]
        )

    def shouldShow(self):
        return _single("WireTip")


class WireBundleWatcher:
    def __init__(self):
        self.title = "Bundle Tools"
        self.widgets = _button_container(
            [
                HoverToolButton(
                    "Edit Harness",
                    "VibeWire_EditHarness",
                    tooltip="Open the harness tool",
                ),
                HoverToolButton(
                    "Move Start Point",
                    "VibeWire_MoveSegmentStart",
                    WireSelection.preview_segment_start,
                    "Preview and move the bundle segment start node",
                ),
                HoverToolButton(
                    "Move End Point",
                    "VibeWire_MoveSegmentEnd",
                    WireSelection.preview_segment_end,
                    "Preview and move the bundle segment end node",
                ),
            ]
        )

    def shouldShow(self):
        return _single("WireBundleSegment")


class WireHarnessWatcher:
    def __init__(self):
        self.commands = ["VibeWire_EditHarness"]
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
    try:
        WireSelection.clear_hover_preview()
    except Exception:
        pass
    Gui.Control.clearTaskWatcher()
