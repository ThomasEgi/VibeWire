"""Task panel for editing cable end tip settings."""

import math
import re

import FreeCADGui as Gui
from PySide import QtCore, QtGui

from .WireTip import TIP_OFFSET_MARGIN, WireTipProxy

NUMBER_PATTERN = re.compile(
    r"^\s*([0-9]+(?:[.,][0-9]*)?)\s*(mm\s*\^?2|mm2|mm²|mm)?\s*$",
    re.IGNORECASE,
)


class WireTipTaskPanel:
    """Edit the cable end treatment and its dimensions."""

    PRESETS = (
        ("1.0 mm²", 1.0),
        ("1.5 mm²", 1.5),
        ("2.5 mm²", 2.5),
    )

    def __init__(self, tip):
        WireTipProxy._add_properties(tip)
        self.tip = tip
        self.cable = self._find_cable(tip)
        if self.cable is not None:
            from .WireCable import ensure_core_properties

            ensure_core_properties(self.cable)
        self._updating = False
        self._original = self._snapshot()
        self._segment_length = self._tip_segment_length(tip, self.cable)
        self._max_offset = max(0.0, self._segment_length - TIP_OFFSET_MARGIN)
        self._max_core_diameter = (
            max(0.0, self.cable.Diameter.Value) if self.cable is not None else 0.0
        )

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
        self.type_combo.addItems(["Length offset", "Stripped wire"])
        self.type_combo.setCurrentText(getattr(tip, "TipType", "Length offset"))
        type_form.addRow("Tip type:", self.type_combo)
        layout.addLayout(type_form)

        context_form = QtGui.QFormLayout()
        context_form.addRow(
            "Tip segment length:",
            QtGui.QLabel(f"{max(0.0, self._segment_length):.2f} mm"),
        )
        context_form.addRow(
            "Maximum length setting:",
            QtGui.QLabel(f"{max(0.0, self._max_offset):.2f} mm"),
        )
        layout.addLayout(context_form)

        self.stack = QtGui.QStackedWidget()
        self.stack.addWidget(self._build_offset_page())
        self.stack.addWidget(self._build_stripped_page())
        layout.addWidget(self.stack)
        self.stack.setCurrentIndex(0 if self.type_combo.currentText() == "Length offset" else 1)

        self._timer = QtCore.QTimer(self.form)
        self._timer.setSingleShot(True)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._apply_live)

        self.type_combo.currentTextChanged.connect(self._on_type_changed)
        self.offset_spin.valueChanged.connect(lambda _value: self._schedule())
        self.stripped_spin.valueChanged.connect(lambda _value: self._schedule())
        self.core_edit.textChanged.connect(self._on_core_text_changed)
        self.core_unit.currentTextChanged.connect(self._on_unit_changed)
        self.common_combo.currentTextChanged.connect(self._on_common_changed)

        self._set_core_controls(update_text=True)
        self._update_core_display()

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

        self.core_size_widget = QtGui.QWidget()
        core_layout = QtGui.QHBoxLayout(self.core_size_widget)
        core_layout.setContentsMargins(0, 0, 0, 0)
        self.core_edit = QtGui.QLineEdit()
        self.core_unit = QtGui.QComboBox()
        self.core_unit.addItems(["mm", "mm²"])
        core_layout.addWidget(self.core_edit, 1)
        core_layout.addWidget(self.core_unit)
        form.addRow("Core size:", self.core_size_widget)

        self.common_combo = QtGui.QComboBox()
        self.common_combo.addItems(["Custom"] + [label for label, _ in self.PRESETS])
        form.addRow("Common size:", self.common_combo)

        self.core_diameter_label = QtGui.QLabel("")
        form.addRow("Core diameter:", self.core_diameter_label)
        layout.addLayout(form)

        self.core_warning = QtGui.QLabel("")
        self.core_warning.setWordWrap(True)
        self.core_warning.setStyleSheet("color: #b00000;")
        layout.addWidget(self.core_warning)

        hint = QtGui.QLabel(
            "Removes the insulation over the stripped length and shows the "
            "conductive core. The core size is shared by both cable ends and is "
            "limited to the cable diameter. Select a common size or enter a "
            "diameter/area; typed units switch the mm / mm² selector."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _set_core_controls(self, update_text=False):
        if self.cable is None:
            return
        mode = getattr(self.cable, "CoreSizeMode", "Area")
        if mode == "Diameter":
            value = getattr(self.cable, "CoreDiameter").Value
            unit = "mm"
        else:
            value = getattr(self.cable, "CoreArea")
            unit = "mm²"
        self._updating = True
        try:
            self.core_unit.setCurrentText(unit)
            if update_text:
                self.core_edit.setText(self._format_number(value))
            area = (
                math.pi * (value / 2.0) ** 2
                if mode == "Diameter"
                else max(0.0, value)
            )
            self.common_combo.setCurrentText(self._preset_for_area(area))
        finally:
            self._updating = False

    def _set_core_size(self, mode, value, update_text=True):
        if self.cable is None:
            return
        value = max(0.0, value)
        if mode == "Diameter":
            diameter = value
            area = math.pi * (diameter / 2.0) ** 2
        else:
            area = value
            diameter = 2.0 * math.sqrt(area / math.pi)
        self._updating = True
        try:
            self.cable.CoreSizeMode = mode
            self.cable.CoreArea = area
            self.cable.CoreDiameter = diameter
        finally:
            self._updating = False
        self._set_core_controls(update_text=update_text)
        self._update_core_display()

    @staticmethod
    def _format_number(value):
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text or "0"

    @classmethod
    def _preset_for_area(cls, area):
        for label, preset_area in cls.PRESETS:
            if abs(area - preset_area) < 1e-4:
                return label
        return "Custom"

    def _parse_core_size(self, text):
        if self.cable is None:
            return None
        match = NUMBER_PATTERN.match(text)
        if match is None:
            return None
        value = float(match.group(1).replace(",", "."))
        unit = (match.group(2) or "").lower().replace(" ", "")
        current_mode = getattr(self.cable, "CoreSizeMode", "Area")
        if unit in ("mm²", "mm2", "mm^2", "mm^2"):
            mode = "Area"
        elif unit == "mm":
            mode = "Diameter"
        else:
            mode = current_mode
        return mode, value

    def _schedule(self):
        self._timer.start()

    def _on_type_changed(self, text):
        if self._updating:
            return
        self.stack.setCurrentIndex(0 if text == "Length offset" else 1)
        self._schedule()

    def _on_core_text_changed(self, _text):
        if not self._updating:
            self._schedule()

    def _on_unit_changed(self, text):
        if self._updating or self.cable is None:
            return
        mode = "Area" if text == "mm²" else "Diameter"
        current_mode = getattr(self.cable, "CoreSizeMode", "Area")
        if mode == current_mode:
            return
        diameter = max(0.0, getattr(self.cable, "CoreDiameter").Value)
        if mode == "Area":
            self._set_core_size("Area", math.pi * (diameter / 2.0) ** 2)
        else:
            self._set_core_size("Diameter", diameter)
        self._schedule()

    def _on_common_changed(self, text):
        if self._updating or text == "Custom":
            return
        for label, area in self.PRESETS:
            if label == text:
                self._set_core_size("Area", area)
                self._schedule()
                return

    def _apply_live(self):
        if self.tip is None or not self.tip.isValid():
            return
        tip_type = self.type_combo.currentText()
        self.tip.TipType = tip_type
        self.tip.LengthOffset = min(
            self.offset_spin.value(), self._max_offset
        )
        self.tip.StrippedLength = min(
            self.stripped_spin.value(), self._max_offset
        )

        parsed = self._parse_core_size(self.core_edit.text())
        if parsed is not None:
            mode, value = parsed
            current_mode = getattr(self.cable, "CoreSizeMode", "Area")
            current_value = (
                getattr(self.cable, "CoreDiameter").Value
                if current_mode == "Diameter"
                else getattr(self.cable, "CoreArea")
            )
            if mode != current_mode or abs(current_value - value) > 1e-9:
                self._set_core_size(mode, value, update_text=False)
            if mode == "Area":
                self._set_unit_and_common("mm²", value)
            else:
                self._set_unit_and_common("mm", math.pi * (value / 2.0) ** 2)

        self._update_core_display()
        if self.tip.Document is not None:
            self.tip.Document.recompute()

    def _set_unit_and_common(self, unit, area):
        self._updating = True
        try:
            self.core_unit.setCurrentText(unit)
            self.common_combo.setCurrentText(self._preset_for_area(area))
        finally:
            self._updating = False

    def _update_core_display(self):
        requested = 0.0
        if self.cable is not None:
            try:
                requested = max(0.0, getattr(self.cable, "CoreDiameter").Value)
            except Exception:
                pass
        if self._max_core_diameter > 0.0:
            effective = min(requested, self._max_core_diameter)
        else:
            effective = requested
        self.core_diameter_label.setText(f"{effective:.2f} mm")
        if self._max_core_diameter > 0.0 and requested > self._max_core_diameter + 1e-9:
            self.core_warning.setText(
                f"Core diameter limited to cable diameter "
                f"{self._max_core_diameter:.2f} mm."
            )
        else:
            self.core_warning.setText("")

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
        snapshot = {
            "TipType": getattr(self.tip, "TipType", "Length offset"),
            "LengthOffset": self.tip.LengthOffset.Value,
            "StrippedLength": self.tip.StrippedLength.Value,
        }
        if self.cable is not None:
            snapshot.update(
                {
                    "CoreSizeMode": getattr(self.cable, "CoreSizeMode", "Area"),
                    "CoreArea": getattr(self.cable, "CoreArea", 1.0),
                    "CoreDiameter": getattr(self.cable, "CoreDiameter").Value,
                }
            )
        return snapshot

    def _restore(self, values):
        try:
            self.tip.TipType = values["TipType"]
            self.tip.LengthOffset = values["LengthOffset"]
            self.tip.StrippedLength = values["StrippedLength"]
            if self.cable is not None:
                self.cable.CoreSizeMode = values["CoreSizeMode"]
                self.cable.CoreArea = values["CoreArea"]
                self.cable.CoreDiameter = values["CoreDiameter"]
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
