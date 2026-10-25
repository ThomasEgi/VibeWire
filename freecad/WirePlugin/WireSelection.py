"""Selection remapping for cable helper geometry."""

import FreeCAD as App
import FreeCADGui as Gui

HELPER_TIP_PAIRS = (
    ("StartCoreObject", "StartTip"),
    ("EndCoreObject", "EndTip"),
    ("StartFerruleMetal", "StartTip"),
    ("EndFerruleMetal", "EndTip"),
    ("StartFerruleSleeve", "StartTip"),
    ("EndFerruleSleeve", "EndTip"),
)


class HelperSelectionObserver:
    """Select the owning tip and highlight the clicked helper geometry."""

    def __init__(self):
        self._busy = False
        self._highlighted = {}

    def addSelection(self, doc_name, obj_name, sub_name, mouse_pos=None):
        if self._busy:
            return
        if isinstance(doc_name, str):
            document = App.getDocument(doc_name)
        else:
            document = doc_name
        if document is None:
            return
        selected = (
            document.getObject(obj_name)
            if isinstance(obj_name, str)
            else obj_name
        )
        target = _selection_target(selected)
        if target is None or target is selected:
            return
        self._busy = True
        try:
            Gui.Selection.removeSelection(selected)
            Gui.Selection.addSelection(target)
            self._schedule_highlight(selected, target)
        finally:
            self._busy = False

    def removeSelection(self, *args):
        self._clear_highlight()

    def setSelection(self, *args):
        self._clear_highlight()

    def clearSelection(self, *args):
        self._clear_highlight()

    def _schedule_highlight(self, obj, target):
        def apply():
            try:
                if target not in Gui.Selection.getSelection():
                    return
                if not obj.isValid():
                    return
                self._highlight(obj)
            except Exception:
                pass

        try:
            from PySide import QtCore
        except ImportError:
            from PySide6 import QtCore
        QtCore.QTimer.singleShot(30, apply)

    def _highlight(self, obj):
        view = getattr(obj, "ViewObject", None)
        if view is None:
            return
        name = obj.Name
        if name not in self._highlighted:
            try:
                original = tuple(view.ShapeAppearance)
            except Exception:
                original = None
            if original:
                self._highlighted[name] = (obj, original)
        try:
            material = App.Material()
            material.DiffuseColor = (0.0, 1.0, 0.0, 1.0)
            material.AmbientColor = (0.0, 0.5, 0.0, 1.0)
            material.Transparency = 0
            count = len(view.ShapeAppearance) or 1
            view.ShapeAppearance = [material] * count
        except Exception:
            pass

    def _clear_highlight(self):
        for obj, original in list(self._highlighted.values()):
            try:
                obj.ViewObject.ShapeAppearance = original
            except Exception:
                pass
        self._highlighted.clear()


def _selection_target(obj):
    if obj is None:
        return None
    for parent in obj.InList:
        if getattr(getattr(parent, "Proxy", None), "Type", None) != "WireCable":
            continue
        for helper_name, tip_name in HELPER_TIP_PAIRS:
            if getattr(parent, helper_name, None) is obj:
                tip = getattr(parent, tip_name, None)
                if tip is not None and tip.isValid():
                    return tip
        if obj in (
            getattr(parent, "PathObject", None),
            getattr(parent, "BadRadiusObject", None),
            getattr(parent, "BadLengthObject", None),
        ):
            return parent
    return None


class HelperTreeObserver:
    """Hide cable helper objects when a document is restored or activated."""

    def slotFinishRestoreDocument(self, document):
        _hide_document_helpers(document)

    def slotActivateDocument(self, document):
        _hide_document_helpers(document)


def _hide_document_helpers(document):
    if document is None:
        return
    from .WireCable import hide_support_objects

    for obj in document.Objects:
        if getattr(getattr(obj, "Proxy", None), "Type", None) == "WireCable":
            hide_support_objects(obj)
    _hide_helper_tree_rows(document)


def _hide_helper_tree_rows(document):
    if document is None or not getattr(App, "GuiUp", False):
        return
    try:
        from .WireCable import SUPPORT_OBJECT_PROPERTIES
        from PySide import QtWidgets
    except Exception:
        try:
            from .WireCable import SUPPORT_OBJECT_PROPERTIES
            from PySide6 import QtWidgets
        except Exception:
            return
    labels = set()
    for obj in document.Objects:
        if getattr(getattr(obj, "Proxy", None), "Type", None) != "WireCable":
            continue
        for name in SUPPORT_OBJECT_PROPERTIES:
            helper = getattr(obj, name, None)
            if helper is not None and helper.isValid():
                labels.add(helper.Label)
    if not labels:
        return
    main_window = Gui.getMainWindow()
    for view in main_window.findChildren(QtWidgets.QTreeView):
        model = view.model()
        if model is None or view.metaObject().className() != "Gui::TreeWidget":
            continue
        stack = [model.index(i, 0) for i in range(model.rowCount())]
        while stack:
            index = stack.pop()
            try:
                if str(index.data()) in labels:
                    view.setRowHidden(index.row(), index.parent(), True)
                for i in range(model.rowCount(index)):
                    stack.append(model.index(i, 0, index))
            except Exception:
                continue


def install():
    selection_attr = "_wire_helper_selection_observer"
    if getattr(Gui, selection_attr, None) is None:
        observer = HelperSelectionObserver()
        setattr(Gui, selection_attr, observer)
        Gui.Selection.addObserver(observer)

    tree_attr = "_wire_helper_tree_observer"
    if getattr(Gui, tree_attr, None) is None:
        tree_observer = HelperTreeObserver()
        setattr(Gui, tree_attr, tree_observer)
        App.addDocumentObserver(tree_observer)
