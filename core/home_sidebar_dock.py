import os
from PySide6.QtWidgets import QDockWidget, QPushButton, QListWidget
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize
from PySide6.QtGui import QIcon, QPalette
from core.utils import load_svg_icon

class HomeSidebarDock:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        
        # UIのロード
        loader = QUiLoader()
        ui_path = os.path.join(self.base_dir, "ui", "docks", "home_sidebar_dock.ui")
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.ReadOnly):
            print(f"UIファイルを開けませんでした: {ui_path}")
            return
            
        self.dock_widget = loader.load(ui_file, parent_window)
        ui_file.close()
        
        if not self.dock_widget:
            return
            
        # UI要素の取得
        self.homeHeader = self.dock_widget.findChild(QPushButton, "homeHeader")
        self.homeSidebarList = self.dock_widget.findChild(QListWidget, "homeSidebarList")
        self.pluginHeader = self.dock_widget.findChild(QPushButton, "pluginHeader")
        self.pluginSidebarList = self.dock_widget.findChild(QListWidget, "pluginSidebarList")
        
        # toggleViewActionの設定（アクティビティバー用）
        view_action = self.dock_widget.toggleViewAction()
        
        # テーマのテキスト色を取得
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        
        # アイコンのロード
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        icon_path = os.path.join(icons_dir, "home-48.svg")
        icon = load_svg_icon(icon_path, text_color)
        view_action.setIcon(icon)
                
        view_action.setText("ホーム")

        if self.homeSidebarList:
            self.homeSidebarList.itemClicked.connect(self.on_item_clicked)

    def on_item_clicked(self, item):
        text = item.text()
        if text == "Home":
            if hasattr(self.parent_window, "open_home_tab"):
                self.parent_window.open_home_tab()
        elif text == "Dashboard":
            if hasattr(self.parent_window, "open_dashboard_tab"):
                self.parent_window.open_dashboard_tab()

    def get_widget(self):
        return self.dock_widget
