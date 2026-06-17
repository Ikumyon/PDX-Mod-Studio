import os
import shutil
import subprocess
import stat
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QTreeWidgetItem, 
                             QVBoxLayout, QHBoxLayout, QMenu, QWidget, QLabel, 
                             QToolButton, QStyle, QInputDialog, QMessageBox)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize, QMimeData, QUrl, QByteArray
from PySide6.QtGui import QIcon, QPalette, QAction, QPixmap, QGuiApplication, QKeySequence
from core.utils import load_svg_icon
import core.api

class OpenEditorItemWidget(QWidget):
    def __init__(self, name, path, index, icon, icon_close, parent_dock):
        super().__init__()
        self.path = path
        self.index = index
        self.parent_dock = parent_dock
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)
        
        # アイコン
        self.icon_label = QLabel()
        self.icon_label.setPixmap(icon.pixmap(16, 16))
        layout.addWidget(self.icon_label)
        
        # ファイル名
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("background: transparent;")
        layout.addWidget(self.name_label)
        
        layout.addStretch()
        
        # 閉じるボタン (デフォルト非表示)
        self.close_button = QToolButton()
        self.close_button.setIcon(icon_close)
        self.close_button.setFixedSize(18, 18)
        self.close_button.setAutoRaise(True)
        self.close_button.setToolTip("閉じる")
        self.close_button.setVisible(False)
        self.close_button.clicked.connect(self.on_close_clicked)
        layout.addWidget(self.close_button)
        
        # ツールチップ設定
        self.setToolTip(path)
        # 背景を透明に（親の選択ハイライトが見えるように）
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def enterEvent(self, event):
        self.close_button.setVisible(True)
        super().enterEvent(event)
        
    def leaveEvent(self, event):
        # アクティブ（選択中）でなければ非表示にする
        is_active = (self.parent_dock.openEditorsList.currentRow() == self.index)
        if not is_active:
            self.close_button.setVisible(False)
        super().leaveEvent(event)

    def on_close_clicked(self):
        # メインウィンドウのタブを閉じる処理をトリガー
        if hasattr(self.parent_dock.parent_window, "editorTabs") and self.parent_dock.parent_window.editorTabs:
            # tabCloseRequested はシグナルなので emit する
            self.parent_dock.parent_window.editorTabs.tabCloseRequested.emit(self.index)

