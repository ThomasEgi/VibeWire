"""Task panel for editing cable end tip settings."""

import FreeCADGui as Gui
from PySide import QtCore, QtGui

from . import FerruleData
from .WireTip import TIP_OFFSET_MARGIN, WireTipProxy


class WireTipTaskPanel:
    """Edit the cable end treatment and its dimensions."""

    def __init__(self, tip):
        WireTipProxy._add_properties(tip)
        self.tip = tip
        self.cable = self._find_cable(tip)
        if self.cable is not None:
            from .WireCable import ensure_core_properties

            ensure_core_properties(self.cable)
        self._updating = False
        self._cross_section = (
            FerruleData.cross_section_for_size(
                getattr(self.cable, "WireSizeMM2", 0.0)
            )
            if self.cable is not None
            else None
        )
        self._original = self._snapshot()
        self._segment_length = self._tip_segment_length(tip, self.cable)
        self._max_offset = max(0.0, self._segment_length - TIP_OFFSET_MARGIN)

        self.form = QtGui.QWidget()
        self.form.setWindowTitle("Cable Tip")
        layout = QtGui.QVBoxLayout(self.form)

        cable_label = self.cable.Label if self.cable is not None else "(unknown cable)"
        end_label = getattr(tip, "End", "Start")
        info = QtGui.QLabel(f"Cable: {cable_label}    End: {end_label}")
        info.setWordWrap(True)
        layout.addWidget(info)

        type_form = QtGui.QFormLayout()
        self.type_combo = QtGui.QComboBox()
        self.type_combo.addItems(["Length offset", "Stripped wire", "Ferrule"])
        self.type_combo.setCurrentText(getattr(tip, "TipType", "Length offset"))
        type_form.addRow("Tip type:", self.type_combo)
        layout.addLayout(type_form)

        context_form = QtGui.QFormLayout()
        context_form.addRow(
            "Tip segment length:",
            QtGui.QLabel(f"{max(0.0, self._segment_length):.2f} mm"),
        )
        layout.addLayout(context_form)

        self.stack = QtGui.QStackedWidget()
        self.stack.addWidget(self._build_offset_page())
        self.stack.addWidget(self._build_stripped_page())
        self.stack.addWidget(self._build_ferrule_page())
        layout.addWidget(self.stack)
        self.stack.setCurrentIndex(
            {"Length offset": 0, "Stripped wire": 1, "Ferrule": 2}.get(
                self.type_combo.currentText(), 0
            )
        )

        self._timer = QtCore.QTimer(self.form)
        self._timer.setSingleShot(True)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._apply_live)

        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self.offset_spin.valueChanged.connect(lambda _value: self._schedule())
        self.stripped_spin.valueChanged.connect(lambda _value: self._schedule())
        self.ferrule_type_combo.currentIndexChanged.connect(
            self._on_ferrule_type_changed
        )
        self.ferrule_variant_combo.currentIndexChanged.connect(
            self._on_ferrule_variant_changed
        )
        self.ferrule_color_combo.currentIndexChanged.connect(
            self._on_ferrule_color_changed
        )

        self._update_ferrule_details()

    def _build_offset_page(self):
        page = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(page)
        form = QtGui.QFormLayout()
        self.offset_spin = QtGui.QDoubleSpinBox()
        self.offset_spin.setRange(0.0, self._max_offset)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSingleStep(1.0)
        self.offset_spin.setSuffix(" mm")
        self.offset_spin.setValue(
            min(max(0.0, self.tip.LengthOffset.Value), self._max_offset)
        )
        form.addRow("Length offset:", self.offset_spin)
        layout.addLayout(form)
        hint = QtGui.QLabel(
            "Shortens the visible cable at this end, for example where a "
            "connector covers it. Changes update the cable live."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_stripped_page(self):
        page = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(page)
        form = QtGui.QFormLayout()

        self.stripped_spin = QtGui.QDoubleSpinBox()
        self.stripped_spin.setRange(0.0, self._max_offset)
        self.stripped_spin.setDecimals(2)
        self.stripped_spin.setSingleStep(1.0)
        self.stripped_spin.setSuffix(" mm")
        self.stripped_spin.setValue(
            min(max(0.0, self.tip.StrippedLength.Value), self._max_offset)
        )
        form.addRow("Stripped length:", self.stripped_spin)
        layout.addLayout(form)

        hint = QtGui.QLabel(
            "Removes the insulation over the stripped length and shows the "
            "conductive core. Cable diameter and core size are read from the "
            "wire object (select a standard wire size in the cable tool for "
            "standard cores)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_ferrule_page(self):
        page = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(page)
        form = QtGui.QFormLayout()

        self.ferrule_size_label = QtGui.QLabel("")
        form.addRow("Cross-section:", self.ferrule_size_label)
        self.ferrule_type_combo = QtGui.QComboBox()
        form.addRow("Ferrule type:", self.ferrule_type_combo)
        self.ferrule_variant_combo = QtGui.QComboBox()
        form.addRow("Variant:", self.ferrule_variant_combo)
        self.ferrule_color_combo = QtGui.QComboBox()
        form.addRow("Sleeve code:", self.ferrule_color_combo)

        color_widget = QtGui.QWidget()
        color_layout = QtGui.QHBoxLayout(color_widget)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.ferrule_color_swatch = QtGui.QLabel()
        self.ferrule_color_swatch.setFixedSize(24, 24)
        self.ferrule_color_text = QtGui.QLabel("")
        color_layout.addWidget(self.ferrule_color_swatch)
        color_layout.addWidget(self.ferrule_color_text, 1)
        form.addRow("Sleeve color:", color_widget)

        self.ferrule_l1_label = QtGui.QLabel("")
        self.ferrule_strip_label = QtGui.QLabel("")
        form.addRow("Tip length:", self.ferrule_l1_label)
        form.addRow("Stripped length:", self.ferrule_strip_label)
        layout.addLayout(form)

        self.ferrule_warning = QtGui.QLabel("")
        self.ferrule_warning.setWordWrap(True)
        self.ferrule_warning.setStyleSheet("color: #b00000;")
        layout.addWidget(self.ferrule_warning)

        hint = QtGui.QLabel(
            "Ferrules are matched to the standard wire size selected in the "
            "cable tool. The tip selects the ferrule type and, if needed, the "
            "variant. Sleeve color comes from the DIN/T/W code for this size."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        self._ferrule_type_entries = []
        self._populate_ferrule_controls()
        return page

    def _populate_ferrule_controls(self):
        self._updating = True
        try:
            self.ferrule_type_combo.clear()
            self.ferrule_variant_combo.clear()
            self.ferrule_color_combo.clear()
            self._ferrule_type_entries = []
            if self._cross_section is None:
                self.ferrule_size_label.setText(
                    "No standard wire size selected (use the cable tool)"
                )
                self.ferrule_type_combo.setEnabled(False)
                self.ferrule_variant_combo.setEnabled(False)
                self.ferrule_color_combo.setEnabled(False)
                self._update_ferrule_details()
                return

            entry = self._cross_section
            self.ferrule_size_label.setText(FerruleData.size_label(entry))
            for type_entry in FerruleData.ferrule_types(entry):
                self.ferrule_type_combo.addItem(
                    FerruleData.ferrule_type_label(type_entry),
                    type_entry["type"],
                )
                self._ferrule_type_entries.append(type_entry)

            wanted_type = getattr(self.tip, "FerruleType", "tube")
            type_index = self.ferrule_type_combo.findData(wanted_type)
            self.ferrule_type_combo.setCurrentIndex(
                type_index if type_index >= 0 else 0
            )
            self.ferrule_type_combo.setEnabled(bool(self._ferrule_type_entries))

            systems = sorted(entry.get("color_codes", {}))
            for system in systems:
                code = entry["color_codes"][system]
                info = FerruleData.color_info(code) or {}
                label = f"{system} — {code} ({info.get('name', code)})"
                self.ferrule_color_combo.addItem(label, system)
            wanted_system = getattr(self.tip, "FerruleColorSystem", "DIN")
            system_index = self.ferrule_color_combo.findData(wanted_system)
            self.ferrule_color_combo.setCurrentIndex(
                system_index if system_index >= 0 else 0
            )
            self.ferrule_color_combo.setEnabled(bool(systems))
            self._populate_ferrule_variants()
        finally:
            self._updating = False

    def _selected_ferrule_type(self):
        index = self.ferrule_type_combo.currentIndex()
        if 0 <= index < len(self._ferrule_type_entries):
            return self._ferrule_type_entries[index]
        return None

    def _populate_ferrule_variants(self):
        self._updating = True
        try:
            self.ferrule_variant_combo.clear()
            type_entry = self._selected_ferrule_type()
            if type_entry is None:
                self.ferrule_variant_combo.setEnabled(False)
                self._update_ferrule_details()
                return
            for variant_data in FerruleData.variants(type_entry):
                self.ferrule_variant_combo.addItem(
                    FerruleData.variant_label(variant_data)
                )
            self.ferrule_variant_combo.setEnabled(
                self.ferrule_variant_combo.count() > 0
            )
            index = int(getattr(self.tip, "FerruleVariant", 0))
            if index < 0 or index >= self.ferrule_variant_combo.count():
                index = 0
            self.ferrule_variant_combo.setCurrentIndex(index)
            self._update_ferrule_details()
        finally:
            self._updating = False

    def _update_ferrule_details(self):
        self.ferrule_l1_label.setStyleSheet("")
        type_entry = self._selected_ferrule_type()
        if type_entry is None:
            self.ferrule_l1_label.setText("—")
            self.ferrule_strip_label.setText("—")
            self.ferrule_warning.setText("")
            self.ferrule_color_text.setText("")
            self.ferrule_color_swatch.setStyleSheet("")
            return

        variant_data = FerruleData.variant(
            type_entry, self.ferrule_variant_combo.currentIndex()
        )
        if variant_data is None:
            self.ferrule_l1_label.setText("—")
            self.ferrule_strip_label.setText("—")
            self.ferrule_warning.setText("")
            return

        tip_length = variant_data["l1_mm"]
        strip_length = FerruleData.strip_length(variant_data)
        self.ferrule_l1_label.setText(f"{tip_length:.2f} mm")
        self.ferrule_strip_label.setText(f"{strip_length:.2f} mm")

        system = self.ferrule_color_combo.currentData()
        info, code = FerruleData.color_for_system(self._cross_section, system)
        if info:
            self.ferrule_color_swatch.setStyleSheet(
                f"background-color: {info['hex']}; border: 1px solid #000;"
            )
            self.ferrule_color_text.setText(f"{code} ({info['name']})")
        else:
            self.ferrule_color_swatch.setStyleSheet("")
            self.ferrule_color_text.setText("")

        warnings = []
        if tip_length > self._segment_length + 1e-9:
            self.ferrule_l1_label.setStyleSheet("color: #b00000;")
            warnings.append(
                f"Tip length exceeds the available tip segment "
                f"({self._segment_length:.2f} mm). Increase the tip-segment "
                "length."
            )
        if not variant_data.get("conforming", True):
            warnings.append("This variant is marked as not conforming to the standard.")
        if self.cable is not None:
            try:
                core_diameter = self.cable.CoreDiameter.Value
            except Exception:
                core_diameter = 0.0
            if core_diameter > variant_data["d1_mm"] + 1e-9:
                warnings.append(
                    f"Core diameter {core_diameter:.2f} mm exceeds the "
                    f"ferrule inner diameter d1 {variant_data['d1_mm']:.2f} mm."
                )
        self.ferrule_warning.setText(" ".join(warnings))

    def _on_ferrule_type_changed(self, _index):
        if self._updating:
            return
        type_entry = self._selected_ferrule_type()
        if type_entry is None:
            return
        self.tip.FerruleType = type_entry["type"]
        self.tip.FerruleVariant = 0
        self._populate_ferrule_variants()
        self._schedule()

    def _on_ferrule_variant_changed(self, index):
        if self._updating:
            return
        self.tip.FerruleVariant = max(0, index)
        self._update_ferrule_details()
        self._schedule()

    def _on_ferrule_color_changed(self, _index):
        if self._updating:
            return
        system = self.ferrule_color_combo.currentData()
        if system:
            self.tip.FerruleColorSystem = system
        self._update_ferrule_details()
        self._schedule()

    def _schedule(self):
        self._timer.start()

    def _on_type_changed(self, text):
        if self._updating:
            return
        self.stack.setCurrentIndex(
            {"Length offset": 0, "Stripped wire": 1, "Ferrule": 2}.get(text, 0)
        )
        self._schedule()

    def _apply_live(self):
        if self.tip is None or not self.tip.isValid():
            return
        self.tip.TipType = self.type_combo.currentText()
        self.tip.LengthOffset = min(
            self.offset_spin.value(), self._max_offset
        )
        self.tip.StrippedLength = min(
            self.stripped_spin.value(), self._max_offset
        )
        if self._cross_section is not None:
            type_entry = self._selected_ferrule_type()
            if type_entry is not None:
                self.tip.FerruleType = type_entry["type"]
            variant_index = self.ferrule_variant_combo.currentIndex()
            if variant_index >= 0:
                self.tip.FerruleVariant = variant_index
            system = self.ferrule_color_combo.currentData()
            if system:
                self.tip.FerruleColorSystem = system
        self._update_ferrule_details()
        if self.tip.Document is not None:
            self.tip.Document.recompute()

    @staticmethod
    def _find_cable(tip):
        for parent in tip.InList:
            if getattr(getattr(parent, "Proxy", None), "Type", None) == "WireCable":
                return parent
        return None

    @staticmethod
    def _tip_segment_length(tip, cable):
        if cable is None:
            return 0.0
        end = getattr(tip, "End", "Start")
        property_name = "StartTipLength" if end == "Start" else "EndTipLength"
        if property_name not in cable.PropertiesList:
            return 0.0
        try:
            return max(0.0, getattr(cable, property_name).Value)
        except Exception:
            return 0.0

    def _snapshot(self):
        return {
            "TipType": getattr(self.tip, "TipType", "Length offset"),
            "LengthOffset": self.tip.LengthOffset.Value,
            "StrippedLength": self.tip.StrippedLength.Value,
            "FerruleType": getattr(self.tip, "FerruleType", "tube"),
            "FerruleVariant": getattr(self.tip, "FerruleVariant", 0),
            "FerruleColorSystem": getattr(self.tip, "FerruleColorSystem", "DIN"),
        }

    def _restore(self, values):
        try:
            self.tip.TipType = values["TipType"]
            self.tip.LengthOffset = values["LengthOffset"]
            self.tip.StrippedLength = values["StrippedLength"]
            self.tip.FerruleType = values["FerruleType"]
            self.tip.FerruleVariant = values["FerruleVariant"]
            self.tip.FerruleColorSystem = values["FerruleColorSystem"]
        except Exception:
            pass

    def getStandardButtons(self):
        return QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel

    def isAllowedAlterSelection(self):
        return False

    def isAllowedAlterView(self):
        return False

    def accept(self):
        self._timer.stop()
        self._apply_live()
        Gui.Control.closeDialog()

    def reject(self):
        self._timer.stop()
        if self.tip is not None and self.tip.isValid():
            self._restore(self._original)
            if self.tip.Document is not None:
                self.tip.Document.recompute()
        Gui.Control.closeDialog()
