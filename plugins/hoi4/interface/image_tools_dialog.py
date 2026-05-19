import os
from PySide6.QtCore import QFile
from PySide6.QtWidgets import QDialog, QVBoxLayout
from PySide6.QtUiTools import QUiLoader

class ImageToolsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("画像編集ツール")
        
        loader = QUiLoader()
        base_dir = os.path.dirname(__file__)
        ui_path = os.path.join(base_dir, "image_tools_dialog.ui")
        
        file = QFile(ui_path)
        if file.open(QFile.OpenModeFlag.ReadOnly):
            self.ui = loader.load(file, self)
            file.close()
            
            if self.ui:
                self.resize(self.ui.size())
                layout = QVBoxLayout(self)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.addWidget(self.ui)
