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
