import sys
import os
import json
import tempfile
import zipfile
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QToolButton, QWidget, QTabBar, QFileDialog
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize, QCoreApplication
import core.api
from core.i18n import I18nManager
tr = QCoreApplication.translate

def main():
    app = QApplication(sys.argv)
    
    # 翻訳の初期化
    I18nManager().init_translation(app)
    
    # Windowsのタスクバーアイコンを正しく表示するための設定
    try:
        import ctypes
        myappid = 'pdx.mod.studio.v1' # 任意の識別子
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    # --- 外部プラグインから import 可能にするための登録 ---
    import core.api
    sys.modules['core.api'] = core.api
    # -----------------------------------------------

    # UIファイルのパスを取得
    base_dir = os.path.dirname(__file__)
    
    # メインウィンドウのロード
    ui_file_path = os.path.join(base_dir, "ui", "main_window.ui")
    ui_file = QFile(ui_file_path)
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        print(tr("Main", "UIファイルを開けませんでした: {path}").format(path=ui_file_path))
        sys.exit(-1)

    loader = QUiLoader()
    window = loader.load(ui_file)
    ui_file.close()
    
    if not window:
        print(tr("Main", "UIのロードに失敗しました: {error}").format(error=loader.errorString()))
        sys.exit(-1)

    # --- アプリケーションアイコンの設定 ---
    window.current_project_file = None
    window.current_project_type = "reference"
    window.embedded_project_workspace = None

    from PySide6.QtGui import QIcon
    icon_path = os.path.join(base_dir, "assets", "app_icon.ico")
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
        # タスクバー用のアイコン設定 (Windows)
        app.setWindowIcon(QIcon(icon_path))

    # --- ドックの初期化 ---
    from core.project_tree_dock import ProjectTreeDock
    from core.plugin_manager import PluginManager
    from core.editor_registry import EditorRegistry
    from core.editor import EditorWidget
    project_tree = ProjectTreeDock(window)
    project_tree_dock = project_tree.get_widget()
    
    view_menu = window.findChild(QMenu, "menuView")
    docks = []
    if project_tree_dock:
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, project_tree_dock)
        docks.append(project_tree_dock)

    if view_menu:
        for dock in docks:
            view_menu.addAction(dock.toggleViewAction())

    # --- エディタータブの設定 (QTabBar + QStackedWidget への適応) ---
    tab_bar_container = window.findChild(object, "editorTabBarContainer")
    editor_stacked = window.findChild(object, "editorStackedWidget")
    tab_corner_container = window.findChild(object, "tabCornerContainer")

    if not tab_bar_container or not editor_stacked:
        print("Error: editorTabBarContainer or editorStackedWidget not found in UI")
        sys.exit(-1)

    # QTabBar をプログラム側で生成（QUiLoader の制限回避）
    editor_tab_bar = QTabBar(tab_bar_container)
    editor_tab_bar.setDocumentMode(True)
    editor_tab_bar.setTabsClosable(True)
    editor_tab_bar.setExpanding(False)
    if tab_bar_container.layout():
        tab_bar_container.layout().addWidget(editor_tab_bar)

    class EditorTabProxy(QWidget):
        def __init__(self, tab_bar, stacked_widget):
            super().__init__()
            self.tab_bar = tab_bar
            self.stacked_widget = stacked_widget
            self.tabCloseRequested = tab_bar.tabCloseRequested
            self.currentChanged = tab_bar.currentChanged

        def count(self): return self.tab_bar.count()
        def currentIndex(self): return self.tab_bar.currentIndex()
        def setCurrentIndex(self, index):
            self.tab_bar.setCurrentIndex(index)
            self.stacked_widget.setCurrentIndex(index)
        def widget(self, index): return self.stacked_widget.widget(index)
        def tabText(self, index): return self.tab_bar.tabText(index)
        def setTabText(self, index, text): self.tab_bar.setTabText(index, text)
        def tabToolTip(self, index): return self.tab_bar.tabToolTip(index)
        def setTabToolTip(self, index, tip): self.tab_bar.setTabToolTip(index, tip)
        def setTabIcon(self, index, icon): self.tab_bar.setTabIcon(index, icon)
        def removeTab(self, index):
            w = self.stacked_widget.widget(index)
            self.tab_bar.removeTab(index)
            if w: self.stacked_widget.removeWidget(w)
        def addTab(self, widget, icon, text):
            self.stacked_widget.addWidget(widget)
            idx = self.tab_bar.addTab(icon, text)
            return idx
        def insertTab(self, index, widget, icon, text):
            self.stacked_widget.insertWidget(index, widget)
            idx = self.tab_bar.insertTab(index, icon, text)
            return idx
        def indexOf(self, widget): return self.stacked_widget.indexOf(widget)
        def setCornerWidget(self, widget, corner):
            if tab_corner_container and tab_corner_container.layout():
                # 既存のウィジェットのうち、modeSelectorButton 以外を削除
                layout = tab_corner_container.layout()
                for i in reversed(range(layout.count())):
                    item = layout.itemAt(i)
                    w = item.widget()
                    if w and w.objectName() != "modeSelectorButton":
                        layout.removeItem(item)
                        w.deleteLater()
                layout.addWidget(widget)

    window.editorTabs = EditorTabProxy(editor_tab_bar, editor_stacked)
    editor_tab_bar.currentChanged.connect(editor_stacked.setCurrentIndex)

    # シグナルの接続
    window.editorTabs.tabCloseRequested.connect(lambda index: (
        window.editorTabs.removeTab(index),
        project_tree.update_open_editors(window.editorTabs)
    ))

    def on_tab_changed(index):
        project_tree.sync_selection(index)
        update_editor_selector(index)

    window.editorTabs.currentChanged.connect(on_tab_changed)
    # 初期状態のリスト更新
    project_tree.update_open_editors(window.editorTabs)

    # --- エディタ管理の初期化 ---
    editor_registry = EditorRegistry()
    TEXT_EDITOR_ID = editor_registry.text_editor_id
    
    # ビュー切り替え用のボタンをUIから取得 (旧modeSelectorButtonを流用)
    view_selector = window.findChild(QToolButton, "modeSelectorButton")
    if view_selector:
        view_selector.setVisible(False) # 初期状態は非表示
        view_selector.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        view_selector.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        view_selector.setIconSize(QSize(20, 20))
        mode_icon_path = os.path.join(base_dir, "assets", "icons", "panel-top-open.svg")
        if os.path.exists(mode_icon_path):
            from core.utils import load_svg_icon
            icon_color = window.palette().color(window.foregroundRole()).name()
            view_selector.setIcon(load_svg_icon(mode_icon_path, icon_color))
        view_selector.setStyleSheet("QToolButton::menu-indicator { image: none; }") # 三角マークを隠す場合は設定


    def get_element_for_path(file_path):
        """ファイルパスが属するプラグイン内のエレメントを特定する"""
        if not file_path or file_path.startswith("untitled:"):
            return None
            
        plugin = project_tree.active_plugin
        if not plugin or not hasattr(project_tree, "current_project_path"):
            return None
        
        try:
            rel_path = os.path.relpath(file_path, project_tree.current_project_path)
            norm_rel_dir = os.path.normpath(os.path.dirname(rel_path))
            
            for element in plugin.elements:
                e_path = os.path.normpath(element.path)
                if norm_rel_dir == e_path or norm_rel_dir.startswith(e_path + os.sep):
                    return element
        except Exception:
            pass
        return None

    # --- ビュー切り替えボタンのメニュー更新ロジック ---
    def update_editor_selector(index):
        if not view_selector or not window.editorTabs or index < 0:
            if view_selector: view_selector.setVisible(False)
            return
            
        widget = window.editorTabs.widget(index)
        if not widget:
            view_selector.setVisible(False)
            return
            
        available_editors = getattr(widget, "available_editors", [])
        current_editor_id = editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID))
        
        if not available_editors:
            view_selector.setVisible(False)
            return
        
        # メニューの構築
        menu = QMenu(view_selector)
        current_editor_name = tr("MainWindow", "テキストエディタ")
        
        # 1. 外部定義エディタ
        for editor in available_editors:
            action = menu.addAction(editor.name)
            action.setData(editor.editor_id)
            if editor.editor_id == current_editor_id:
                current_editor_name = editor.name
                action.setCheckable(True)
                action.setChecked(True)
            action.triggered.connect(lambda checked=False, e_id=editor.editor_id: on_editor_selected(e_id))
            
        menu.addSeparator()
        
        # 2. 標準テキストエディタ
        script_action = menu.addAction(tr("MainWindow", "テキストエディタ"))
        script_action.setData(TEXT_EDITOR_ID)
        if current_editor_id == TEXT_EDITOR_ID:
            script_action.setCheckable(True)
            script_action.setChecked(True)
        script_action.triggered.connect(lambda checked=False: on_editor_selected(TEXT_EDITOR_ID))
        
        view_selector.setMenu(menu)
        view_selector.setText("")
        view_selector.setToolTip(current_editor_name)
        view_selector.setFixedSize(32, 28)
        view_selector.setVisible(True)
        view_selector.update() # 再描画を促す

    def on_editor_selected(editor_id):
        editor_id = editor_registry.normalize_editor_id(editor_id)
        current_tab_idx = window.editorTabs.currentIndex()
        if current_tab_idx < 0:
            return
            
        file_path = window.editorTabs.tabToolTip(current_tab_idx)
        open_file(file_path, editor_id)

    def _tab_text_without_dirty_marker(text):
        return text[1:] if text.startswith("*") else text

    def mark_tab_dirty(widget):
        if getattr(widget, "is_dirty", False):
            return
        widget.is_dirty = True
        index = window.editorTabs.indexOf(widget)
        if index >= 0:
            text = window.editorTabs.tabText(index)
            if not text.startswith("*"):
                window.editorTabs.setTabText(index, f"*{text}")
            project_tree.update_open_editors(window.editorTabs)

    def mark_tab_clean(widget):
        widget.is_dirty = False
        index = window.editorTabs.indexOf(widget)
        if index >= 0:
            text = window.editorTabs.tabText(index)
            clean_text = _tab_text_without_dirty_marker(text)
            if clean_text != text:
                window.editorTabs.setTabText(index, clean_text)
            project_tree.update_open_editors(window.editorTabs)

    def _path_for_save_dialog(widget):
        file_path = getattr(widget, "file_path", "")
        if file_path and not file_path.startswith("untitled:"):
            return file_path
        project_path = getattr(project_tree, "current_project_path", "")
        if project_path:
            return project_path
        return base_dir

    def save_text_widget(widget, save_as=False):
        file_path = getattr(widget, "file_path", "")
        if save_as or not file_path or file_path.startswith("untitled:"):
            file_path, _ = QFileDialog.getSaveFileName(window, "Save File", _path_for_save_dialog(widget))
            if not file_path:
                return False

        element = get_element_for_path(file_path)
        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)

        try:
            with open(file_path, "w", encoding=encoding) as handle:
                handle.write(widget.toPlainText())
        except Exception as error:
            window.statusBar().showMessage(f"Failed to save file: {error}", 5000)
            return False

        widget.file_path = file_path
        widget.content = widget.toPlainText()
        widget._last_notified_content = widget.content
        index = window.editorTabs.indexOf(widget)
        if index >= 0:
            window.editorTabs.setTabToolTip(index, file_path)
            window.editorTabs.setTabText(index, os.path.basename(file_path))
            window.editorTabs.setTabIcon(index, project_tree.get_icon_for_path(file_path))

        mark_tab_clean(widget)
        window.statusBar().showMessage(f"Saved: {file_path}", 3000)
        return True

    def save_tab(widget, save_as=False):
        if not widget:
            return False

        method_name = "on_save_as_triggered" if save_as else "on_save_triggered"
        save = getattr(widget, method_name, None)
        if not callable(save):
            return False

        try:
            result = save()
        except Exception as error:
            window.statusBar().showMessage(f"Failed to save tab: {error}", 5000)
            return False

        success = result is not False
        if success:
            mark_tab_clean(widget)
            file_path = getattr(widget, "file_path", None)
            if file_path and not str(file_path).startswith("untitled:"):
                core.api.notify_file_saved(file_path)
        return success

    def save_current_tab():
        if not window.editorTabs:
            return False
        index = window.editorTabs.currentIndex()
        if index < 0:
            return False
        return save_tab(window.editorTabs.widget(index), False)

    def save_current_tab_as():
        if not window.editorTabs:
            return False
        index = window.editorTabs.currentIndex()
        if index < 0:
            return False
        return save_tab(window.editorTabs.widget(index), True)

    def save_all_tabs():
        if not window.editorTabs:
            return False
        ok = True
        for index in range(window.editorTabs.count()):
            widget = window.editorTabs.widget(index)
            if getattr(widget, "is_dirty", True):
                ok = save_tab(widget, False) and ok
        return ok

    def create_editor_widget(editor_id, file_path, content, available_editors):
        editor_id = editor_registry.normalize_editor_id(editor_id)
        if editor_id == TEXT_EDITOR_ID:
            widget = EditorWidget()
            widget.setPlainText(content)
            widget.on_save_triggered = lambda w=widget: save_text_widget(w, False)
            widget.on_save_as_triggered = lambda w=widget: save_text_widget(w, True)
            widget.textChanged.connect(lambda w=widget: mark_tab_dirty(w))
        else:
            widget = editor_registry.create_editor_widget(editor_id, window.editorTabs, file_path, content)
            if not widget:
                # 失敗した場合はテキストエディタ
                return create_editor_widget(TEXT_EDITOR_ID, file_path, content, available_editors)
        
        widget.editor_id = editor_id
        widget.file_path = file_path
        widget.content = content
        widget.available_editors = available_editors
        widget.is_dirty = False
        element = get_element_for_path(file_path)
        if element:
            widget.active_plugin = element.plugin
        widget._last_notified_content = content # 最後に通知したときの内容


        controller = getattr(widget, "plugin_controller", None)
        if controller:
            if not callable(getattr(widget, "on_save_triggered", None)) and callable(getattr(controller, "on_save_triggered", None)):
                widget.on_save_triggered = controller.on_save_triggered
            if not callable(getattr(widget, "on_save_as_triggered", None)) and callable(getattr(controller, "on_save_as_triggered", None)):
                widget.on_save_as_triggered = controller.on_save_as_triggered

        if editor_id != TEXT_EDITOR_ID:
            from PySide6.QtCore import QTimer

            def check_content_change(w=widget):
                try:
                    current_content = getattr(w, "content", None)
                    if current_content is not None and current_content != w._last_notified_content:
                        w._last_notified_content = current_content
                        mark_tab_dirty(w)
                except (RuntimeError, ReferenceError):
                    if hasattr(w, "_dirty_timer"):
                        w._dirty_timer.stop()

            widget._dirty_timer = QTimer(widget)
            widget._dirty_timer.timeout.connect(check_content_change)
            widget._dirty_timer.start(100)

        return widget

    def _open_file_legacy_unused(file_path, editor_id=None):
        if not window.editorTabs:
            return
            
        # 既に開いているか確認（同じファイルかつ同じエディタ）
        for i in range(window.editorTabs.count()):
            widget = window.editorTabs.widget(i)
            if window.editorTabs.tabToolTip(i) == file_path and editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID)) == editor_id:
                window.editorTabs.setCurrentIndex(i)
                update_editor_selector(i)
                return
        
        # エレメントと利用可能なエディタの特定
        element = get_element_for_path(file_path)
        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)
        
        try:
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                content = f.read()
            
            available_editors = []
            if element:
                available_editors = editor_registry.get_editors_for_element(element)
            
            # ウィジェットの生成
            editor = create_editor_widget(editor_id, file_path, content, available_editors)
            
            file_name = os.path.basename(file_path)
            if editor_id != TEXT_EDITOR_ID:
                file_name = f"[E] {file_name}"

            icon = project_tree.get_icon_for_path(file_path)
            index = window.editorTabs.addTab(editor, icon, file_name)
            window.editorTabs.setTabToolTip(index, file_path)
            window.editorTabs.setCurrentIndex(index)
            update_editor_selector(index)
            
            # 「開いているエディター」リストの更新
            project_tree.update_open_editors(window.editorTabs)
        except Exception as e:
            print(f"ファイルを開けませんでした: {e}")

    # 無題タブのID管理
    untitled_id_counter = [0]

    def open_untitled_tab(name, content="", editor_id=TEXT_EDITOR_ID):
        editor_id = editor_registry.normalize_editor_id(editor_id)
        if not window.editorTabs:
            return
            
        untitled_id_counter[0] += 1
        virtual_path = f"untitled:{untitled_id_counter[0]}"
        
        # 利用可能なエディタを判定（もしあれば）
        # ※無題タブの場合はパスがないため、デフォルトのままにするか、IDから類推する
        available_editors = []
        if editor_id != TEXT_EDITOR_ID:
            editor_definition = editor_registry.get_editor(editor_id)
            if editor_definition:
                available_editors = [editor_definition]
        
        editor = create_editor_widget(editor_id, virtual_path, content, available_editors)
        
        from PySide6.QtGui import QIcon
        icon = QIcon() # デフォルト
        # アイコンディレクトリがあればデフォルトファイルアイコンを設定
        icons_dir = os.path.join(base_dir, "assets", "icons")
        if os.path.exists(icons_dir):
            from core.utils import load_svg_icon
            text_color = window.palette().color(window.foregroundRole()).name()
            icon = load_svg_icon(os.path.join(icons_dir, "file.svg"), text_color)

        tab_name = f"[E] {name}" if editor_id != TEXT_EDITOR_ID else name
        index = window.editorTabs.addTab(editor, icon, tab_name)
        window.editorTabs.setTabToolTip(index, virtual_path)
        window.editorTabs.setCurrentIndex(index)
        update_editor_selector(index)
        
        project_tree.update_open_editors(window.editorTabs)

    def open_file(file_path, editor_id=None):
        if not window.editorTabs:
            return

        element = get_element_for_path(file_path)
        available_editors = editor_registry.get_editors_for_element(element) if element else []
        if editor_id is None:
            editor_id = TEXT_EDITOR_ID
        else:
            editor_id = editor_registry.normalize_editor_id(editor_id)

        for i in range(window.editorTabs.count()):
            widget = window.editorTabs.widget(i)
            current_editor_id = editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID))
            if window.editorTabs.tabToolTip(i) == file_path and current_editor_id == editor_id:
                window.editorTabs.setCurrentIndex(i)
                update_editor_selector(i)
                return

        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)

        try:
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                content = f.read()

            editor = create_editor_widget(editor_id, file_path, content, available_editors)
            file_name = os.path.basename(file_path)
            if editor_id != TEXT_EDITOR_ID:
                file_name = f"[E] {file_name}"

            icon = project_tree.get_icon_for_path(file_path)
            index = window.editorTabs.addTab(editor, icon, file_name)
            window.editorTabs.setTabToolTip(index, file_path)
            window.editorTabs.setCurrentIndex(index)
            update_editor_selector(index)
            project_tree.update_open_editors(window.editorTabs)
        except Exception as e:
            print(f"ファイルを開けませんでした: {e}")

    window.open_file = open_file
    window.open_untitled_tab = open_untitled_tab

    action_save = window.findChild(object, "actionSave")
    if action_save:
        action_save.triggered.connect(save_current_tab)

    action_save_as = window.findChild(object, "actionSaveAs")
    if action_save_as:
        action_save_as.triggered.connect(save_current_tab_as)

    action_save_all = window.findChild(object, "actionSaveAll")
    if action_save_all:
        action_save_all.triggered.connect(save_all_tabs)



    core.api.register_editor_handler({
        "get_element_for_file": get_element_for_path,
        "get_editors_for_file": lambda file_path, inc=True: 
            [{"id": e.editor_id, "name": e.name} for e in (editor_registry.get_editors_for_element(get_element_for_path(file_path)) or [])] + ([{"id": TEXT_EDITOR_ID, "name": editor_registry.get_editor(TEXT_EDITOR_ID).name}] if inc else [])
    })

    core.api.register_active_plugin_handler(lambda: project_tree.active_plugin)


    # --- アクティビティバーの設定 ---
    activity_bar = window.findChild(QWidget, "TLeftActivityBar")
    dock_action_map = {} # {QDockWidget: QAction}
    
    def update_activity_bar(dock_widget, area):
        if not activity_bar:
            return
        is_left = (area == Qt.DockWidgetArea.LeftDockWidgetArea)
        
        if is_left and dock_widget not in dock_action_map:
            # 左側にドッキングされ、まだ登録されていない場合
            action = dock_widget.toggleViewAction()
            activity_bar.addAction(action)
            dock_action_map[dock_widget] = action
        elif not is_left and dock_widget in dock_action_map:
            # 左側から離れ、登録されている場合
            action = dock_action_map.pop(dock_widget)
            activity_bar.removeAction(action)

    if activity_bar:
        activity_bar.setIconSize(QSize(28, 28))
        activity_bar.setMovable(False)

    for dock in docks:
        dock.dockLocationChanged.connect(lambda area, d=dock: update_activity_bar(d, area))
        dock.topLevelChanged.connect(lambda floating, d=dock: update_activity_bar(d, window.dockWidgetArea(d)))
        current_area = window.dockWidgetArea(dock)
        update_activity_bar(dock, current_area)

    # --- プラグインの読み込みとメニュー設定 ---
    from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout
    
    plugins_dir = os.path.join(base_dir, "plugins")
    plugin_manager = PluginManager(plugins_dir)
    plugins = plugin_manager.load_plugins()

    def on_plugin_selected(plugin):
        if not plugin:
            return
        print(f"プラグインが選択されました: {plugin.name} (Version: {plugin.version})")
        window.statusBar().showMessage(f"プラグイン '{plugin.name}' が選択されました。")
        # ProjectTreeDock にプラグインを通知
        project_tree.set_active_plugin(plugin)
        editor_registry.register_plugin(plugin)
        
        # 全タブの利用可能なエディタを更新
        if window.editorTabs:
            for i in range(window.editorTabs.count()):
                w = window.editorTabs.widget(i)
                path = window.editorTabs.tabToolTip(i)
                elem = get_element_for_path(path)
                if elem:
                    w.available_editors = editor_registry.get_editors_for_element(elem)
                else:
                    w.available_editors = []
            update_editor_selector(window.editorTabs.currentIndex())


    # メニューバーにコンボボックスを配置
    menubar = window.menuBar()
    if menubar:
        plugin_container = QWidget()
        plugin_layout = QHBoxLayout(plugin_container)
        plugin_layout.setContentsMargins(10, 0, 10, 0)
        plugin_layout.setSpacing(5)
        
        label = QLabel(tr("MainWindow", "プラグイン:"))
        label.setStyleSheet("font-weight: bold; color: #888;")
        plugin_layout.addWidget(label)
        
        from PySide6.QtGui import QIcon, QPixmap
        
        plugin_combo = QComboBox()
        plugin_combo.setMinimumWidth(200)
        plugin_combo.setIconSize(QSize(20, 20))
        
        # プラグインをコンボボックスに追加
        for plugin in plugins:
            if plugin.icon_path and os.path.exists(plugin.icon_path):
                icon = QIcon()
                pixmap = QPixmap(plugin.icon_path)
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
                icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
                icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
                plugin_combo.addItem(icon, plugin.name, plugin)
            else:
                plugin_combo.addItem(plugin.name, plugin)
            
        plugin_layout.addWidget(plugin_combo)
        
        # プラグイン設定ボタン
        from core.utils import load_svg_icon
        settings_button = QToolButton()
        settings_button.setIcon(load_svg_icon(os.path.join(base_dir, "assets/icons/settings.svg"), "#ffffff"))
        settings_button.setToolTip(tr("MainWindow", "プラグイン設定"))
        settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        plugin_layout.addWidget(settings_button)

        def on_settings_clicked():
            plugin = plugin_combo.itemData(plugin_combo.currentIndex())
            if plugin:
                # ProjectTreeDockから現在のプロジェクトパスを取得
                project_path = getattr(project_tree, "current_project_path", None)
                plugin.show_settings(window, project_path)
        
        settings_button.clicked.connect(on_settings_clicked)
        
        menubar.setCornerWidget(plugin_container, Qt.Corner.TopRightCorner)
        
        plugin_combo.currentIndexChanged.connect(
            lambda index: on_plugin_selected(plugin_combo.itemData(index))
        )
        
        if plugins:
            plugin_combo.setCurrentIndex(0)
            on_plugin_selected(plugins[0])

    # --- core.api のハンドラ登録 ---
    # 1. メッセージ (ステータスバー)
    def get_plugin_by_id(plugin_id):
        for plugin in plugins:
            if plugin.id == plugin_id:
                return plugin
        return None

    def select_plugin(plugin):
        if not plugin:
            return False
        try:
            index = plugin_combo.findData(plugin)
            if index >= 0:
                plugin_combo.setCurrentIndex(index)
        except NameError:
            pass
        on_plugin_selected(plugin)
        return True

    def plugin_export_project_data(plugin, context):
        if not plugin or not plugin.module:
            return {}
        export = getattr(plugin.module, "export_project_data", None)
        if not callable(export):
            return {}
        return export(plugin, context) or {}

    def plugin_import_project_data(plugin, context, data):
        if not plugin or not plugin.module:
            return
        import_data = getattr(plugin.module, "import_project_data", None)
        if callable(import_data):
            import_data(plugin, context, data or {})

    def active_required_plugins():
        plugin = getattr(project_tree, "active_plugin", None)
        return [plugin.id] if plugin else []

    def export_all_plugin_data(context):
        result = {}
        for plugin_id in context["required_plugins"]:
            plugin = get_plugin_by_id(plugin_id)
            result[plugin_id] = plugin_export_project_data(plugin, context)
        return result

    PROJECT_TYPE_REFERENCE = "reference"
    PROJECT_TYPE_EMBEDDED = "embedded"

    def normalise_project_type(project_type):
        if project_type == PROJECT_TYPE_REFERENCE:
            return PROJECT_TYPE_REFERENCE
        if project_type == PROJECT_TYPE_EMBEDDED:
            return PROJECT_TYPE_EMBEDDED
        return PROJECT_TYPE_REFERENCE

    def current_project_metadata(project_type):
        project_type = normalise_project_type(project_type)
        project_path = getattr(project_tree, "current_project_path", None)
        display_name = os.path.basename(os.path.normpath(project_path)) if project_path else "Untitled Project"
        metadata = {
            "schema_version": 1,
            "project_type": project_type,
            "required_plugins": active_required_plugins(),
            "display_name": display_name,
            "mod_root": "mod" if project_type == PROJECT_TYPE_EMBEDDED else project_path,
        }
        if project_type == PROJECT_TYPE_EMBEDDED:
            metadata["source_mod_root"] = getattr(window, "source_mod_root", None) or project_path
        return metadata

    def project_context(metadata, project_file, mod_root):
        return {
            "project_file": project_file,
            "project_type": normalise_project_type(metadata.get("project_type")),
            "mod_root": mod_root,
            "required_plugins": metadata.get("required_plugins", []),
            "metadata": metadata,
        }

    def write_json_file(path, data):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)

    def read_json_file(path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def ensure_project_path():
        project_path = getattr(project_tree, "current_project_path", None)
        if project_path and os.path.isdir(project_path):
            return project_path
        window.statusBar().showMessage("No project folder is open.", 5000)
        return None

    def project_save_path_dialog():
        start_dir = getattr(project_tree, "current_project_path", None) or base_dir
        path, selected_filter = QFileDialog.getSaveFileName(
            window,
            "プロジェクトを保存",
            start_dir,
            "参照型プロジェクト (*.pdxproj);;内包型プロジェクト (*.pdxpkg)",
        )
        if not path:
            return None
        if not path.lower().endswith((".pdxproj", ".pdxpkg")):
            path += ".pdxpkg" if "内包型" in selected_filter else ".pdxproj"
        return path

    def project_type_for_path(path):
        return PROJECT_TYPE_EMBEDDED if path.lower().endswith(".pdxpkg") else PROJECT_TYPE_REFERENCE

    def save_reference_project(path):
        mod_root = ensure_project_path()
        if not mod_root:
            return False
        metadata = current_project_metadata(PROJECT_TYPE_REFERENCE)
        context = project_context(metadata, path, mod_root)
        metadata["plugin_data"] = export_all_plugin_data(context)
        write_json_file(path, metadata)
        window.current_project_file = path
        window.current_project_type = PROJECT_TYPE_REFERENCE
        window.statusBar().showMessage(f"Project saved: {path}", 3000)
        return True

    def add_directory_to_zip(archive, source_dir, archive_root):
        for root, _, files in os.walk(source_dir):
            for filename in files:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, source_dir)
                archive_path = os.path.join(archive_root, rel_path).replace("\\", "/")
                archive.write(full_path, archive_path)

    def save_embedded_project(path):
        mod_root = ensure_project_path()
        if not mod_root:
            return False
        metadata = current_project_metadata(PROJECT_TYPE_EMBEDDED)
        context = project_context(metadata, path, mod_root)
        plugin_data = export_all_plugin_data(context)
        temp_fd, temp_path = tempfile.mkstemp(suffix=".pdxpkg")
        os.close(temp_fd)
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("project.json", json.dumps(metadata, indent=4, ensure_ascii=False))
            add_directory_to_zip(archive, mod_root, "mod")
            for plugin_id, data in plugin_data.items():
                for data_key, payload in (data or {}).items():
                    archive.writestr(
                        f"plugin_data/{plugin_id}/{data_key}.json",
                        json.dumps(payload, indent=4, ensure_ascii=False),
                    )
        os.replace(temp_path, path)
        window.current_project_file = path
        window.current_project_type = PROJECT_TYPE_EMBEDDED
        window.statusBar().showMessage(f"Project package saved: {path}", 3000)
        return True

    def save_project_to(path):
        if not save_all_tabs():
            window.statusBar().showMessage("Project save cancelled because a tab could not be saved.", 5000)
            return False
        try:
            if project_type_for_path(path) == PROJECT_TYPE_EMBEDDED:
                return save_embedded_project(path)
            return save_reference_project(path)
        except Exception as error:
            window.statusBar().showMessage(f"Failed to save project: {error}", 5000)
            return False

    def save_project():
        path = getattr(window, "current_project_file", None)
        if not path:
            return save_project_as()
        return save_project_to(path)

    def save_project_as():
        path = project_save_path_dialog()
        if not path:
            return False
        return save_project_to(path)

    def open_project_dialog():
        path, _ = QFileDialog.getOpenFileName(
            window,
            "プロジェクトを開く",
            base_dir,
            "PDX Mod Studio プロジェクト (*.pdxproj *.pdxpkg)",
        )
        if path:
            open_project_file(path)

    def apply_required_plugins(metadata):
        missing = []
        for plugin_id in metadata.get("required_plugins", []):
            plugin = get_plugin_by_id(plugin_id)
            if plugin:
                select_plugin(plugin)
            else:
                missing.append(plugin_id)
        if missing:
            window.statusBar().showMessage(f"Missing required plugins: {', '.join(missing)}", 7000)

    def import_all_plugin_data(metadata, project_file, mod_root, plugin_data):
        context = project_context(metadata, project_file, mod_root)
        for plugin_id, data in (plugin_data or {}).items():
            plugin = get_plugin_by_id(plugin_id)
            if plugin:
                plugin_import_project_data(plugin, context, data)

    def open_reference_project(path):
        metadata = read_json_file(path)
        mod_root = metadata.get("mod_root")
        if not mod_root or not os.path.isdir(mod_root):
            window.statusBar().showMessage("Project mod_root does not exist.", 7000)
            return False
        apply_required_plugins(metadata)
        project_tree.load_project(mod_root)
        import_all_plugin_data(metadata, path, mod_root, metadata.get("plugin_data", {}))
        window.current_project_file = path
        window.current_project_type = PROJECT_TYPE_REFERENCE
        window.statusBar().showMessage(f"Project opened: {path}", 3000)
        return True

    def read_zip_json(archive, name):
        with archive.open(name) as handle:
            return json.loads(handle.read().decode("utf-8"))

    def open_embedded_project(path):
        workspace = tempfile.mkdtemp(prefix="pdx_mod_studio_")
        with zipfile.ZipFile(path, "r") as archive:
            metadata = read_zip_json(archive, "project.json")
            archive.extractall(workspace)
        mod_root = os.path.join(workspace, metadata.get("mod_root", "mod"))
        if not os.path.isdir(mod_root):
            window.statusBar().showMessage("Project package does not contain mod/.", 7000)
            return False
        apply_required_plugins(metadata)
        project_tree.load_project(mod_root)
        plugin_data = {}
        plugin_data_root = os.path.join(workspace, "plugin_data")
        for plugin_id in metadata.get("required_plugins", []):
            plugin_dir = os.path.join(plugin_data_root, plugin_id)
            plugin_data[plugin_id] = {}
            if os.path.isdir(plugin_dir):
                for filename in os.listdir(plugin_dir):
                    if filename.endswith(".json"):
                        data_key = os.path.splitext(filename)[0]
                        plugin_data[plugin_id][data_key] = read_json_file(os.path.join(plugin_dir, filename))
        import_all_plugin_data(metadata, path, mod_root, plugin_data)
        window.current_project_file = path
        window.current_project_type = PROJECT_TYPE_EMBEDDED
        window.embedded_project_workspace = workspace
        window.source_mod_root = metadata.get("source_mod_root")
        window.statusBar().showMessage(f"Project package opened: {path}", 3000)
        return True

    def open_project_file(path):
        try:
            if path.lower().endswith(".pdxpkg"):
                return open_embedded_project(path)
            return open_reference_project(path)
        except Exception as error:
            window.statusBar().showMessage(f"Failed to open project: {error}", 7000)
            return False

    action_open_project = window.findChild(object, "actionOpenProject")
    if action_open_project:
        action_open_project.triggered.connect(open_project_dialog)

    action_save_project = window.findChild(object, "actionSaveProject")
    if action_save_project:
        action_save_project.triggered.connect(save_project)

    action_save_project_as = window.findChild(object, "actionSaveProjectAs")
    if action_save_project_as:
        action_save_project_as.triggered.connect(save_project_as)

    core.api.register_message_handler(lambda text, timeout: window.statusBar().showMessage(text, timeout))

    # 2. 進捗 (ステータスバーにプログレスバーを追加)
    from PySide6.QtWidgets import QProgressBar
    progress_bar = QProgressBar()
    progress_bar.setMaximumWidth(200)
    progress_bar.setTextVisible(True)
    progress_bar.setVisible(False)
    window.statusBar().addPermanentWidget(progress_bar)
    
    def on_progress(value, text):
        if value < 0 or value >= 100:
            progress_bar.setVisible(False)
            if text: window.statusBar().showMessage(text, 3000)
        else:
            progress_bar.setVisible(True)
            progress_bar.setValue(value)
            if text: progress_bar.setFormat(f"{text}: %p%")
            else: progress_bar.setFormat("%p%")

    core.api.register_progress_handler(on_progress)

    # 3. タブ操作
    def get_open_tabs():
        tabs = []
        if window.editorTabs:
            for i in range(window.editorTabs.count()):
                widget = window.editorTabs.widget(i)
                tabs.append({
                    "index": i,
                    "name": window.editorTabs.tabText(i),
                    "path": window.editorTabs.tabToolTip(i),
                    "widget": widget,
                    "is_dirty": getattr(widget, "is_dirty", False),
                    "editor_id": editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID))
                })
        return tabs


    core.api.register_tabs_handler({
        "get_tabs": get_open_tabs,
        "open_tab": open_file,
        "open_untitled_tab": open_untitled_tab
    })


    # ウィンドウを表示
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
