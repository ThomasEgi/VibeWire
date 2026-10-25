"""Selection remapping and visual refresh for cable helper geometry."""

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

TIP_HELPERS = {
    "StartTip": (
        "StartCoreObject",
        "StartFerruleMetal",
        "StartFerruleSleeve",
    ),
    "EndTip": (
        "EndCoreObject",
        "EndFerruleMetal",
        "EndFerruleSleeve",
    ),
}


class HelperSelectionObserver:
    """Remap helper clicks to tips and refresh tip highlighting."""

    def __init__(self):
        self._busy = False
        self._refresh_scheduled = False

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
        if selected is None:
            return
        if getattr(getattr(selected, "Proxy", None), "Type", None) == "WireTip":
            self._schedule_refresh()
            return
        target = _selection_target(selected)
        if target is None or target is selected:
            self._schedule_refresh()
            return
        self._busy = True
        try:
            Gui.Selection.removeSelection(selected)
            Gui.Selection.addSelection(target)
        finally:
            self._busy = False
        self._schedule_refresh()

    def removeSelection(self, *args):
        self._schedule_refresh()

    def setSelection(self, *args):
        self._schedule_refresh()

    def clearSelection(self, *args):
        _schedule_tree_clear()
        self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_scheduled:
            return
        self._refresh_scheduled = True
        try:
            from PySide import QtCore
        except Exception:
            try:
                from PySide6 import QtCore
            except Exception:
                self._refresh_scheduled = False
                _refresh_helpers()
                return
        QtCore.QTimer.singleShot(0, self._refresh)

    def _refresh(self):
        self._refresh_scheduled = False
        _refresh_helpers()


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


def _sleeve_color(cable, tip):
    try:
        from . import FerruleData

        entry = FerruleData.cross_section_for_size(
            getattr(cable, "WireSizeMM2", 0.0)
        )
        info, _code = FerruleData.color_for_system(
            entry, getattr(tip, "FerruleColorSystem", "DIN")
        )
        rgb = FerruleData.hex_to_rgb(info["hex"]) if info else None
        if rgb is not None:
            return rgb
    except Exception:
        pass
    return (0.0, 0.0, 0.0)


def _helper_base_color(cable, tip, helper_name):
    if "Core" in helper_name:
        return (0.8, 0.45, 0.2)
    if "FerruleMetal" in helper_name:
        return (0.75, 0.75, 0.78)
    if "FerruleSleeve" in helper_name:
        return _sleeve_color(cable, tip)
    return (0.75, 0.75, 0.78)


def _set_helper_appearance(helper, rgb):
    view = getattr(helper, "ViewObject", None)
    if view is None:
        return
    try:
        transparency = view.Transparency
    except Exception:
        transparency = 0
    count = len(view.ShapeAppearance) or 1
    material = App.Material()
    material.DiffuseColor = (rgb[0], rgb[1], rgb[2], 1.0)
    material.AmbientColor = (0.3333, 0.3333, 0.3333, 1.0)
    material.SpecularColor = (0.5333, 0.5333, 0.5333, 1.0)
    material.EmissiveColor = (0.0, 0.0, 0.0, 1.0)
    material.Shininess = 0.9
    material.Transparency = 0.0
    try:
        view.ShapeAppearance = [material] * count
        view.ShapeColor = rgb
        view.Transparency = transparency
    except Exception:
        pass


def _refresh_helpers():
    document = App.ActiveDocument
    if document is None:
        return
    selected = set(Gui.Selection.getSelection())
    for cable in document.Objects:
        if getattr(getattr(cable, "Proxy", None), "Type", None) != "WireCable":
            continue
        for tip_name, helper_names in TIP_HELPERS.items():
            tip = getattr(cable, tip_name, None)
            if tip is None or not tip.isValid():
                continue
            highlight = tip in selected
            for helper_name in helper_names:
                helper = getattr(cable, helper_name, None)
                if helper is None or not helper.isValid():
                    continue
                if highlight:
                    rgb = (0.0, 1.0, 0.0)
                else:
                    rgb = _helper_base_color(cable, tip, helper_name)
                _set_helper_appearance(helper, rgb)


def schedule_select_tool_object(obj):
    """Keep the object being edited selected and highlighted."""
    if obj is None:
        return
    try:
        from PySide import QtCore
    except Exception:
        try:
            from PySide6 import QtCore
        except Exception:
            return

    def select():
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
        except Exception:
            pass

    QtCore.QTimer.singleShot(0, select)
    QtCore.QTimer.singleShot(100, select)


