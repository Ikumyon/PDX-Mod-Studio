import os
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QTreeWidgetItem, 
                             QVBoxLayout, QHBoxLayout, QMenu, QWidget, QLabel, 
                             QToolButton, QStyle)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize
from PySide6.QtGui import QIcon, QPalette, QAction
from core.utils import load_svg_icon

class ProjectTreeDock:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        
        # UIのロード
        loader = QUiLoader()
        ui_path = os.path.join(self.base_dir, "ui", "docks", "project_tree_dock.ui")
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.ReadOnly):
            print(f"UIファイルを開けませんでした: {ui_path}")
            return
            
        self.dock_widget = loader.load(ui_file, parent_window)
        ui_file.close()
        
        if not self.dock_widget:
            return
            
        # UI要素の取得
        self.openFolderButton = self.dock_widget.findChild(object, "openFolderButton")
        self.folderStack = self.dock_widget.findChild(object, "folderStack")
        self.modElementsTree = self.dock_widget.findChild(object, "modElementsTree")
        self.openEditorsHeader = self.dock_widget.findChild(object, "openEditorsHeader")
        self.openEditorsList = self.dock_widget.findChild(object, "openEditorsList")
        self.projectHeaderDisclosure = self.dock_widget.findChild(object, "projectHeaderDisclosure")
        self.searchLineEdit = self.dock_widget.findChild(object, "searchLineEdit")
        self.noFolderHeader = self.dock_widget.findChild(object, "noFolderHeader")
        self.noFolderMessageLabel = self.dock_widget.findChild(object, "noFolderMessageLabel")
        
        # 操作ボタンの取得
        self.newFileButton = self.dock_widget.findChild(QToolButton, "newFileButton")
        self.newFolderButton = self.dock_widget.findChild(QToolButton, "newFolderButton")
        self.refreshTreeButton = self.dock_widget.findChild(QToolButton, "refreshTreeButton")
        self.collapseAllButton = self.dock_widget.findChild(QToolButton, "collapseAllButton")
        
        # タイトルバーウィジェットの設定（メニュー、フロート、閉じボタン含む）
        self.setup_title_bar()
        
        # テキスト色の取得
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        
        # アイコンのロード
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        self.icon_folder = load_svg_icon(os.path.join(icons_dir, "folder.svg"), text_color)
        self.icon_file = load_svg_icon(os.path.join(icons_dir, "file.svg"), text_color)
        self.icon_chevron_down = load_svg_icon(os.path.join(icons_dir, "chevron-down.svg"), text_color)
        self.icon_chevron_right = load_svg_icon(os.path.join(icons_dir, "chevron-right.svg"), text_color)
        self.icon_refresh = load_svg_icon(os.path.join(icons_dir, "rotate-cw.svg"), text_color)
        self.icon_collapse = load_svg_icon(os.path.join(icons_dir, "copy-minus.svg"), text_color)
        
        # ボタンへのアイコン設定
        operation_buttons = [
            (self.newFileButton, self.icon_file),
            (self.newFolderButton, self.icon_folder),
            (self.refreshTreeButton, self.icon_refresh),
            (self.collapseAllButton, self.icon_collapse)
        ]
        for btn, icon in operation_buttons:
            if btn:
                btn.setIcon(icon)
                btn.setText("")
                btn.setAutoRaise(True)
            
        # 初期アイコン設定
        headers = [self.openEditorsHeader, self.projectHeaderDisclosure, self.noFolderHeader]
        for header in headers:
            if header:
                header.setIcon(self.icon_chevron_down)
            
        # シグナルの接続
        if self.openFolderButton:
            self.openFolderButton.clicked.connect(self.on_open_folder_clicked)
        if self.openEditorsHeader:
            self.openEditorsHeader.clicked.connect(self.toggle_open_editors)
        if self.projectHeaderDisclosure:
            self.projectHeaderDisclosure.clicked.connect(self.toggle_project_tree)
        if self.noFolderHeader:
            self.noFolderHeader.clicked.connect(self.toggle_no_folder)
        if self.collapseAllButton:
            self.collapseAllButton.clicked.connect(lambda: self.modElementsTree.collapseAll() if self.modElementsTree else None)
        if self.refreshTreeButton:
            self.refreshTreeButton.clicked.connect(lambda: self.load_project(self.current_project_path) if hasattr(self, "current_project_path") and self.current_project_path else None)
        if self.modElementsTree:
            self.modElementsTree.itemDoubleClicked.connect(self.on_item_double_clicked)
            
    def on_item_double_clicked(self, item, column):
        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        if file_path and os.path.isfile(file_path):
            if hasattr(self.parent_window, "open_file"):
                self.parent_window.open_file(file_path)
            
    def setup_title_bar(self):
        self.explorerTitleBar = self.dock_widget.findChild(QWidget, "explorerTitleBar")
        if not self.explorerTitleBar:
            return
            
        # パレットから色を取得して少し暗く調整
        bg_color = self.parent_window.palette().color(QPalette.ColorRole.Window).darker(110).name()
        self.explorerTitleBar.setStyleSheet(f"""
            QWidget#explorerTitleBar {{
                background-color: {bg_color};
                border-radius: 4px;
            }}
        """)

        layout = self.explorerTitleBar.layout()
        if not layout:
            layout = QHBoxLayout(self.explorerTitleBar)
            layout.setContentsMargins(8, 2, 2, 2)
            layout.setSpacing(2)
            
        # タイトルラベル
        self.explorerTitleLabel = QLabel("エクスプローラー")
        layout.addWidget(self.explorerTitleLabel)
        layout.addStretch()
        
        # --- ボタン群 ---
        
        # 1. メニューボタン (三角形のみ、テキストなし)
        self.explorerMoreButton = QToolButton()
        self.explorerMoreButton.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.explorerMoreButton.setAutoRaise(True)
        # テキストを空にし、メニューインジケーターのみを表示させる設定
        self.explorerMoreButton.setText("") 
        layout.addWidget(self.explorerMoreButton)
        
        # メニュー設定
        self.more_menu = QMenu(self.explorerMoreButton)
        self.action_show_editors = QAction("開いているエディター", self.more_menu)
        self.action_show_editors.setCheckable(True)
        self.action_show_editors.setChecked(True)
        self.action_show_editors.triggered.connect(self.on_show_editors_toggled)
        self.more_menu.addAction(self.action_show_editors)
        self.more_menu.addSeparator()
        self.action_open_other = QAction("別のプロジェクトを選択...", self.more_menu)
        self.action_open_other.triggered.connect(self.on_open_folder_clicked)
        self.more_menu.addAction(self.action_open_other)
        self.explorerMoreButton.setMenu(self.more_menu)
        
        # 2. フロートボタン (標準アイコン使用)
        self.floatButton = QToolButton()
        self.floatButton.setIcon(self.dock_widget.style().standardIcon(QStyle.SP_TitleBarNormalButton))
        self.floatButton.setAutoRaise(True)
        self.floatButton.setToolTip("フロート切り替え")
        self.floatButton.clicked.connect(lambda: self.dock_widget.setFloating(not self.dock_widget.isFloating()))
        layout.addWidget(self.floatButton)
        
        # 3. 閉じボタン (標準アイコン使用)
        self.closeButton = QToolButton()
        self.closeButton.setIcon(self.dock_widget.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.closeButton.setAutoRaise(True)
        self.closeButton.setToolTip("閉じる")
        self.closeButton.clicked.connect(self.dock_widget.close)
        layout.addWidget(self.closeButton)
        
        # ドックにセット
        self.dock_widget.setTitleBarWidget(self.explorerTitleBar)
        
    def on_show_editors_toggled(self, checked):
        if self.openEditorsHeader and self.openEditorsList:
            self.openEditorsHeader.setVisible(checked)
            self.openEditorsList.setVisible(checked)
            
    def toggle_open_editors(self):
        if self.openEditorsList:
            is_visible = self.openEditorsList.isVisible()
            self.openEditorsList.setVisible(not is_visible)
            self.openEditorsHeader.setIcon(self.icon_chevron_right if is_visible else self.icon_chevron_down)
            
    def toggle_project_tree(self):
        widgets = [self.searchLineEdit, self.modElementsTree]
        is_visible = any(w.isVisible() for w in widgets if w)
        for w in widgets:
            if w: w.setVisible(not is_visible)
        if self.projectHeaderDisclosure:
            self.projectHeaderDisclosure.setIcon(self.icon_chevron_right if is_visible else self.icon_chevron_down)

    def toggle_no_folder(self):
        widgets = [self.noFolderMessageLabel, self.openFolderButton]
        is_visible = any(w.isVisible() for w in widgets if w)
        for w in widgets:
            if w: w.setVisible(not is_visible)
        if self.noFolderHeader:
            self.noFolderHeader.setIcon(self.icon_chevron_right if is_visible else self.icon_chevron_down)

    def on_open_folder_clicked(self):
        folder_path = QFileDialog.getExistingDirectory(
            self.parent_window,
            "MODフォルダーを開く",
            os.path.expanduser("~")
        )
        if folder_path:
            self.load_project(folder_path)
            
    def load_project(self, folder_path):
        if not self.modElementsTree or not self.folderStack:
            return
        self.current_project_path = folder_path
        self.modElementsTree.clear()
        self._populate_tree(folder_path, self.modElementsTree.invisibleRootItem())
        self.folderStack.setCurrentIndex(1)
        
    def _populate_tree(self, path, parent_item):
        try:
            items = os.listdir(path)
            items.sort()
            for item_name in items:
                full_path = os.path.join(path, item_name)
                if os.path.isdir(full_path):
                    tree_item = QTreeWidgetItem(parent_item)
                    tree_item.setText(0, item_name)
                    tree_item.setIcon(0, self.icon_folder)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                    self._populate_tree(full_path, tree_item)
            for item_name in items:
                full_path = os.path.join(path, item_name)
                if os.path.isfile(full_path):
                    tree_item = QTreeWidgetItem(parent_item)
                    tree_item.setText(0, item_name)
                    tree_item.setIcon(0, self.icon_file)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
        except Exception as e:
            print(f"ツリーの構築中にエラーが発生しました: {e}")

    def get_widget(self):
        return self.dock_widget
