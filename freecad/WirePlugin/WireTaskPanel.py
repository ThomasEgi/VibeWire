"""Task panel for defining wire segments from point references."""

import math
import re

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from . import FerruleData
from .WireColors import TRACER_NONE, color_hex, names as cable_color_names
from .WireBundle import (
    add_cable_to_harness,
    find_harness_for_segments,
    is_bundle_segment,
)
from .WireCable import (
    WireCableProxy,
    create_wire_cable,
    ensure_support_objects,
    rename_cable,
    update_cable_dependencies,
)
from .PointReference import (
    POINT_REFERENCE_TYPES,
    ClickableLabel,
    PickObserver,
    PointReferenceGate,
)
from .WireCreator import Segment


class WireTaskPanel:
    """Define an ordered list of segments by picking their start/end points."""

    def __init__(self, cable=None):
        self.segments = []
        self._pick_observer = None
        self._picking = None
        self._gate_active = False
        self._syncing_selection = False
        self._syncing_colors = False
        self._selection_observer = None
        self.cable = cable
        self._build_cable = (
            bool(getattr(cable, "BuildCable", True)) if cable is not None else True
        )

        self.form = QtGui.QWidget()
        self.form.setWindowTitle("Edit Wire" if cable is not None else "Create Wire")

        layout = QtGui.QVBoxLayout(self.form)

        name_form = QtGui.QFormLayout()
        self.name_edit = QtGui.QLineEdit()
        self.name_edit.setPlaceholderText("Auto: wire_<start>_<end>")
        self.name_edit.setToolTip(
            "Leave empty to name the wire as wire_<first start>_<last end>."
        )
        name_form.addRow("Wire name:", self.name_edit)
        layout.addLayout(name_form)

        hint = QtGui.QLabel(
            "Add segments and pick a start/end reference. Pick a point "
            "reference (coordinate system, Std_Part origin, Part/Body) or a "
            "bundle segment cylinder. Picking a bundle segment collects its "
            "other endpoint automatically; as start it runs normal, as end it "
            "runs reversed."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.segment_list = QtGui.QListWidget()
        layout.addWidget(self.segment_list)

        list_buttons = QtGui.QHBoxLayout()
        self.btn_add = QtGui.QPushButton("Add Segment")
        self.btn_remove = QtGui.QPushButton("Remove Segment")
        self.btn_up = QtGui.QPushButton("Move Up")
        self.btn_down = QtGui.QPushButton("Move Down")
        self.btn_swap = QtGui.QPushButton("Swap Start/End")
        list_buttons.addWidget(self.btn_add)
        list_buttons.addWidget(self.btn_remove)
        list_buttons.addWidget(self.btn_up)
        list_buttons.addWidget(self.btn_down)
        list_buttons.addWidget(self.btn_swap)
        layout.addLayout(list_buttons)

        detail_group = QtGui.QGroupBox("Selected Segment")
        detail_layout = QtGui.QFormLayout(detail_group)
        self.start_label = ClickableLabel("(not set)")
        self.btn_pick_start = QtGui.QPushButton("Pick Start")
        self.end_label = ClickableLabel("(not set)")
        self.btn_pick_end = QtGui.QPushButton("Pick End")
        detail_layout.addRow("Start:", self._label_with_button(self.start_label, self.btn_pick_start))
        detail_layout.addRow("End:", self._label_with_button(self.end_label, self.btn_pick_end))
        layout.addWidget(detail_group)

        geometry_group = QtGui.QGroupBox("Geometry")
        geometry_layout = QtGui.QFormLayout(geometry_group)
        self.wire_size_combo = QtGui.QComboBox()
        self.wire_size_combo.addItem("Custom wire size", 0.0)
        for entry in FerruleData.cross_sections():
            self.wire_size_combo.addItem(
                FerruleData.size_label(entry), entry["cross_section_mm2"]
            )
        geometry_layout.addRow("Wire size:", self.wire_size_combo)
        self.cable_color_combo = QtGui.QComboBox()
        self.cable_color_combo.setIconSize(QtCore.QSize(14, 14))
        self.cable_color_combo.addItem(
            self._cable_color_icon(("Green", "Green", "Green", "Yellow")),
            "PE (Green-Yellow)",
            "__PE__",
        )
        self.cable_color_combo.insertSeparator(self.cable_color_combo.count())
        for name in cable_color_names():
            self.cable_color_combo.addItem(
                self._cable_color_icon((name,)), name, name
            )
        blue_index = self.cable_color_combo.findData("Blue")
        self.cable_color_combo.setCurrentIndex(
            blue_index if blue_index >= 0 else 0
        )
        geometry_layout.addRow("Primary color:", self.cable_color_combo)
        self.cable_tracer_combo = QtGui.QComboBox()
        self.cable_tracer_combo.setIconSize(QtCore.QSize(14, 14))
        self.cable_tracer_combo.addItem("None", TRACER_NONE)
        self.cable_tracer_combo.insertSeparator(self.cable_tracer_combo.count())
        for name in cable_color_names():
            self.cable_tracer_combo.addItem(
                self._cable_color_icon((name,)), name, name
            )
        geometry_layout.addRow("Tracer color:", self.cable_tracer_combo)
        self.diameter_spin = QtGui.QDoubleSpinBox()
        self.diameter_spin.setRange(0.1, 1000.0)
        self.diameter_spin.setDecimals(2)
        self.diameter_spin.setSingleStep(0.5)
        self.diameter_spin.setValue(4.0)
        self.diameter_spin.setSuffix(" mm")
        self.derived_diameter_label = QtGui.QLabel("")
        diameter_widget = QtGui.QWidget()
        diameter_layout = QtGui.QHBoxLayout(diameter_widget)
        diameter_layout.setContentsMargins(0, 0, 0, 0)
        diameter_layout.addWidget(self.diameter_spin)
        diameter_layout.addWidget(self.derived_diameter_label, 1)
        self.min_bend_spin = QtGui.QDoubleSpinBox()
        self.min_bend_spin.setRange(0.0, 100000.0)
        self.min_bend_spin.setDecimals(2)
        self.min_bend_spin.setSingleStep(1.0)
        self.min_bend_spin.setValue(12.0)
        self.min_bend_spin.setSuffix(" mm")
        geometry_layout.addRow("Diameter:", diameter_widget)
        self.core_diameter_spin = QtGui.QDoubleSpinBox()
        self.core_diameter_spin.setRange(0.01, 1000.0)
        self.core_diameter_spin.setDecimals(2)
        self.core_diameter_spin.setSingleStep(0.1)
        self.core_diameter_spin.setValue(1.13)
        self.core_diameter_spin.setSuffix(" mm")
        self.core_diameter_label = QtGui.QLabel("")
        core_widget = QtGui.QWidget()
        core_layout = QtGui.QHBoxLayout(core_widget)
        core_layout.setContentsMargins(0, 0, 0, 0)
        core_layout.addWidget(self.core_diameter_spin)
        core_layout.addWidget(self.core_diameter_label, 1)
        geometry_layout.addRow("Core diameter:", core_widget)
        geometry_layout.addRow("Minimum bend radius:", self.min_bend_spin)

        geometry_buttons = QtGui.QHBoxLayout()
        self.btn_create_path = QtGui.QPushButton("Create Path")
        self.btn_create_cable = QtGui.QPushButton("Create Cable")
        geometry_buttons.addWidget(self.btn_create_path)
        geometry_buttons.addWidget(self.btn_create_cable)
        geometry_layout.addRow(geometry_buttons)
        layout.addWidget(geometry_group)

        self.status_label = QtGui.QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.btn_add.clicked.connect(self.add_segment)
        self.btn_remove.clicked.connect(self.remove_segment)
        self.btn_up.clicked.connect(self.move_up)
        self.btn_down.clicked.connect(self.move_down)
        self.btn_swap.clicked.connect(self.swap_segment_ends)
        self.btn_pick_start.clicked.connect(lambda: self.pick_point("start"))
        self.btn_pick_end.clicked.connect(lambda: self.pick_point("end"))
        self.start_label.clicked.connect(lambda: self.select_point("start"))
        self.end_label.clicked.connect(lambda: self.select_point("end"))
        self.btn_create_path.clicked.connect(self.create_path)
        self.btn_create_cable.clicked.connect(self.create_cable)
        self.wire_size_combo.currentIndexChanged.connect(self._on_wire_size_changed)
        self.cable_color_combo.currentIndexChanged.connect(
            self._on_primary_color_changed
        )
        self.cable_tracer_combo.currentIndexChanged.connect(
            self._on_tracer_color_changed
        )
        self.diameter_spin.valueChanged.connect(lambda _value: self._schedule_live_update())
        self.core_diameter_spin.valueChanged.connect(lambda _value: self._schedule_live_update())
        self.min_bend_spin.valueChanged.connect(lambda _value: self._schedule_live_update())
        self._live_timer = QtCore.QTimer(self.form)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(100)
        self._live_timer.timeout.connect(self._live_update)
        self.segment_list.currentRowChanged.connect(self._update_detail)
        self.form.destroyed.connect(self._on_form_destroyed)

        self._update_button_labels()
        if self.cable is not None:
            self._load_cable()
        else:
            self._on_wire_size_changed()
            self._update_list()
            self._update_detail()

        self.segment_list.currentRowChanged.connect(self._on_list_row_changed)
        self._selection_observer = PickObserver(self._on_scene_selection)
        Gui.Selection.addObserver(self._selection_observer)

    def _update_button_labels(self):
        action = "Update" if self.cable is not None else "Create"
        self.btn_create_path.setText(f"{action} Path")
        self.btn_create_cable.setText(f"{action} Cable")

    def _load_cable(self):
        WireCableProxy._add_properties(self.cable)
        self.segments = []
        document = self.cable.Document
        points = list(self.cable.Points)
        for index in range(0, len(points) - 1, 2):
            start = points[index]
            end = points[index + 1]
            if start is None or end is None:
                continue
            self.segments.append(
                {
                    "start": (document.Name, start.Name),
                    "end": (document.Name, end.Name),
                    "auto_field": None,
                }
            )

        primary = getattr(self.cable, "CableColor", "Blue")
        tracer = getattr(self.cable, "CableColorTracer", TRACER_NONE)
        self._set_color_combos(primary, tracer)
        self.diameter_spin.setValue(self.cable.Diameter.Value)
        self.core_diameter_spin.setValue(self.cable.CoreDiameter.Value)
        self.min_bend_spin.setValue(self.cable.MinBendRadius.Value)
        self._build_cable = bool(self.cable.BuildCable)
        size = getattr(self.cable, "WireSizeMM2", 0.0)
        index = self.wire_size_combo.findData(size)
        self.wire_size_combo.setCurrentIndex(index if index >= 0 else 0)
        self._on_wire_size_changed()
        self.name_edit.setText(self.cable.Label)

        self._update_list()
        if self.segments:
            self.segment_list.setCurrentRow(0)
        self._update_detail()
        self._show_cable_status()
        self._live_timer.stop()

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
        self.segments.append({"start": None, "end": None, "auto_field": None})
        self._update_list()
        self.segment_list.setCurrentRow(len(self.segments) - 1)
        self._schedule_live_update()

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
        self._schedule_live_update()

    def move_up(self):
        row = self._current_row()
        if row is None or row == 0:
            return
        self.segments[row - 1], self.segments[row] = self.segments[row], self.segments[row - 1]
        self._update_list()
        self.segment_list.setCurrentRow(row - 1)
        self._schedule_live_update()

    def move_down(self):
        row = self._current_row()
        if row is None or row >= len(self.segments) - 1:
            return
        self.segments[row + 1], self.segments[row] = self.segments[row], self.segments[row + 1]
        self._update_list()
        self.segment_list.setCurrentRow(row + 1)
        self._schedule_live_update()

    def swap_segment_ends(self):
        row = self._current_row()
        if row is None:
            return
        segment = self.segments[row]
        start_obj = self._resolve(segment["start"])
        end_obj = self._resolve(segment["end"])
        if is_bundle_segment(start_obj) and start_obj is end_obj:
            endpoint = start_obj.End
            if endpoint is not None:
                document = start_obj.Document
                segment["start"] = (document.Name, endpoint.Name)
                segment["end"] = (document.Name, start_obj.Name)
                segment["auto_field"] = "start"
                self._update_list()
                self.segment_list.setCurrentRow(row)
                self._schedule_live_update()
                return
        segment["start"], segment["end"] = segment["end"], segment["start"]
        auto_field = segment.get("auto_field")
        if auto_field == "start":
            segment["auto_field"] = "end"
        elif auto_field == "end":
            segment["auto_field"] = "start"
        self._update_list()
        self.segment_list.setCurrentRow(row)
        self._schedule_live_update()

    def pick_point(self, field):
        row = self._current_row()
        if row is None:
            QtGui.QMessageBox.information(
                self.form, "WirePlugin", "Add and select a segment first."
            )
            return

        self._stop_picking()
        self._picking = (row, field)
        self.status_label.setStyleSheet("")
        self.status_label.setText(
            "Select a point reference or bundle segment in the 3D view or "
            f"tree for segment {row + 1} {field}."
        )
        Gui.Selection.clearSelection()
        Gui.Selection.addSelectionGate(
            PointReferenceGate(allow_bundle_segments=True)
        )
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
        if obj is None:
            return
        if obj.TypeId not in POINT_REFERENCE_TYPES and not is_bundle_segment(obj):
            return

        row, field = self._picking
        self._stop_picking()
        if row >= len(self.segments):
            return

        entry = self.segments[row]
        if is_bundle_segment(obj):
            endpoint = obj.End
            entry["start"] = None
            entry["end"] = None
            entry["auto_field"] = None
            if field == "start":
                entry["start"] = (document.Name, obj.Name)
                if endpoint is not None:
                    entry["end"] = (document.Name, endpoint.Name)
                    entry["auto_field"] = "end"
            else:
                entry["end"] = (document.Name, obj.Name)
                if endpoint is not None:
                    entry["start"] = (document.Name, endpoint.Name)
                    entry["auto_field"] = "start"
            self.status_label.setStyleSheet("")
            self.status_label.setText("Bundle segment endpoints set.")
        else:
            entry[field] = (document.Name, obj.Name)
            if entry.get("auto_field") == field:
                entry["auto_field"] = None
        self._update_list()
        self.segment_list.setCurrentRow(row)
        self._schedule_live_update()

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

            clear_tool_selection(self.cable)
            schedule_clear_tool_selection(self.cable)
        except Exception:
            pass

    def _remove_selection_observer(self):
        if self._selection_observer is not None:
            try:
                Gui.Selection.removeObserver(self._selection_observer)
            except Exception:
                pass
            self._selection_observer = None

    def _row_scene_objects(self, row):
        objects = []
        segment = self.segments[row]
        for field in ("start", "end"):
            obj = self._resolve(segment[field])
            if obj is not None and obj not in objects:
                objects.append(obj)
        bundles = [obj for obj in objects if is_bundle_segment(obj)]
        return bundles if bundles else objects

    def _on_list_row_changed(self, _row):
        if self._syncing_selection or self._picking is not None:
            return
        row = self._current_row()
        if row is None:
            return
        objects = self._row_scene_objects(row)
        if not objects:
            return
        self._syncing_selection = True
        try:
            Gui.Selection.clearSelection()
            for obj in objects:
                Gui.Selection.addSelection(obj)
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
        if selected is None or not is_bundle_segment(selected):
            return

        matches = []
        for row, segment in enumerate(self.segments):
            if (
                self._resolve(segment["start"]) is selected
                or self._resolve(segment["end"]) is selected
            ):
                matches.append(row)
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

    def _point_text(self, ref, reversed_bundle=False):
        obj = self._resolve(ref)
        if obj is None:
            return "(not set)" if ref is None else "(missing)"
        if is_bundle_segment(obj):
            start = obj.Start.Label if obj.Start else "?"
            end = obj.End.Label if obj.End else "?"
            if reversed_bundle:
                return f"{obj.Label} ({end} -> {start}) [reversed]"
            return f"{obj.Label} ({start} -> {end})"
        point = obj.getGlobalPlacement().Base
        return f"{obj.Label} ({point.x:.2f}, {point.y:.2f}, {point.z:.2f})"

    def _on_wire_size_changed(self, *args):
        data = self.wire_size_combo.currentData()
        entry = FerruleData.cross_section_for_size(data) if data else None
        if entry is not None:
            self.diameter_spin.setValue(entry["cable_diameter_mm"])
            self.diameter_spin.setVisible(False)
            self.derived_diameter_label.setText(
                f"{entry['cable_diameter_mm']:.2f} mm "
                "(from sleeve d2 - 1 mm)"
            )
            self.derived_diameter_label.setVisible(True)
            core_diameter = 2.0 * math.sqrt(
                entry["cross_section_mm2"] / math.pi
            )
            self.core_diameter_spin.setValue(core_diameter)
            self.core_diameter_spin.setVisible(False)
            self.core_diameter_label.setText(
                f"{core_diameter:.2f} mm "
                f"(from {entry['cross_section_mm2']:g} mm²)"
            )
            self.core_diameter_label.setVisible(True)
        else:
            self.diameter_spin.setVisible(True)
            self.derived_diameter_label.setVisible(False)
            self.core_diameter_spin.setVisible(True)
            self.core_diameter_label.setVisible(False)
        self._schedule_live_update()

    @staticmethod
    def _cable_color_icon(colors):
        pixmap = QtGui.QPixmap(14, 14)
        if len(colors) == 1 or len(set(colors)) == 1:
            pixmap.fill(QtGui.QColor(color_hex(colors[0])))
        else:
            pixmap.fill(QtGui.QColor(color_hex(colors[0])))
            painter = QtGui.QPainter(pixmap)
            for color_name, rect in zip(
                colors,
                (
                    QtCore.QRect(0, 0, 7, 7),
                    QtCore.QRect(7, 0, 7, 7),
                    QtCore.QRect(0, 7, 7, 7),
                    QtCore.QRect(7, 7, 7, 7),
                ),
            ):
                painter.fillRect(rect, QtGui.QColor(color_hex(color_name)))
            painter.end()
        return QtGui.QIcon(pixmap)

    def _set_color_combos(self, primary, tracer):
        self._syncing_colors = True
        try:
            index = self.cable_color_combo.findData(primary)
            if index < 0:
                index = self.cable_color_combo.findData("Blue")
            self.cable_color_combo.setCurrentIndex(index if index >= 0 else 0)
            index = self.cable_tracer_combo.findData(tracer)
            if index < 0:
                index = 0
            self.cable_tracer_combo.setCurrentIndex(index)
        finally:
            self._syncing_colors = False

    def _selected_primary_color(self):
        value = self.cable_color_combo.currentData()
        if value == "__PE__":
            return "Green"
        return value if value else "Blue"

    def _selected_tracer_color(self):
        value = self.cable_tracer_combo.currentData()
        return value if value else TRACER_NONE

    def _apply_cable_colors(self, primary, tracer):
        if self.cable is not None and self.cable.isValid():
            self.cable.CableColor = primary
            self.cable.CableColorTracer = tracer
            try:
                self.cable.Document.recompute()
            except Exception:
                pass

    def _on_primary_color_changed(self, *args):
        if self._syncing_colors:
            return
        value = self.cable_color_combo.currentData()
        if not value:
            return
        if value == "__PE__":
            self._set_color_combos("Green", "Yellow")
            self._apply_cable_colors("Green", "Yellow")
            return
        self._apply_cable_colors(value, self._selected_tracer_color())

    def _on_tracer_color_changed(self, *args):
        if self._syncing_colors:
            return
        value = self.cable_tracer_combo.currentData()
        if not value:
            return
        self._apply_cable_colors(self._selected_primary_color(), value)

    def _schedule_live_update(self):
        if self.cable is not None:
            if self._cable_is_usable(self.cable.Document):
                self._live_timer.start()
        elif len(self.segments) > 1:
            self._live_timer.start()

    def _live_update(self):
        if self.cable is None and len(self.segments) <= 1:
            self.status_label.setStyleSheet("")
            self.status_label.setText("")
            return

        document = self._target_document()
        links, error = self._collect_valid_prefix(document)
        if error is not None:
            self._update_incomplete_preview(document, links, error)
            return
        self._generate(make_cable=self._build_cable, live=True)

    def _collect_valid_prefix(self, document):
        if not self.segments:
            return [], "Add at least one segment first."

        links = []
        for index, segment in enumerate(self.segments):
            start_obj = self._resolve(segment["start"])
            end_obj = self._resolve(segment["end"])
            if start_obj is None:
                return links, f"Segment {index + 1} needs a start reference."
            if end_obj is None:
                return links, f"Segment {index + 1} needs an end reference."
            if (
                start_obj.Document is not document
                or end_obj.Document is not document
            ):
                return (
                    links,
                    "All references must belong to the same document as the cable.",
                )
            if not is_bundle_segment(start_obj) and not is_bundle_segment(end_obj):
                start = start_obj.getGlobalPlacement().Base
                end = end_obj.getGlobalPlacement().Base
                if (end - start).Length < 1e-9:
                    return (
                        links,
                        f"Segment {index + 1} has identical start and end points.",
                    )
            links.extend([start_obj, end_obj])
        return links, None

    def _apply_cable_parameters(self, cable):
        diameter = self.diameter_spin.value()
        min_bend_radius = self.min_bend_spin.value()
        wire_size_data = self.wire_size_combo.currentData()
        wire_size_mm2 = float(wire_size_data) if wire_size_data else 0.0
        cable.Diameter = diameter
        cable.MinBendRadius = min_bend_radius
        cable.WireSizeMM2 = wire_size_mm2
        cable.CableColor = self._selected_primary_color()
        cable.CableColorTracer = self._selected_tracer_color()
        if wire_size_mm2 > 0.0:
            cable.CoreSizeMode = "Area"
            cable.CoreArea = wire_size_mm2
            cable.CoreDiameter = 2.0 * math.sqrt(wire_size_mm2 / math.pi)
        else:
            core_diameter = self.core_diameter_spin.value()
            cable.CoreSizeMode = "Diameter"
            cable.CoreDiameter = core_diameter
            cable.CoreArea = math.pi * (core_diameter / 2.0) ** 2

    def _update_incomplete_preview(self, document, links, message):
        if self.cable is None and (len(self.segments) <= 1 or not links):
            self.status_label.setStyleSheet("color: #d08000;")
            self.status_label.setText(f"Segment definition incomplete: {message}")
            return

        try:
            if self._cable_is_usable(document):
                ensure_support_objects(self.cable)
                self.cable.Points = links
                update_cable_dependencies(self.cable)
                self._apply_cable_parameters(self.cable)
                self.cable.BuildCable = self._build_cable
                self.cable.Preview = True
            else:
                name_text = self.name_edit.text().strip()
                preview_name = name_text or self._auto_wire_name(links)
                safe_name = self._safe_object_name(preview_name)
                container = document.addObject(
                    "App::DocumentObjectGroup", safe_name + "_Group"
                )
                self.cable = create_wire_cable(
                    document,
                    links,
                    diameter=self.diameter_spin.value(),
                    min_bend_radius=self.min_bend_spin.value(),
                    container=container,
                    build_cable=self._build_cable,
                    name=safe_name,
                    label=preview_name,
                )
                self._apply_cable_parameters(self.cable)
                self.cable.Preview = True
                rename_cable(self.cable, preview_name)

            harness = find_harness_for_segments(links) if links else None
            if harness is not None:
                add_cable_to_harness(harness, self.cable)
            else:
                self.cable.Harness = None
            document.recompute()
            self._update_button_labels()
        except Exception as error:
            self.status_label.setStyleSheet("color: #b00000;")
            self.status_label.setText(str(error))
            return

        self.status_label.setStyleSheet("color: #d08000;")
        self.status_label.setText(f"Segment definition incomplete: {message}")

    def _update_list(self):
        current = self.segment_list.currentRow()
        self.segment_list.blockSignals(True)
        self.segment_list.clear()
        for index, segment in enumerate(self.segments):
            start = self._point_text(segment["start"])
            end = self._point_text(segment["end"], reversed_bundle=True)
            self.segment_list.addItem(f"{index + 1}: {start} -> {end}")
        if 0 <= current < len(self.segments):
            self.segment_list.setCurrentRow(current)
        self.segment_list.blockSignals(False)
        self._update_detail()
        self._update_name_placeholder()

    def _name_component(self, obj):
        if is_bundle_segment(obj):
            point = obj.Start
            text = point.Label if point else (obj.Label or obj.Name or "bundle")
        else:
            text = obj.Label or obj.Name or "point"
        component = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
        return component or "point"

    def _auto_name_from_objects(self, start, end):
        return f"wire_{self._name_component(start)}_{self._name_component(end)}"

    def _suggested_wire_name(self):
        if not self.segments:
            return ""
        start = self._resolve(self.segments[0]["start"])
        end = self._resolve(self.segments[-1]["end"])
        if start is None or end is None:
            return ""
        return self._auto_name_from_objects(start, end)

    def _auto_wire_name(self, links):
        if len(links) < 2:
            return ""
        return self._auto_name_from_objects(links[0], links[-1])

    def _update_name_placeholder(self):
        suggested = self._suggested_wire_name()
        self.name_edit.setPlaceholderText(
            suggested or "Auto: wire_<start>_<end>"
        )

    @staticmethod
    def _safe_object_name(name):
        safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
        safe = re.sub(r"_+", "_", safe).strip("_")
        if not safe:
            safe = "Wire"
        if safe[0].isdigit():
            safe = "Wire_" + safe
        return safe[:64]

    def _update_detail(self, *args):
        row = self._current_row()
        has_segment = row is not None
        self.btn_pick_start.setEnabled(has_segment)
        self.btn_pick_end.setEnabled(has_segment)
        self.btn_remove.setEnabled(has_segment)
        self.btn_up.setEnabled(has_segment and row > 0)
        self.btn_down.setEnabled(has_segment and row < len(self.segments) - 1)
        self.btn_swap.setEnabled(has_segment)

        if not has_segment:
            self._update_point_label(self.start_label, None)
            self._update_point_label(self.end_label, None, reversed_bundle=True)
            return

        segment = self.segments[row]
        self._update_point_label(self.start_label, segment["start"])
        self._update_point_label(
            self.end_label, segment["end"], reversed_bundle=True
        )

    def _update_point_label(self, label, ref, reversed_bundle=False):
        label.setText(self._point_text(ref, reversed_bundle))
        if self._resolve(ref) is None:
            label.setCursor(QtCore.Qt.ArrowCursor)
            label.setStyleSheet("")
            label.setToolTip("")
        else:
            label.setCursor(QtCore.Qt.PointingHandCursor)
            label.setStyleSheet("color: #1a5fb4; text-decoration: underline;")
            label.setToolTip(
                "Click to select this point reference or bundle segment in the scene"
            )

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

    def _reference_object(self, ref, role, index):
        obj = self._resolve(ref)
        if obj is None:
            raise ValueError(
                f"Segment {index + 1} needs a {role} reference."
            )
        return obj

    def _collect_segments(self, document):
        if not self.segments:
            raise ValueError("Add at least one segment first.")

        segments = []
        links = []
        for index, segment in enumerate(self.segments):
            start_obj = self._reference_object(segment["start"], "start", index)
            end_obj = self._reference_object(segment["end"], "end", index)
            if start_obj.Document is not document or end_obj.Document is not document:
                raise ValueError(
                    "All references must belong to the same document as the cable."
                )
            if not is_bundle_segment(start_obj) and not is_bundle_segment(end_obj):
                start = start_obj.getGlobalPlacement().Base
                end = end_obj.getGlobalPlacement().Base
                if (end - start).Length < 1e-9:
                    raise ValueError(
                        f"Segment {index + 1} has identical start and end points."
                    )
                segments.append(Segment(start, end))
            links.extend([start_obj, end_obj])
        return segments, links

    def _target_document(self):
        if self.cable is not None:
            try:
                if self.cable.isValid():
                    return self.cable.Document
            except Exception:
                pass
        document = App.ActiveDocument
        if document is None:
            document = App.newDocument("Wire")
        return document

    def _cable_is_usable(self, document):
        try:
            return (
                self.cable is not None
                and self.cable.isValid()
                and self.cable.Document is document
            )
        except Exception:
            return False

    def create_path(self):
        self._build_cable = False
        self._generate(make_cable=False)

    def create_cable(self):
        self._build_cable = True
        self._generate(make_cable=True)

    def _generate(self, make_cable, live=False):
        self._stop_picking()
        self._build_cable = make_cable
        document = self._target_document()

        try:
            _, links = self._collect_segments(document)
        except ValueError as error:
            if live:
                self.status_label.setStyleSheet("color: #b00000;")
                self.status_label.setText(str(error))
            else:
                QtGui.QMessageBox.warning(self.form, "WirePlugin", str(error))
            return

        diameter = self.diameter_spin.value()
        min_bend_radius = self.min_bend_spin.value()
        harness = find_harness_for_segments(links)
        wire_name = self.name_edit.text().strip()
        if not wire_name:
            wire_name = self._auto_wire_name(links)
        safe_name = self._safe_object_name(wire_name)

        try:
            if self._cable_is_usable(document):
                ensure_support_objects(self.cable)
                self.cable.Points = links
                update_cable_dependencies(self.cable)
                self._apply_cable_parameters(self.cable)
                self.cable.BuildCable = make_cable
                self.cable.Preview = False
                rename_cable(self.cable, wire_name)
            else:
                self.cable = None
                container = document.addObject(
                    "App::DocumentObjectGroup", safe_name + "_Group"
                )
                self.cable = create_wire_cable(
                    document,
                    links,
                    diameter=diameter,
                    min_bend_radius=min_bend_radius,
                    container=container,
                    build_cable=make_cable,
                    name=safe_name,
                    label=wire_name,
                )
                self._apply_cable_parameters(self.cable)
                self.cable.Preview = False
                rename_cable(self.cable, wire_name)
        except Exception as error:
            if live:
                self.status_label.setStyleSheet("color: #b00000;")
                self.status_label.setText(str(error))
            else:
                QtGui.QMessageBox.critical(self.form, "WirePlugin", str(error))
            return

        if harness is not None:
            add_cable_to_harness(harness, self.cable)
        else:
            self.cable.Harness = None

        self.name_edit.setText(wire_name)
        document.recompute()
        self._update_button_labels()
        self._show_cable_status()

    def _show_cable_status(self):
        if self.cable is None:
            return
        try:
            status = self.cable.Status
        except Exception:
            status = ""
        self.status_label.setText(status)
        if status.startswith("Error:") or "WARNING" in status:
            self.status_label.setStyleSheet("color: #b00000;")
        else:
            self.status_label.setStyleSheet("")

    def reject(self):
        self._stop_picking()
        self._remove_selection_observer()
        Gui.Control.closeDialog()
        try:
            from .WireSelection import clear_tool_selection, schedule_clear_tool_selection

            clear_tool_selection(self.cable)
            schedule_clear_tool_selection(self.cable)
        except Exception:
            pass

    def accept(self):
        self._stop_picking()
        self._remove_selection_observer()
        Gui.Control.closeDialog()
        try:
            from .WireSelection import clear_tool_selection, schedule_clear_tool_selection

            clear_tool_selection(self.cable)
            schedule_clear_tool_selection(self.cable)
        except Exception:
            pass