def _schedule_tree_clear():
    try:
        from PySide import QtCore
    except Exception:
        try:
            from PySide6 import QtCore
        except Exception:
            return
    QtCore.QTimer.singleShot(0, _clear_tree_if_empty)


def _clear_tree_if_empty():
    try:
        if Gui.Selection.getSelection():
            return
    except Exception:
        return
    _clear_tree_selection()


def _clear_tree_selection():
    if not getattr(App, "GuiUp", False):
        return
    try:
        from PySide import QtCore, QtGui, QtWidgets
    except Exception:
        try:
            from PySide6 import QtCore, QtGui, QtWidgets
        except Exception:
            return
    main_window = Gui.getMainWindow()
    if main_window is None:
        return
    for view in main_window.findChildren(QtWidgets.QTreeView):
        try:
            if view.metaObject().className() != "Gui::TreeWidget":
                continue
            view.clearSelection()
            view.setCurrentIndex(QtCore.QModelIndex())
            model = view.model()
            stack = [model.index(i, 0) for i in range(model.rowCount())]
            while stack:
                index = stack.pop()
                if index.data(QtGui.Qt.BackgroundRole) is not None:
                    model.setData(index, None, QtGui.Qt.BackgroundRole)
                for i in range(model.rowCount(index)):
                    stack.append(model.index(i, 0, index))
        except Exception:
            continue


def _clear_tool_tree(obj, others):
    if not getattr(App, "GuiUp", False):
        return
    try:
        from PySide import QtCore, QtGui, QtWidgets
    except Exception:
        try:
            from PySide6 import QtCore, QtGui, QtWidgets
        except Exception:
            return
    label = getattr(obj, "Label", None)
    other_labels = [getattr(item, "Label", None) for item in others]
    main_window = Gui.getMainWindow()
    if main_window is None:
        return
    for view in main_window.findChildren(QtWidgets.QTreeView):
        try:
            if view.metaObject().className() != "Gui::TreeWidget":
                continue
            model = view.model()
            object_indexes = []
            replacement = None
            stack = [model.index(i, 0) for i in range(model.rowCount())]
            while stack:
                index = stack.pop()
                text = str(index.data())
                if text == label:
                    object_indexes.append(index)
                if replacement is None and text in other_labels:
                    replacement = index
                for i in range(model.rowCount(index)):
                    stack.append(model.index(i, 0, index))
            for index in object_indexes:
                if view.selectionModel().isSelected(index):
                    view.selectionModel().select(
                        index, QtCore.QItemSelectionModel.Deselect
                    )
                model.setData(index, None, QtGui.Qt.BackgroundRole)
            if replacement is not None:
                view.selectionModel().select(
                    replacement, QtCore.QItemSelectionModel.Select
                )
            current = view.currentIndex()
            if current.isValid() and str(current.data()) == label:
                view.setCurrentIndex(
                    replacement if replacement is not None else QtCore.QModelIndex()
                )
        except Exception:
            continue


def clear_tool_selection(obj):
    """Deselect the object edited by a closing tool, leaving other selections."""
    if obj is None:
        return
    selected = list(Gui.Selection.getSelection())
    others = [item for item in selected if item is not obj]
    observer = getattr(Gui, "_wire_helper_selection_observer", None)
    was_busy = bool(getattr(observer, "_busy", False))
    if observer is not None:
        observer._busy = True
    try:
        if obj in selected:
            try:
                Gui.Selection.removeSelection(obj)
            except Exception:
                pass
        _clear_tool_tree(obj, others)
    finally:
        if observer is not None:
            observer._busy = was_busy
    current = Gui.Selection.getSelection()
    for other in others:
        if other not in current:
            try:
                Gui.Selection.addSelection(other)
            except Exception:
                pass
    _refresh_helpers()
    if observer is not None:
        observer._schedule_refresh()


def schedule_clear_tool_selection(obj):
    """Clear the tool object again after FreeCAD finishes closing a panel."""
    try:
        from PySide import QtCore
    except Exception:
        try:
            from PySide6 import QtCore
        except Exception:
            return
    QtCore.QTimer.singleShot(0, lambda: clear_tool_selection(obj))
    QtCore.QTimer.singleShot(75, lambda: clear_tool_selection(obj))


def clear_selection():
    """Clear both the document selection and the tree's current item."""
    try:
        Gui.Selection.clearSelection()
    except Exception:
        pass
    _clear_tree_selection()
    _refresh_helpers()


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
    _refresh_helpers()


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
    if main_window is None:
        return
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
    _hide_helper_tree_rows(App.ActiveDocument)
    _refresh_helpers()
