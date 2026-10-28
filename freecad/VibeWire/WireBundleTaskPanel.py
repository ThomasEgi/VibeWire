"""Task panel for defining independent straight bundle segments."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from .PointReference import (
    POINT_REFERENCE_TYPES,
    ClickableLabel,
    PickObserver,
    PointReferenceGate,
)
from .WireBundle import (
    create_bundle_segment,
    create_wire_harness,
    remove_bundle_segment,
    update_segment_dependencies,
)


class WireBundleTaskPanel:
    """Define a list of independent straight bundle segments."""

    def __init__(self, bundle=None):
        self.segments = []
        self._pick_observer = None
        self._picking = None
        self._gate_active = False
        self._syncing_selection = False
        self._selection_observer = None
        self.bundle = bundle

        self.form = QtGui.QWidget()
        self.form.setWindowTitle(
            "Edit Harness" if bundle is not None else "Create Harness"
        )
        layout = QtGui.QVBoxLayout(self.form)

        hint = QtGui.QLabel(
            "Add independent straight bundle segments. They are not connected "
            "to each other; cables route over them and generate their own "
            "bi-arcs between segments. Closed segments only connect end to end; "
            "open segments allow entry and exit anywhere once their cable "
            "entry/exit parameters are set."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.segment_list = QtGui.QListWidget()
        layout.addWidget(self.segment_list)

        list_buttons = QtGui.QHBoxLayout()
        self.btn_add = QtGui.QPushButton("Add Segment")
        self.btn_remove = QtGui.QPushButton("Remove Segment")
        list_buttons.addWidget(self.btn_add)
        list_buttons.addWidget(self.btn_remove)
        layout.addLayout(list_buttons)

        detail_group = QtGui.QGroupBox("Selected Segment")
        detail_layout = QtGui.QFormLayout(detail_group)
        self.start_label = ClickableLabel("(not set)")
        self.btn_pick_start = QtGui.QPushButton("Pick Start")
        self.end_label = ClickableLabel("(not set)")
        self.btn_pick_end = QtGui.QPushButton("Pick End")
        detail_layout.addRow(
            "Start:", self._label_with_button(self.start_label, self.btn_pick_start)
        )
        detail_layout.addRow(
            "End:", self._label_with_button(self.end_label, self.btn_pick_end)
        )
        self.segment_type_combo = QtGui.QComboBox()
        self.segment_type_combo.addItems(["Closed", "Open"])
        detail_layout.addRow("Type:", self.segment_type_combo)
        self.orientation_spin = QtGui.QDoubleSpinBox()
        self.orientation_spin.setRange(-360.0, 360.0)
        self.orientation_spin.setDecimals(1)
        self.orientation_spin.setSingleStep(5.0)
        self.orientation_spin.setValue(0.0)
        self.orientation_spin.setSuffix(" deg")
        detail_layout.addRow("Rotation:", self.orientation_spin)
        self.max_cables_spin = QtGui.QSpinBox()
        self.max_cables_spin.setRange(0, 9999)
        self.max_cables_spin.setValue(0)
        self.max_cables_spin.setSpecialValueText("Unlimited")
        detail_layout.addRow("Max cables:", self.max_cables_spin)
        self.radius_spin = QtGui.QDoubleSpinBox()
        self.radius_spin.setRange(0.1, 1000.0)
        self.radius_spin.setDecimals(2)
        self.radius_spin.setSingleStep(1.0)
        self.radius_spin.setValue(10.0)
        self.radius_spin.setSuffix(" mm")
        detail_layout.addRow("Display radius:", self.radius_spin)
        layout.addWidget(detail_group)

        radius_form = QtGui.QFormLayout()
        self.gap_spin = QtGui.QDoubleSpinBox()
        self.gap_spin.setRange(0.0, 1000.0)
        self.gap_spin.setDecimals(2)
        self.gap_spin.setSingleStep(1.0)
        self.gap_spin.setValue(1.0)
        self.gap_spin.setSuffix(" mm")
        radius_form.addRow("Cable gap:", self.gap_spin)
        self.pattern_combo = QtGui.QComboBox()
        self.pattern_combo.addItems(["Circular", "Linear"])
        radius_form.addRow("Pattern:", self.pattern_combo)
        layout.addLayout(radius_form)

        self.btn_apply = QtGui.QPushButton()
        layout.addWidget(self.btn_apply)

        self.status_label = QtGui.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.btn_add.clicked.connect(self.add_segment)
        self.btn_remove.clicked.connect(self.remove_segment)
        self.btn_pick_start.clicked.connect(lambda: self.pick_point("start"))
        self.btn_pick_end.clicked.connect(lambda: self.pick_point("end"))
        self.start_label.clicked.connect(lambda: self.select_point("start"))
        self.end_label.clicked.connect(lambda: self.select_point("end"))
        self.btn_apply.clicked.connect(self.apply)
        self.segment_type_combo.currentTextChanged.connect(self._on_segment_type_changed)
        self.orientation_spin.valueChanged.connect(self._on_orientation_changed)
        self.max_cables_spin.valueChanged.connect(self._on_max_cables_changed)
        self.radius_spin.valueChanged.connect(self._on_radius_changed)
        self.segment_list.currentRowChanged.connect(self._update_detail)
        self.form.destroyed.connect(self._on_form_destroyed)

        self._update_button_labels()
        if self.bundle is not None:
            self._load_bundle()
        else:
            self._update_list()
            self._update_detail()

        self._select_initial_segment()
        self.segment_list.currentRowChanged.connect(self._on_list_row_changed)
        self._selection_observer = PickObserver(self._on_scene_selection)
        Gui.Selection.addObserver(self._selection_observer)

    def _update_button_labels(self):
        action = "Update" if self.bundle is not None else "Create"
        self.btn_apply.setText(f"{action} Harness")

    def _load_bundle(self):
        self.segments = []
        document = self.bundle.Document
        for segment in self.bundle.Segments:
            start = segment.Start
            end = segment.End
            orientation = 0.0
            if "Orientation" in segment.PropertiesList:
                orientation = segment.Orientation.Value
            self.segments.append(
                {
                    "start": (document.Name, start.Name) if start else None,
                    "end": (document.Name, end.Name) if end else None,
                    "object": segment,
                    "orientation": orientation,
                    "max_cables": int(getattr(segment, "MaxCables", 0) or 0),
                    "radius": segment.Radius.Value,
                    "segment_type": getattr(segment, "SegmentType", "Closed"),
                }
            )
        if "Gap" in self.bundle.PropertiesList:
            self.gap_spin.setValue(self.bundle.Gap.Value)
        if "Pattern" in self.bundle.PropertiesList:
            self.pattern_combo.setCurrentText(self.bundle.Pattern)
        self._update_list()
        if self.segments:
            self.segment_list.setCurrentRow(0)
        self._update_detail()
        self.status_label.setText(f"Harness has {len(self.segments)} segment(s).")

    @staticmethod
    def _label_with_button(label, button):
        container = QtGui.QWidget()
        layout = QtGui.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label, 1)
        layout.addWidget(button)
        return container

    def getStandardButtons(self):
        return QtGui.QDialogButtonBox.Close

    def isAllowedAlterSelection(self):
        return True

    def isAllowedAlterView(self):
        return True

    def add_segment(self):
        self.segments.append(
            {
                "start": None,
                "end": None,
                "object": None,
                "orientation": 0.0,
                "max_cables": 0,
                "radius": self.radius_spin.value(),
                "segment_type": "Closed",
            }
        )
        self._update_list()
        self.segment_list.setCurrentRow(len(self.segments) - 1)

    def remove_segment(self):
        row = self._current_row()
        if row is None:
            return
        del self.segments[row]
        self._update_list()
        if self.segments:
            self.segment_list.setCurrentRow(min(row, len(self.segments) - 1))
        else:
            self._update_detail()

    def pick_point(self, field):
        row = self._current_row()
        if row is None:
            QtGui.QMessageBox.information(
                self.form, "VibeWire", "Add and select a segment first."
            )
            return

        self._stop_picking()
        self._picking = (row, field)
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Select a point reference in the 3D view or tree for segment "
            f"{row + 1} {field}."
        )
        Gui.Selection.clearSelection()
        Gui.Selection.addSelectionGate(PointReferenceGate())
        self._gate_active = True
        self._pick_observer = PickObserver(self._on_picked)
        Gui.Selection.addObserver(self._pick_observer)

    def _on_picked(self, doc_name, obj_name, subelement):
        if self._picking is None:
            return

        if isinstance(doc_name, str):
            document = App.getDocument(doc_name)
        else:
            document = doc_name
        if document is None:
            return
        if isinstance(obj_name, str):
            obj = document.getObject(obj_name)
        else:
            obj = obj_name
        if obj is None or obj.TypeId not in POINT_REFERENCE_TYPES:
            return

        row, field = self._picking
        self._stop_picking()
        if row >= len(self.segments):
            return

        self.segments[row][field] = (document.Name, obj.Name)
        self._update_list()
        self.segment_list.setCurrentRow(row)

    def _stop_picking(self):
        if self._pick_observer is not None:
            try:
                Gui.Selection.removeObserver(self._pick_observer)
            except Exception:
                pass
            self._pick_observer = None
        if self._gate_active:
            try:
                Gui.Selection.removeSelectionGate()
            except Exception:
                pass
            self._gate_active = False
        if self._picking is not None:
            self._picking = None
            try:
                self.status_label.setText("")
            except Exception:
                pass

    def _on_form_destroyed(self, *args):
        self._stop_picking()
        self._remove_selection_observer()
        try:
            from .WireSelection import clear_tool_selection, schedule_clear_tool_selection

            clear_tool_selection(self.bundle)
            schedule_clear_tool_selection(self.bundle)
        except Exception:
            pass

    def _select_initial_segment(self):
        if self.bundle is None:
            return
        selected = Gui.Selection.getSelection()
        for row, entry in enumerate(self.segments):
            if entry.get("object") in selected:
                self.segment_list.setCurrentRow(row)
                item = self.segment_list.item(row)
                if item is not None:
                    self.segment_list.scrollToItem(item)
                return

    def _on_list_row_changed(self, _row):
        if self._syncing_selection or self._picking is not None:
            return
        row = self._current_row()
        if row is None:
            return
        segment = self.segments[row].get("object")
        if segment is None or not segment.isValid():
            return
        self._syncing_selection = True
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(segment)
        finally:
            self._syncing_selection = False

    def _on_scene_selection(self, doc_name, obj_name, subelement):
        if self._syncing_selection or self._picking is not None:
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
        from .WireBundle import is_bundle_segment

        if not is_bundle_segment(selected):
            return
        matches = [
            row
            for row, entry in enumerate(self.segments)
            if entry.get("object") is selected
        ]
        if not matches:
            return
        current = self.segment_list.currentRow()
        row = current if current in matches else matches[0]
        self._syncing_selection = True
        try:
            self.segment_list.setCurrentRow(row)
            item = self.segment_list.item(row)
            if item is not None:
                self.segment_list.scrollToItem(item)
        finally:
            self._syncing_selection = False

    def _remove_selection_observer(self):
        if self._selection_observer is not None:
            try:
                Gui.Selection.removeObserver(self._selection_observer)
            except Exception:
                pass
            self._selection_observer = None

    def _current_row(self):
        row = self.segment_list.currentRow()
        if row < 0 or row >= len(self.segments):
            return None
        return row

    @staticmethod
    def _resolve(ref):
        if ref is None:
            return None
        document = App.getDocument(ref[0])
        if document is None:
            return None
        return document.getObject(ref[1])

    def _point_text(self, ref):
        obj = self._resolve(ref)
        if obj is None:
            return "(not set)" if ref is None else "(missing)"
        point = obj.getGlobalPlacement().Base
        return f"{obj.Label} ({point.x:.2f}, {point.y:.2f}, {point.z:.2f})"

    def _update_list(self):
        current = self.segment_list.currentRow()
        self.segment_list.blockSignals(True)
        self.segment_list.clear()
        for index, segment in enumerate(self.segments):
            start = self._point_text(segment["start"])
            end = self._point_text(segment["end"])
            suffix = " [Open]" if segment.get("segment_type") == "Open" else ""
            self.segment_list.addItem(f"{index + 1}: {start} -> {end}{suffix}")
        if 0 <= current < len(self.segments):
            self.segment_list.setCurrentRow(current)
        self.segment_list.blockSignals(False)
        self._update_detail()

    def _update_detail(self, *args):
        row = self._current_row()
        has_segment = row is not None
        self.btn_pick_start.setEnabled(has_segment)
        self.btn_pick_end.setEnabled(has_segment)
        self.btn_remove.setEnabled(has_segment)
        self.orientation_spin.setEnabled(has_segment)
        self.max_cables_spin.setEnabled(has_segment)
        self.radius_spin.setEnabled(has_segment)
        self.segment_type_combo.setEnabled(has_segment)

        if not has_segment:
            self._update_point_label(self.start_label, None)
            self._update_point_label(self.end_label, None)
            self.orientation_spin.blockSignals(True)
            self.orientation_spin.setValue(0.0)
            self.orientation_spin.blockSignals(False)
            self.max_cables_spin.blockSignals(True)
            self.max_cables_spin.setValue(0)
            self.max_cables_spin.blockSignals(False)
            self.segment_type_combo.blockSignals(True)
            self.segment_type_combo.setCurrentText("Closed")
            self.segment_type_combo.blockSignals(False)
            return

        segment = self.segments[row]
        self._update_point_label(self.start_label, segment["start"])
        self._update_point_label(self.end_label, segment["end"])
        self.segment_type_combo.blockSignals(True)
        self.segment_type_combo.setCurrentText(
            segment.get("segment_type", "Closed")
        )
        self.segment_type_combo.blockSignals(False)
        self.orientation_spin.blockSignals(True)
        self.orientation_spin.setValue(segment.get("orientation", 0.0))
        self.orientation_spin.blockSignals(False)
        self.max_cables_spin.blockSignals(True)
        self.max_cables_spin.setValue(int(segment.get("max_cables", 0) or 0))
        self.max_cables_spin.blockSignals(False)
        self.radius_spin.blockSignals(True)
        self.radius_spin.setValue(float(segment.get("radius", 10.0) or 10.0))
        self.radius_spin.blockSignals(False)

    def _on_orientation_changed(self, value):
        row = self._current_row()
        if row is not None:
            self.segments[row]["orientation"] = float(value)

    def _on_max_cables_changed(self, value):
        row = self._current_row()
        if row is not None:
            self.segments[row]["max_cables"] = int(value)

    def _on_segment_type_changed(self, value):
        row = self._current_row()
        if row is None:
            return
        self.segments[row]["segment_type"] = value
        self._update_list()

    def _on_radius_changed(self, value):
        row = self._current_row()
        if row is None:
            return
        entry = self.segments[row]
        entry["radius"] = float(value)
        segment = entry.get("object")
        if segment is not None and segment.isValid():
            segment.Radius = float(value)
            if segment.Document is not None:
                segment.Document.recompute()

    def _update_point_label(self, label, ref):
        label.setText(self._point_text(ref))
        if self._resolve(ref) is None:
            label.setCursor(QtCore.Qt.ArrowCursor)
            label.setStyleSheet("")
            label.setToolTip("")
        else:
            label.setCursor(QtCore.Qt.PointingHandCursor)
            label.setStyleSheet("color: #1a5fb4; text-decoration: underline;")
            label.setToolTip("Click to select this point reference in the scene")

    def select_point(self, field):
        row = self._current_row()
        if row is None:
            return
        self._stop_picking()
        obj = self._resolve(self.segments[row][field])
        if obj is None:
            self.status_label.setStyleSheet("")
            self.status_label.setText(
                f"No point reference set for segment {row + 1} {field}."
            )
            return
        try:
            obj.ViewObject.Visibility = True
        except Exception:
            pass
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj)
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            f"Selected {obj.Label} for segment {row + 1} {field}."
        )

    def _target_document(self):
        if self.bundle is not None:
            try:
                if self.bundle.isValid():
                    return self.bundle.Document
            except Exception:
                pass
        document = App.ActiveDocument
        if document is None:
            document = App.newDocument("Bundle")
        return document

    @staticmethod
    def _is_valid(obj, document):
        try:
            return obj is not None and obj.isValid() and obj.Document is document
        except Exception:
            return False

    def _collect_segments(self, document):
        if not self.segments:
            raise ValueError("Add at least one bundle segment first.")
        result = []
        for index, segment in enumerate(self.segments):
            start = self._resolve(segment["start"])
            end = self._resolve(segment["end"])
            if start is None:
                raise ValueError(
                    f"Segment {index + 1} needs a start point reference."
                )
            if end is None:
                raise ValueError(
                    f"Segment {index + 1} needs an end point reference."
                )
            if start.Document is not document or end.Document is not document:
                raise ValueError(
                    "All point references must belong to the same document "
                    "as the bundle."
                )
            if (end.getGlobalPlacement().Base - start.getGlobalPlacement().Base).Length < 1e-9:
                raise ValueError(
                    f"Segment {index + 1} has identical start and end points."
                )
            result.append((start, end))
        return result

    def apply(self):
        self._stop_picking()
        document = self._target_document()
        try:
            segment_points = self._collect_segments(document)
        except ValueError as error:
            QtGui.QMessageBox.warning(self.form, "VibeWire", str(error))
            return

        try:
            bundle_usable = self._is_valid(self.bundle, document)
            if not bundle_usable:
                self.bundle = create_wire_harness(document)
            if "Pattern" not in self.bundle.PropertiesList:
                self.bundle.addProperty(
                    "App::PropertyEnumeration",
                    "Pattern",
                    "Harness",
                    "Cable arrangement pattern",
                )
                self.bundle.Pattern = ["Circular", "Linear"]
            self.bundle.Gap = self.gap_spin.value()
            self.bundle.Pattern = self.pattern_combo.currentText()

            panel_objects = []
            for entry, (start, end) in zip(self.segments, segment_points):
                segment = entry.get("object")
                if self._is_valid(segment, document):
                    segment.Start = start
                    segment.End = end
                    segment.Radius = float(entry.get("radius", 10.0) or 10.0)
                    segment.Orientation = entry.get("orientation", 0.0)
                    segment.MaxCables = int(entry.get("max_cables", 0) or 0)
                    segment.SegmentType = entry.get("segment_type", "Closed")
                    update_segment_dependencies(segment)
                else:
                    segment = create_bundle_segment(
                        self.bundle,
                        start,
                        end,
                        radius=float(entry.get("radius", 10.0) or 10.0),
                        segment_type=entry.get("segment_type", "Closed"),
                    )
                    segment.Orientation = entry.get("orientation", 0.0)
                    segment.MaxCables = int(entry.get("max_cables", 0) or 0)
                    entry["object"] = segment
                panel_objects.append(segment)

            for segment in list(self.bundle.Segments):
                if segment not in panel_objects:
                    remove_bundle_segment(self.bundle, segment)
            self.bundle.Segments = panel_objects
            from .WireBundle import ensure_helper_group, ensure_segment_group

            ensure_segment_group(self.bundle)
            ensure_helper_group(self.bundle)
        except Exception as error:
            QtGui.QMessageBox.critical(self.form, "VibeWire", str(error))
            return

        document.recompute()
        self._update_button_labels()
        self.status_label.setStyleSheet("")
        self.status_label.setText(f"Harness has {len(panel_objects)} segment(s).")

    def reject(self):
        self._stop_picking()
        Gui.Control.closeDialog()
        try:
            from .WireSelection import clear_tool_selection, schedule_clear_tool_selection

            clear_tool_selection(self.bundle)
            schedule_clear_tool_selection(self.bundle)
        except Exception:
            pass

    def accept(self):
        self._stop_picking()
        Gui.Control.closeDialog()
        try:
            from .WireSelection import clear_tool_selection, schedule_clear_tool_selection

            clear_tool_selection(self.bundle)
            schedule_clear_tool_selection(self.bundle)
        except Exception:
            pass
