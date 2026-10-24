"""Cable creation task panel."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtGui, QtCore
from WireCreator import WireCreator, Segment


class CableTaskPanel:
    def __init__(self):
        self.form = QtGui.QWidget()
        self.form.setWindowTitle("Create Cable")
        self.layout = QtGui.QVBoxLayout(self.form)

        self.segments = []

        self.listWidget = QtGui.QListWidget()
        self.layout.addWidget(self.listWidget)

        btnLayout = QtGui.QHBoxLayout()
        self.btnAdd = QtGui.QPushButton("Add Segment")
        self.btnRemove = QtGui.QPushButton("Remove")
        self.btnUp = QtGui.QPushButton("Move Up")
        self.btnDown = QtGui.QPushButton("Move Down")
        btnLayout.addWidget(self.btnAdd)
        btnLayout.addWidget(self.btnRemove)
        btnLayout.addWidget(self.btnUp)
        btnLayout.addWidget(self.btnDown)
        self.layout.addLayout(btnLayout)

        self.btnCreate = QtGui.QPushButton("Create Cable Geometry")
        self.btnClose = QtGui.QPushButton("Cancel / Close")
        self.layout.addWidget(self.btnCreate)
        self.layout.addWidget(self.btnClose)

        self.btnAdd.clicked.connect(self.addSegment)
        self.btnRemove.clicked.connect(self.removeSegment)
        self.btnUp.clicked.connect(self.moveUp)
        self.btnDown.clicked.connect(self.moveDown)
        self.btnCreate.clicked.connect(self.createCable)
        self.btnClose.clicked.connect(self.reject)

        self.updateList()

    def updateList(self):
        self.listWidget.clear()
        for i, seg in enumerate(self.segments):
            self.listWidget.addItem(
                f"{i + 1}: ({seg.start.x:.3f}, {seg.start.y:.3f}, {seg.start.z:.3f}) -> "
                f"({seg.end.x:.3f}, {seg.end.y:.3f}, {seg.end.z:.3f})"
            )

    def addSegment(self):
        dlg = QtGui.QDialog(self.form)
        dlg.setWindowTitle("Add Segment")
        layout = QtGui.QFormLayout(dlg)

        sx, sy, sz = QtGui.QDoubleSpinBox(dlg), QtGui.QDoubleSpinBox(dlg), QtGui.QDoubleSpinBox(dlg)
        ex, ey, ez = QtGui.QDoubleSpinBox(dlg), QtGui.QDoubleSpinBox(dlg), QtGui.QDoubleSpinBox(dlg)
        for s in [sx, sy, sz, ex, ey, ez]:
            s.setRange(-100000.0, 100000.0)
            s.setDecimals(3)
            s.setSingleStep(1.0)

        layout.addRow("Start X", sx)
        layout.addRow("Start Y", sy)
        layout.addRow("Start Z", sz)
        layout.addRow("End X", ex)
        layout.addRow("End Y", ey)
        layout.addRow("End Z", ez)

        btns = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        layout.addRow(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec_():
            start = App.Vector(sx.value(), sy.value(), sz.value())
            end = App.Vector(ex.value(), ey.value(), ez.value())
            self.segments.append(Segment(start, end))
            self.updateList()

    def removeSegment(self):
        row = self.listWidget.currentRow()
        if row >= 0 and row < len(self.segments):
            del self.segments[row]
            self.updateList()

    def moveUp(self):
        row = self.listWidget.currentRow()
        if row > 0:
            self.segments[row - 1], self.segments[row] = self.segments[row], self.segments[row - 1]
            self.updateList()
            self.listWidget.setCurrentRow(row - 1)

    def moveDown(self):
        row = self.listWidget.currentRow()
        if row >= 0 and row < len(self.segments) - 1:
            self.segments[row + 1], self.segments[row] = self.segments[row], self.segments[row + 1]
            self.updateList()
            self.listWidget.setCurrentRow(row + 1)

    def createCable(self):
        if not self.segments:
            QtGui.QMessageBox.warning(self.form, "WirePlugin", "Add at least one segment.")
            return
        try:
            wc = WireCreator(min_bend_radius=12.0)
            wire = wc.create_wire(self.segments)
            cable = wc.make_cable(wire, diameter=4.0)
            doc = App.ActiveDocument
            if doc is None:
                doc = App.newDocument("Cable")

            part = doc.addObject("App::Part", "CablePart")
            part.Label = "CablePart"

            wire_obj = doc.addObject("Part::Feature", "Wire")
            wire_obj.Shape = wire
            part.addObject(wire_obj)

            if cable is not None:
                cable_obj = doc.addObject("Part::Feature", "Cable")
                cable_obj.Shape = cable
                try:
                    cable_obj.ViewObject.ShapeColor = (0.2, 0.45, 0.8)
                    cable_obj.ViewObject.Transparency = 20
                except Exception:
                    pass
                part.addObject(cable_obj)

            bad_objs = wc.visualize_bad_arcs(diameter=4.0)
            for bad_obj in bad_objs:
                try:
                    part.addObject(bad_obj)
                except Exception:
                    pass

            doc.recompute()
            try:
                Gui.SendMsgToActiveView("ViewFit")
            except Exception:
                pass
        except Exception as e:
            QtGui.QMessageBox.critical(self.form, "Error", str(e))

    def reject(self):
        Gui.Control.closeDialog()

    def accept(self):
        self.createCable()
        Gui.Control.closeDialog()
