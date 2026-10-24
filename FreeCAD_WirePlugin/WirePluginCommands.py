"""Commands for Wire Plugin."""
import FreeCAD
import FreeCADGui as Gui
from PySide import QtGui

class RunWireTestCommand:
    def GetResources(self):
        return {
            'Pixmap': '',
            'MenuText': 'Run WireCreator Test',
            'ToolTip': 'Run test_wirecreator.py'
        }

    def Activated(self):
        try:
            path = FreeCAD.getUserAppDataDir()
            # Try local path
            import os
            test_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'test_wirecreator.py')
            if not os.path.exists(test_path):
                test_path = '/home/mx/opencaudetest/wireplugin/test_wirecreator.py'
            exec(open(test_path).read())
        except Exception as e:
            QtGui.QMessageBox.critical(None, "Error", str(e))

    def IsActive(self):
        return True

Gui.addCommand('WirePlugin_RunTest', RunWireTestCommand())
