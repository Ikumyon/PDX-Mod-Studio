import os
from PySide6.QtWidgets import QWidget, QListWidgetItem, QHBoxLayout, QLabel, QPushButton
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize
from core.dialog.settings import settings_manager
from core.i18n import tr

class HomeTabWidget(QWidget):
    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # UIのロード
        loader = QUiLoader()
        ui_path = os.path.join(self.base_dir, "ui", "widgets", "HomeTab.ui")
        ui_file = QFile(ui_path)
        if ui_file.open(QFile.ReadOnly):
            self.ui = loader.load(ui_file, self)
            ui_file.close()
            
            # レイアウトにロードしたウィジェットを追加
            layout = self.layout()
            if not layout:
                from PySide6.QtWidgets import QVBoxLayout
                layout = QVBoxLayout(self)
                layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.ui)
            
            # 各コントロールの取得
            self.newProjectButton = self.ui.findChild(QPushButton, "newProjectButton")
            self.openProjectButton = self.ui.findChild(QPushButton, "openProjectButton")
            self.importModButton = self.ui.findChild(QPushButton, "importModButton")
            self.recentProjectsList = self.ui.findChild(object, "recentProjectsList")
            
            # イベントバインド
            # newProjectButton は指示により「今のところ何もしない」
            
            if self.openProjectButton:
                # プロジェクトを開く (メニューのファイル->プロジェクトを開くと同様にactionOpenProjectをトリガー)
                action = self.parent_window.findChild(object, "actionOpenProject")
                if action:
                    self.openProjectButton.clicked.connect(action.trigger)
            
            if self.importModButton:
                # MOD取り込み (プロジェクトツリーのMODフォルダーを開くダイアログと同じ挙動)
                if hasattr(self.parent_window, "project_tree") and self.parent_window.project_tree:
                    self.importModButton.clicked.connect(self.parent_window.project_tree.on_open_folder_clicked)
                
            # 最近開いたプロジェクトのダブルクリックでオープン
            if self.recentProjectsList:
                self.recentProjectsList.itemDoubleClicked.connect(self.on_recent_project_clicked)
                
            self.update_recent_projects()
        else:
            print(f"Could not open HomeTab.ui: {ui_path}")

    def update_recent_projects(self):
        if not self.recentProjectsList:
            return
        self.recentProjectsList.clear()
        
        recent = settings_manager.get("recent_projects", [])
        if not recent:
            return
            
        for proj in recent:
            if not isinstance(proj, dict):
                continue
            name = proj.get("name", "Unknown")
            path = proj.get("path", "")
            game = proj.get("game", "")
            date = proj.get("date", "")
            
            # リストアイテムの作成
            item = QListWidgetItem(self.recentProjectsList)
            item.setData(Qt.ItemDataRole.UserRole, path)
            
            # カスタムウィジェットの作成（1行内に名前、ゲーム、日付、開くボタンを横並びにする）
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(10, 5, 10, 5)
            layout.setSpacing(20)
            
            name_label = QLabel(name)
            name_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(name_label)
            
            layout.addStretch()
            
            game_label = QLabel(game.upper() if game else "REFERENCE")
            game_label.setStyleSheet("color: #888888;")
            layout.addWidget(game_label)
            
            date_label = QLabel(date)
            date_label.setStyleSheet("color: #888888;")
            layout.addWidget(date_label)
            
            open_btn = QPushButton("Open")
            open_btn.setFixedWidth(60)
            # クリックイベントのバインド
            open_btn.clicked.connect(lambda checked=False, p=path: self.open_project(p))
            layout.addWidget(open_btn)
            
            item.setSizeHint(widget.sizeHint())
            self.recentProjectsList.addItem(item)
            self.recentProjectsList.setItemWidget(item, widget)

    def on_recent_project_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.open_project(path)

    def open_project(self, path):
        if not path or not os.path.exists(path):
            self.parent_window.statusBar().showMessage(tr("Home", "プロジェクトが存在しません: {path}").format(path=path), 5000)
            return
        
        # project_ioで開く
        if hasattr(self.parent_window, "project_io") and self.parent_window.project_io:
            if os.path.isdir(path):
                # フォルダの場合（直接ロード）
                self.parent_window.project_io.project_tree.load_project(path)
            else:
                # プロジェクトファイルの場合
                self.parent_window.project_io.open_project_file(path)
            self.close_home_tab()

    def close_home_tab(self):
        # 現在のタブの中から home: のパスを持つものを探して閉じる
        if hasattr(self.parent_window, "editorTabs") and self.parent_window.editorTabs:
            for i in range(self.parent_window.editorTabs.count()):
                widget = self.parent_window.editorTabs.widget(i)
                if widget == self or getattr(widget, "file_path", "") == "home:":
                    self.parent_window.editorTabs.tabCloseRequested.emit(i)
                    break
