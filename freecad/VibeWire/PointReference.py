"""Shared helpers for picking point references in task panels."""

import FreeCAD as App
from PySide import QtCore, QtGui

from .WireBundle import is_bundle_segment

POINT_REFERENCE_TYPES = (
    "Part::LocalCoordinateSystem",
    "PartDesign::CoordinateSystem",
    "App::Origin",
    "App::Part",
    "PartDesign::Body",
)


class PointReferenceGate:
    """Selection gate for point references, optionally bundle segments."""

    def __init__(self, allow_bundle_segments=False, allow_point_references=True):
        self.allow_bundle_segments = allow_bundle_segments
        self.allow_point_references = allow_point_references

    def allow(self, document, obj, subelement):
        if isinstance(document, str):
            document = App.getDocument(document)
        if document is None:
            return False
        if isinstance(obj, str):
            obj = document.getObject(obj)
        if obj is None:
            return False
        if self.allow_point_references and obj.TypeId in POINT_REFERENCE_TYPES:
            return True
        return self.allow_bundle_segments and is_bundle_segment(obj)


class PickObserver:
    """Selection observer used while waiting for a point reference pick."""

    def __init__(self, callback):
        self._callback = callback

    def addSelection(self, doc, obj, sub, pnt=None):
        self._callback(doc, obj, sub)

    def removeSelection(self, *args):
        pass

    def setSelection(self, *args):
        pass

    def clearSelection(self, *args):
        pass


class ClickableLabel(QtGui.QLabel):
    """Label that emits clicked when pressed."""

    clicked = QtCore.Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
