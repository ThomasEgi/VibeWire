"""Commands for Wire Plugin."""
import FreeCAD
import FreeCADGui as Gui
from PySide import QtGui
import os

class RunWireTestCommand:
    def GetResources(self):
        return {
            'Pixmap': '',
            'MenuText': 'Run WireCreator Test',
            'ToolTip': 'Run test_wirecreator.py'
        }

    def Activated(self):
        try:
            plugin_dir = os.path.dirname(__file__)
            test_path = os.path.join(plugin_dir, 'test_wirecreator.py')
            if not os.path.exists(test_path):
                test_path = '/home/mx/opencaudetest/wireplugin/test_wirecreator.py'
            exec(open(test_path).read())
        except Exception as e:
            QtGui.QMessageBox.critical(None, "Error", str(e))

    def IsActive(self):
        return True

Gui.addCommand('WirePlugin_RunTest', RunWireTestCommand())


class CreateCableCommand:
    def GetResources(self):
        return {
            'Pixmap': '',
            'MenuText': 'Create Cable',
            'ToolTip': 'Create cable from segments'
        }

    def Activated(self):
        try:
            import sys
            import os
            plugin_dir = os.path.dirname(__file__)
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)
            from CableTaskPanel import CableTaskPanel
            panel = CableTaskPanel()
            Gui.Control.showDialog(panel)
        except Exception as e:
            from PySide import QtGui
            QtGui.QMessageBox.critical(None, "Error", str(e))

    def IsActive(self):
        return True

Gui.addCommand('WirePlugin_CreateCable', CreateCableCommand())