class ProjectTreeDock:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.show_editors_requested = True
        self.show_plugin_section_requested = True
        self.show_hidden_files = False
        
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
        
        # プラグインセクションの取得
        self.pluginSectionContainer = self.dock_widget.findChild(QWidget, "pluginSectionContainer")
        self.pluginSectionLayout = self.dock_widget.findChild(object, "pluginSectionLayout")
        if self.pluginSectionContainer:
            self.pluginSectionContainer.setVisible(False) # 初期状態は非表示
        
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
        self.icon_close = load_svg_icon(os.path.join(icons_dir, "close.svg"), text_color)
        
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
            
        # toggleViewActionの設定（アクティビティバー用）
        view_action = self.dock_widget.toggleViewAction()
        view_action.setIcon(self.icon_file)
        view_action.setText("プロジェクト")
        
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
            self.modElementsTree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.modElementsTree.customContextMenuRequested.connect(self.on_tree_context_menu)

        if self.openEditorsList:
            self.openEditorsList.itemClicked.connect(self.on_editor_item_clicked)
        if self.newFileButton:
            self.newFileButton.clicked.connect(self.on_new_file_clicked)
        if self.newFolderButton:
            self.newFolderButton.clicked.connect(self.on_new_folder_clicked)
            
        self.active_plugin = None
            
    def on_item_double_clicked(self, item, column):
        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        if file_path and os.path.isfile(file_path):
            if hasattr(self.parent_window, "open_file"):
                self.parent_window.open_file(file_path)

    def on_tree_context_menu(self, pos):
        if not self.modElementsTree:
            return
        item = self.modElementsTree.itemAt(pos)
        if not item:
            return
            
        file_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not file_path or not os.path.exists(file_path):
            return
            
        menu = QMenu(self.modElementsTree)

        if os.path.isfile(file_path):
            # 1. 外部エディタ（利用可能なら優先して上に表示）
            try:
                get_editors = getattr(self.parent_window, "get_available_editors_for_file", None)
                editors = get_editors(file_path, include_script=False) if callable(get_editors) else []
                if editors:
                    for editor in editors:
                        action = menu.addAction(f"{editor['name']} で開く")
                        action.triggered.connect(lambda checked=False, e_id=editor['id']: self.parent_window.open_file(file_path, e_id))
                    menu.addSeparator()
            except Exception as e:
                print(f"Error getting editors for context menu: {e}")

            # 2. デフォルトのテキストエディタ
            text_action = menu.addAction("テキストエディタで開く")
            text_action.triggered.connect(lambda: self.parent_window.open_file(file_path, core.api.BUILTIN_TEXT_EDITOR_ID))
            menu.addSeparator()

        explorer_action = menu.addAction("エクスプローラーで開く")
        explorer_action.triggered.connect(lambda checked=False: self.open_in_explorer(file_path))
        menu.addSeparator()

        self._add_file_operation_actions(menu, file_path)
            
        menu.exec(self.modElementsTree.mapToGlobal(pos))

    def _add_file_operation_actions(self, menu, file_path):
        cut_action = menu.addAction("切り取り")
        cut_action.setShortcut(QKeySequence.StandardKey.Cut)
        cut_action.setShortcutVisibleInContextMenu(True)
        cut_action.triggered.connect(lambda checked=False: self.copy_paths_to_clipboard([file_path], cut=True))

        copy_action = menu.addAction("コピー")
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.setShortcutVisibleInContextMenu(True)
        copy_action.triggered.connect(lambda checked=False: self.copy_paths_to_clipboard([file_path], cut=False))

        paste_action = menu.addAction("貼り付け")
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        paste_action.setShortcutVisibleInContextMenu(True)
        paste_action.setEnabled(self.clipboard_has_file_paths())
        paste_action.triggered.connect(lambda checked=False: self.paste_clipboard_paths(file_path))

        menu.addSeparator()

        copy_path_action = menu.addAction("パスのコピー")
        copy_path_action.setShortcut(QKeySequence("Shift+Alt+C"))
        copy_path_action.setShortcutVisibleInContextMenu(True)
        copy_path_action.triggered.connect(lambda checked=False: self.copy_text_to_clipboard(file_path))

        copy_relative_path_action = menu.addAction("相対パスをコピー")
        copy_relative_path_action.setShortcut(QKeySequence("Ctrl+K, Ctrl+Shift+C"))
        copy_relative_path_action.setShortcutVisibleInContextMenu(True)
        copy_relative_path_action.triggered.connect(lambda checked=False: self.copy_text_to_clipboard(self.relative_project_path(file_path)))

        menu.addSeparator()

        rename_action = menu.addAction("名前の変更...")
        rename_action.setShortcut(QKeySequence("F2"))
        rename_action.setShortcutVisibleInContextMenu(True)
        rename_action.triggered.connect(lambda checked=False: self.rename_path(file_path))

        delete_action = menu.addAction("削除")
        delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_action.setShortcutVisibleInContextMenu(True)
        delete_action.triggered.connect(lambda checked=False: self.delete_path(file_path))

    def copy_paths_to_clipboard(self, paths, cut=False):
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in paths])
        mime_data.setText("\n".join(paths))

        # Windows Explorer 等に移動/コピー意図を渡すための DropEffect。
        drop_effect = 2 if cut else 5
        mime_data.setData(
            'application/x-qt-windows-mime;value="Preferred DropEffect"',
            QByteArray(bytes([drop_effect, 0, 0, 0])),
        )
        mime_data.setData("x-kde-cutselection", QByteArray(b"1" if cut else b"0"))
        QGuiApplication.clipboard().setMimeData(mime_data)

    def clipboard_has_file_paths(self):
        mime_data = QGuiApplication.clipboard().mimeData()
        return bool(mime_data and mime_data.hasUrls())

    def clipboard_file_paths(self):
        mime_data = QGuiApplication.clipboard().mimeData()
        if not mime_data or not mime_data.hasUrls():
            return []
        return [url.toLocalFile() for url in mime_data.urls() if url.isLocalFile() and url.toLocalFile()]

    def clipboard_is_cut_operation(self):
        mime_data = QGuiApplication.clipboard().mimeData()
        if not mime_data:
            return False

        kde_cut = bytes(mime_data.data("x-kde-cutselection"))
        if kde_cut == b"1":
            return True

        drop_effect = bytes(mime_data.data('application/x-qt-windows-mime;value="Preferred DropEffect"'))
        return len(drop_effect) >= 1 and drop_effect[0] == 2

    def paste_clipboard_paths(self, target_path):
        destination_dir = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
        if not destination_dir or not os.path.isdir(destination_dir):
            QMessageBox.warning(self.dock_widget, "貼り付け", "貼り付け先のフォルダを特定できません。")
            return

        source_paths = self.clipboard_file_paths()
        if not source_paths:
            QMessageBox.warning(self.dock_widget, "貼り付け", "貼り付けるファイルまたはフォルダがありません。")
            return

        is_cut = self.clipboard_is_cut_operation()
        changed_path = None
        try:
            for source_path in source_paths:
                if not os.path.exists(source_path):
                    raise FileNotFoundError(source_path)

                destination_path = os.path.join(destination_dir, os.path.basename(source_path))
                if os.path.normcase(os.path.abspath(source_path)) == os.path.normcase(os.path.abspath(destination_path)):
                    raise FileExistsError(destination_path)
                if os.path.exists(destination_path):
                    raise FileExistsError(destination_path)

                if is_cut:
                    shutil.move(source_path, destination_path)
                elif os.path.isdir(source_path):
                    shutil.copytree(source_path, destination_path)
                else:
                    shutil.copy2(source_path, destination_path)
                changed_path = destination_path
        except Exception as error:
            QMessageBox.critical(self.dock_widget, "貼り付け", f"貼り付けに失敗しました: {error}")
            return

        if is_cut:
            QGuiApplication.clipboard().clear()
        self.refresh_parent_after_path_change(new_path=changed_path)

    def open_in_explorer(self, file_path):
        try:
            if os.path.isdir(file_path):
                subprocess.Popen(["explorer", os.path.normpath(file_path)])
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(file_path)])
        except Exception as error:
            QMessageBox.critical(self.dock_widget, "エクスプローラーで開く", f"エクスプローラーを開けませんでした: {error}")

    def copy_text_to_clipboard(self, text):
        QGuiApplication.clipboard().setText(text)

    def relative_project_path(self, file_path):
        project_path = getattr(self, "current_project_path", None)
        if not project_path:
            return file_path
        try:
            return os.path.relpath(file_path, project_path).replace("\\", "/")
        except ValueError:
            return file_path

    def refresh_parent_after_path_change(self, old_path=None, new_path=None):
        if not hasattr(self, "current_project_path") or not self.current_project_path:
            return
        self.load_project(self.current_project_path)

        target_path = new_path or old_path
        if target_path and self.modElementsTree:
            matches = self.modElementsTree.findItems(
                os.path.basename(target_path),
                Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive,
                0,
            )
            for item in matches:
                if item.data(0, Qt.ItemDataRole.UserRole) == target_path:
                    self.modElementsTree.setCurrentItem(item)
                    break

    def rename_path(self, file_path):
        parent_dir = os.path.dirname(file_path)
        old_name = os.path.basename(file_path)
        new_name, accepted = QInputDialog.getText(
            self.dock_widget,
            "名前の変更",
            "新しい名前:",
            text=old_name,
        )
        if not accepted:
            return

        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if os.path.basename(new_name) != new_name:
            QMessageBox.warning(self.dock_widget, "名前の変更", "名前にパス区切りを含めることはできません。")
            return

        new_path = os.path.join(parent_dir, new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self.dock_widget, "名前の変更", "同じ名前の項目が既に存在します。")
            return

        try:
            os.rename(file_path, new_path)
        except Exception as error:
            QMessageBox.critical(self.dock_widget, "名前の変更", f"名前の変更に失敗しました: {error}")
            return

        self.refresh_parent_after_path_change(file_path, new_path)

    def delete_path(self, file_path):
        name = os.path.basename(file_path)
        message = f"「{name}」を削除しますか？"
        if os.path.isdir(file_path):
            message += "\nフォルダ内の項目もすべて削除されます。"

        answer = QMessageBox.question(
            self.dock_widget,
            "削除",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            if os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                os.remove(file_path)
        except Exception as error:
            QMessageBox.critical(self.dock_widget, "削除", f"削除に失敗しました: {error}")
            return

        self.refresh_parent_after_path_change(file_path)

            
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

        # 2. プラグイン固有の追加セクション (プラグイン提供のメタデータで名称を動的に決定)
        self.action_show_plugin_section = QAction("", self.more_menu)
        self.action_show_plugin_section.setCheckable(True)
        self.action_show_plugin_section.setChecked(True)
        self.action_show_plugin_section.setVisible(False) # 初期状態では非表示
        self.action_show_plugin_section.triggered.connect(self.on_plugin_section_toggled)

        self.more_menu.addAction(self.action_show_plugin_section)
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
        self.show_editors_requested = checked
        count = 0
        if hasattr(self.parent_window, "editorTabs") and self.parent_window.editorTabs:
            count = self.parent_window.editorTabs.count()
        self._update_editors_visibility(count)

    def on_plugin_section_toggled(self, checked):
        self.show_plugin_section_requested = checked
        if self.pluginSectionContainer:
            has_widget = self.pluginSectionLayout.count() > 0
            self.pluginSectionContainer.setVisible(checked and has_widget)
        
    def _update_editors_visibility(self, count):
        visible = self.show_editors_requested and count > 0
        if self.openEditorsHeader:
            self.openEditorsHeader.setVisible(visible)
        if self.openEditorsList:
            self.openEditorsList.setVisible(visible)
            
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
        if hasattr(self.parent_window, "current_project_file"):
            self.parent_window.current_project_file = None
            self.parent_window.current_project_type = "reference"
            self.parent_window.source_mod_root = None
        core.api.set_project_path(folder_path)
        
        from core.dialog.settings import settings_manager
        settings_manager.add_recent_project(folder_path, os.path.basename(folder_path), game=self.active_plugin.id if self.active_plugin else "")

        self.modElementsTree.clear()
        self._populate_tree(folder_path, self.modElementsTree.invisibleRootItem())
        self.folderStack.setCurrentIndex(1)
        
    def _populate_tree(self, path, parent_item):
        if not hasattr(self, "current_project_path"):
            return
            
        try:
            items = [
                item
                for item in os.listdir(path)
                if self.show_hidden_files or not self.is_hidden_path(os.path.join(path, item))
            ]
            items.sort()
            
            # ディレクトリの処理
            for item_name in items:
                full_path = os.path.join(path, item_name)
                if os.path.isdir(full_path):
                    tree_item = QTreeWidgetItem(parent_item)
                    tree_item.setText(0, item_name)
                    tree_item.setIcon(0, self.icon_folder)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
                    self._populate_tree(full_path, tree_item)
            
            # ファイルの処理
            for item_name in items:
                full_path = os.path.join(path, item_name)
                if os.path.isfile(full_path):
                    tree_item = QTreeWidgetItem(parent_item)
                    tree_item.setText(0, item_name)
                    
                    # --- アイコンの決定ロジック ---
                    icon = self.icon_file # デフォルト
                    
                    if hasattr(self, "path_to_icon") and self.path_to_icon:
                        # プロジェクトルートからの相対パスを取得
                        rel_path = os.path.relpath(full_path, self.current_project_path)
                        norm_rel_dir = os.path.normpath(os.path.dirname(rel_path))
                        
                        # 親ディレクトリが定義された要素のパス配下かチェック
                        for element_path, element_icon in self.path_to_icon.items():
                            # 完全一致、またはそのサブフォルダ内
                            if norm_rel_dir == element_path or norm_rel_dir.startswith(element_path + os.sep):
                                icon = element_icon
                                break
                    
                    tree_item.setIcon(0, icon)
                    # ----------------------------
                    
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, full_path)
        except Exception as e:
            print(f"ツリーの構築中にエラーが発生しました: {e}")

    def set_show_hidden_files(self, enabled):
        self.show_hidden_files = bool(enabled)
        if hasattr(self, "current_project_path") and self.current_project_path:
            self.load_project(self.current_project_path)

    def is_hidden_path(self, path):
        name = os.path.basename(path)
        if name.startswith("."):
            return True
        if os.name != "nt":
            return False
        try:
            return bool(os.stat(path).st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN)
        except (AttributeError, OSError):
            return False

    def get_icon_for_path(self, file_path):
        """指定されたパスに最適なアイコン（専用アイコンまたは汎用ファイルアイコン）を返す"""
        if not hasattr(self, "path_to_icon") or not self.path_to_icon or not hasattr(self, "current_project_path"):
            return self.icon_file
            
        try:
            rel_path = os.path.relpath(file_path, self.current_project_path)
            norm_rel_dir = os.path.normpath(os.path.dirname(rel_path))
            
            for element_path, element_icon in self.path_to_icon.items():
                if norm_rel_dir == element_path or norm_rel_dir.startswith(element_path + os.sep):
                    return element_icon
        except Exception:
            pass
            
        return self.icon_file

    def update_open_editors(self, tab_widget):
        if not self.openEditorsList:
            return
            
        self.openEditorsList.clear()
        count = tab_widget.count()
        
        # アイテム数とユーザー設定に基づいて表示を更新
        self._update_editors_visibility(count)
        visible = self.show_editors_requested and count > 0
        if not visible:
            return
            
        total_height = 0
        for i in range(count):
            file_name = tab_widget.tabText(i)
            file_path = tab_widget.tabToolTip(i)
            
            # パスに応じたアイコンを取得
            icon = self.get_icon_for_path(file_path)
            
            from PySide6.QtWidgets import QListWidgetItem
            list_item = QListWidgetItem()
            list_item.setData(Qt.ItemDataRole.UserRole, i) # インデックスを保存
            self.openEditorsList.addItem(list_item)
            
            # カスタムウィジェットの作成
            item_widget = OpenEditorItemWidget(file_name, file_path, i, icon, self.icon_close, self)
            self.openEditorsList.setItemWidget(list_item, item_widget)
            
            # ウィジェットの推奨サイズから高さを取得してセット
            h = item_widget.sizeHint().height()
            list_item.setSizeHint(QSize(0, h))
            total_height += h
            
        # 初期選択状態の同期
        self.sync_selection(tab_widget.currentIndex())

        # リスト全体の高さを設定 (枠線の厚みなども考慮)
        frame_width = self.openEditorsList.frameWidth() * 2
        self.openEditorsList.setFixedHeight(total_height + frame_width)

    def sync_selection(self, index):
        if not self.openEditorsList or index < 0:
            return
            
        # リストの選択行を更新
        self.openEditorsList.setCurrentRow(index)
        
        # 全項目のボタン表示状態を更新
        for i in range(self.openEditorsList.count()):
            item = self.openEditorsList.item(i)
            widget = self.openEditorsList.itemWidget(item)
            if widget:
                widget.close_button.setVisible(i == index)

    def on_editor_item_clicked(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        if hasattr(self.parent_window, "editorTabs") and self.parent_window.editorTabs:
            self.parent_window.editorTabs.setCurrentIndex(index)

    def set_active_plugin(self, plugin):
        """アクティブなプラグインを設定する"""
        self.active_plugin = plugin
        self.path_to_icon = {}
        
        # テーマのテキスト色を取得
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        
        # 各要素のアイコンをキャッシュ
        if plugin and plugin.elements:
            for element in plugin.elements:
                icon_path = plugin.get_element_attribute(element, "icon")
                if icon_path:
                    if not os.path.isabs(icon_path):
                        icon_path = os.path.join(element.element_dir, icon_path)
                
                if icon_path and os.path.exists(icon_path):
                    if icon_path.lower().endswith(".svg"):
                        icon = load_svg_icon(icon_path, text_color)
                    else:
                        # PNG等の場合は色味を維持する
                        icon = QIcon()
                        pixmap = QPixmap(icon_path)
                        icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
                        icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
                        icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
                        icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
                        icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
                        icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
                    
                    # パス（OSに合わせた形式）とアイコンを紐付け
                    norm_path = os.path.normpath(element.path)
                    self.path_to_icon[norm_path] = icon

        print(f"ProjectTreeDock: プラグインを適用しました - {plugin.name}")
        # プロジェクトが開かれている場合は再読み込みしてアイコンを反映
        if hasattr(self, "current_project_path") and self.current_project_path:
            self.load_project(self.current_project_path)
        
        # アシスタントセクションの更新
        self.update_assistant_widget()

    def update_assistant_widget(self):
        """プラグインから追加セクションのメタデータを取得し、UIを更新する"""
        if not self.pluginSectionContainer or not self.pluginSectionLayout:
            return
            
        # 既存のウィジェットを削除
        while self.pluginSectionLayout.count():
            item = self.pluginSectionLayout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        
        # アクティブなプラグインから新しいセクションの情報を取得
        plugin = getattr(self, "active_plugin", None)
        res = plugin.create_assistant_widget(self.pluginSectionContainer) if plugin else None
        if res and isinstance(res, dict):
            widget = res.get("widget")
            name = res.get("name", "追加セクション")
            collapsible = res.get("collapsible", True)
            
            if widget:
                self.pluginSectionLayout.addWidget(widget)
                if hasattr(self, "action_show_plugin_section"):
                    self.action_show_plugin_section.setText(name)
                    self.action_show_plugin_section.setEnabled(collapsible)
                    self.action_show_plugin_section.setVisible(True)
                self.pluginSectionContainer.setVisible(self.show_plugin_section_requested)
        else:
            if hasattr(self, "action_show_plugin_section"):
                self.action_show_plugin_section.setVisible(False)
            self.pluginSectionContainer.setVisible(False)

    def on_new_file_clicked(self):
        if not hasattr(self, "current_project_path") or not self.current_project_path:
            QMessageBox.warning(self.dock_widget, "警告", "プロジェクトフォルダが開かれていません。")
            return

        # ファイルタイプの要素のみを抽出
        elements = [e for e in self.active_plugin.elements if not self.active_plugin.get_element_attribute(e, "is_folder", False)] if self.active_plugin else []

        if not elements:
            self._create_generic_file()
            return

        menu = QMenu(self.newFileButton)
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()

        # 統合ツリーを構築
        unified_tree = self._build_unified_creation_tree(elements, text_color)
        
        # メニューに反映
        self._populate_creation_menu(menu, unified_tree)
        
        menu.addSeparator()
        generic_action = menu.addAction(self.icon_file, "汎用ファイル...")
        generic_action.triggered.connect(self._create_generic_file)
        
        menu.exec(self.newFileButton.mapToGlobal(self.newFileButton.rect().bottomLeft()))

    def _build_unified_creation_tree(self, elements, text_color):
        tree = []
        for element in elements:
            icon = self._get_element_icon(element, text_color)
            self._merge_path_into_tree(tree, element, icon)
        return tree

    def _merge_path_into_tree(self, current_level, element, element_icon):
        match_glob = element.raw.get("match_glob") or element.path
        normalized = str(match_glob).replace("\\", "/")
        segments = [
            segment
            for segment in normalized.split("/")
            if segment and not any(char in segment for char in "*?[")
        ]

        target_level = current_level
        for segment in segments:
            target = next(
                (node for node in target_level if node.get("kind") == "folder" and node.get("segment") == segment),
                None,
            )
            if not target:
                target = {
                    "kind": "folder",
                    "segment": segment,
                    "name": segment,
                    "icon": self.icon_folder,
                    "children": [],
                }
                target_level.append(target)
            target_level = target["children"]

        target_level.append(
            {
                "kind": "file",
                "name": element.name,
                "icon": element_icon,
                "element": element,
                "path": element.path,
                "extension": element.raw.get("extension"),
            }
        )

    def _populate_creation_menu(self, menu, tree_nodes):
        def sort_key(node):
            return (0 if node.get("kind") == "folder" else 1, node.get("name", "").lower())

        for node in sorted(tree_nodes, key=sort_key):
            name = node.get("name", "Unnamed")
            icon = node.get("icon")
            children = node.get("children")

            if children:
                sub_menu = menu.addMenu(icon, name) if icon else menu.addMenu(name)
                self._populate_creation_menu(sub_menu, children)
                continue

            action = menu.addAction(icon, name) if icon else menu.addAction(name)
            element = node.get("element")
            path = node.get("path")
            ext = node.get("extension")
            action.triggered.connect(
                lambda checked=False, e=element, p=path, x=ext, n=name:
                self._create_element_file(e, path_override=p, extension_override=x, name_override=n)
            )

    def _get_element_icon(self, element, text_color):
        icon_path = element.plugin.get_element_attribute(element, "icon")
        if icon_path:
            if not os.path.isabs(icon_path):
                icon_path = os.path.join(element.element_dir, icon_path)
        
        if icon_path and os.path.exists(icon_path):
            if icon_path.lower().endswith(".svg"):
                return load_svg_icon(icon_path, text_color)
            else:
                icon = QIcon()
                pixmap = QPixmap(icon_path)
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
                icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
                icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
                return icon
        return None


    def on_new_folder_clicked(self):
        if not hasattr(self, "current_project_path") or not self.current_project_path:
            QMessageBox.warning(self.dock_widget, "警告", "プロジェクトフォルダが開かれていません。")
            return

        # フォルダタイプの要素のみを抽出
        elements = [e for e in self.active_plugin.elements if self.active_plugin.get_element_attribute(e, "is_folder", False)] if self.active_plugin else []

        if not elements:
            self._create_generic_folder()
            return

        menu = QMenu(self.newFolderButton)
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()

        for element in elements:
            icon_path = element.plugin.get_element_attribute(element, "icon")
            if icon_path:
                if not os.path.isabs(icon_path):
                    icon_path = os.path.join(element.element_dir, icon_path)

            if icon_path and os.path.exists(icon_path):
                if icon_path.lower().endswith(".svg"):
                    icon = load_svg_icon(icon_path, text_color)
                else:
                    icon = QIcon()
                    pixmap = QPixmap(icon_path)
                    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
                    icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
                    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
                    icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
                    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
                    icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)

            if icon:
                action = menu.addAction(icon, f"{element.name}フォルダを作成...")
            else:
                action = menu.addAction(f"{element.name}フォルダを作成...")
            action.triggered.connect(lambda checked=False, e=element: self._create_element_file(e))
        
        menu.addSeparator()
        generic_action = menu.addAction(self.icon_folder, "汎用フォルダ...")
        generic_action.triggered.connect(self._create_generic_folder)
        
        menu.exec(self.newFolderButton.mapToGlobal(self.newFolderButton.rect().bottomLeft()))

    def _create_generic_folder(self):
        folder_name, ok = QInputDialog.getText(self.dock_widget, "新規フォルダ", "フォルダ名:")
        if ok and folder_name:
            path = os.path.join(self.current_project_path, folder_name)
            try:
                os.makedirs(path, exist_ok=True)
                self.load_project(self.current_project_path)
            except Exception as e:
                QMessageBox.critical(self.dock_widget, "エラー", f"フォルダを作成できませんでした: {e}")

    def _create_element_file(self, element, path_override=None, extension_override=None, name_override=None):
        """プロファイルで定義された要素（ファイルまたはフォルダ）を作成する"""
        is_folder = element.plugin.get_element_attribute(element, "is_folder", False)
        display_name = name_override if name_override else element.name
        label = "フォルダ名" if is_folder else "ファイル名 (拡張子なし)"
        file_name, ok = QInputDialog.getText(self.dock_widget, f"新規 {display_name}", f"{label}:")
        if not ok or not file_name:
            return

        # 相対パスを考慮してターゲットディレクトリを決定
        rel_path = path_override if path_override is not None else element.path
        target_dir = os.path.join(self.current_project_path, rel_path)
        os.makedirs(target_dir, exist_ok=True)
        
        if is_folder:
            path = os.path.join(target_dir, file_name)
            if os.path.exists(path):
                QMessageBox.warning(self.dock_widget, "警告", "同名のフォルダが既に存在します。")
                return
            try:
                os.makedirs(path, exist_ok=True)
                self.load_project(self.current_project_path)
            except Exception as e:
                QMessageBox.critical(self.dock_widget, "エラー", f"フォルダを作成できませんでした: {e}")
        else:
            extension = extension_override if extension_override is not None else (element.plugin.get_element_attribute(element, "extension") or "")
            full_file_name = file_name + extension
            file_path = os.path.join(target_dir, full_file_name)
            
            if os.path.exists(file_path):
                QMessageBox.warning(self.dock_widget, "警告", "同名のファイルが既に存在します。")
                return

            try:
                encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)
                with open(file_path, 'w', encoding=encoding) as f:
                    f.write("")
                
                self.load_project(self.current_project_path)
                if hasattr(self.parent_window, "open_file"):
                    self.parent_window.open_file(file_path)
            except Exception as e:
                QMessageBox.critical(self.dock_widget, "エラー", f"ファイルを作成できませんでした: {e}")

    def _create_generic_file(self):
        file_name, ok = QInputDialog.getText(self.dock_widget, "新規ファイル", "ファイル名:")
        if ok and file_name:
            file_path = os.path.join(self.current_project_path, file_name)
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                self.load_project(self.current_project_path)
                if hasattr(self.parent_window, "open_file"):
                    self.parent_window.open_file(file_path)
            except Exception as e:
                QMessageBox.critical(self.dock_widget, "エラー", f"ファイルを作成できませんでした: {e}")

    def get_widget(self):
        return self.dock_widget
