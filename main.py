import sys
import os
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QToolButton, QWidget, QTabBar, QFileDialog
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize
import core.api

def main():
    app = QApplication(sys.argv)
    
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
        print(f"UIファイルを開けませんでした: {ui_file_path}")
        sys.exit(-1)
        
    loader = QUiLoader()
    window = loader.load(ui_file)
    ui_file.close()
    
    if not window:
        print(f"UIのロードに失敗しました: {loader.errorString()}")
        sys.exit(-1)

    # --- アプリケーションアイコンの設定 ---
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
        current_editor_name = "テキストエディタ"
        
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
        script_action = menu.addAction("テキストエディタ")
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

    def create_editor_widget(editor_id, file_path, content, available_editors):
        editor_id = editor_registry.normalize_editor_id(editor_id)
        if editor_id == TEXT_EDITOR_ID:
            widget = EditorWidget()
            widget.setPlainText(content)
        else:
            widget = editor_registry.create_editor_widget(editor_id, window.editorTabs, file_path, content)
            if not widget:
                # 失敗した場合はテキストエディタ
                return create_editor_widget(TEXT_EDITOR_ID, file_path, content, available_editors)
        
        widget.editor_id = editor_id
        widget.available_editors = available_editors
        widget.is_dirty = False
        element = get_element_for_path(file_path)
        if element:
            widget.active_plugin = element.plugin
        widget._last_notified_content = content # 最後に通知したときの内容

        # --- 自動変更検知の仕組み（安全なタイマー監視） ---
        from PySide6.QtCore import QTimer
        def check_content_change():
            try:
                current_content = getattr(widget, "content", None)
                if current_content is not None and current_content != widget._last_notified_content:
                    widget._last_notified_content = current_content
                    idx = window.editorTabs.indexOf(widget)
                    if idx >= 0:
                        set_tab_dirty(idx, True)
            except (RuntimeError, ReferenceError):
                if hasattr(widget, "_dirty_timer"):
                    widget._dirty_timer.stop()

        widget._dirty_timer = QTimer(widget)
        widget._dirty_timer.timeout.connect(check_content_change)
        widget._dirty_timer.start(100)

        if editor_id == TEXT_EDITOR_ID:
            widget.textChanged.connect(lambda: set_tab_dirty(window.editorTabs.indexOf(widget), True))

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
        
        # 変更あり状態にする
        set_tab_dirty(index, True)
        project_tree.update_open_editors(window.editorTabs)

    def open_file(file_path, editor_id=None):
        if not window.editorTabs:
            return

        element = get_element_for_path(file_path)
        available_editors = editor_registry.get_editors_for_element(element) if element else []
        if editor_id is None:
            editor_id = available_editors[0].editor_id if available_editors else TEXT_EDITOR_ID
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


    # --- 保存機能の実実装 ---
    from PySide6.QtGui import QKeySequence, QAction
    from PySide6.QtWidgets import QMessageBox
    from core.utils import load_svg_icon

    # アイコンのロード
    text_color = window.palette().color(window.foregroundRole()).name()
    icon_dirty = load_svg_icon(os.path.join(base_dir, "assets/icons/save.svg"), "#ffcc00") # 目立つ色にする

    def set_tab_dirty(index, dirty):
        if index < 0 or index >= window.editorTabs.count():
            return
        widget = window.editorTabs.widget(index)
        widget.is_dirty = dirty
        
        file_path = window.editorTabs.tabToolTip(index)
        if dirty:
            window.editorTabs.setTabIcon(index, icon_dirty)
        else:
            # 元のアイコンに戻す
            icon = project_tree.get_icon_for_path(file_path)
            window.editorTabs.setTabIcon(index, icon)

    def save_current_file():
        current_idx = window.editorTabs.currentIndex()
        if current_idx < 0:
            return
            
        file_path = window.editorTabs.tabToolTip(current_idx)
        widget = window.editorTabs.widget(current_idx)
        
        content = ""
        if hasattr(widget, "toPlainText"):
            content = widget.toPlainText()
        elif hasattr(widget, "content"):
            content = widget.content
            
        # 「無題」の場合は保存ダイアログを出す
        if file_path.startswith("untitled:"):
            project_path = core.api.get_project_path() or os.path.expanduser("~")
            save_path, _ = QFileDialog.getSaveFileName(
                window, "名前を付けて保存", 
                project_path, "Text Files (*.txt);;All Files (*)"
            )
            if not save_path:
                return
            file_path = save_path

        # エレメントからエンコーディングを取得
        element = get_element_for_path(file_path)
        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)
            
        try:
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(content)
            
            # 保存成功後のタブ更新
            window.editorTabs.setTabToolTip(current_idx, file_path)
            new_name = os.path.basename(file_path)
            if editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID)) != TEXT_EDITOR_ID:
                new_name = f"[E] {new_name}"
            window.editorTabs.setTabText(current_idx, new_name)
            
            # アイコンも更新
            new_icon = project_tree.get_icon_for_path(file_path)
            window.editorTabs.setTabIcon(current_idx, new_icon)

            controller = getattr(widget, "plugin_controller", None)
            if controller and hasattr(controller, "on_save_triggered"):
                controller.on_save_triggered()
            window.statusBar().showMessage(f"保存しました: {file_path}", 3000)
            widget._last_notified_content = content
            set_tab_dirty(current_idx, False)
            
            core.api.notify_file_saved(file_path)
            # エクスプローラーの同期など
            project_tree.update_open_editors(window.editorTabs)
        except Exception as e:
            QMessageBox.critical(window, "保存エラー", f"ファイルを保存できませんでした: {e}")

    def on_file_saved(saved_file_path):
        # 他のタブで同じファイルが開かれていればリロードする
        for i in range(window.editorTabs.count()):
            widget = window.editorTabs.widget(i)
            if window.editorTabs.tabToolTip(i) == saved_file_path:
                if getattr(widget, "is_dirty", False):
                    # 未保存の変更がある場合は競合を避けるためスキップ (必要なら警告を出す)
                    continue
                
                element = get_element_for_path(saved_file_path)
                encoding = "utf-8"
                if element:
                    encoding = element.plugin.get_element_attribute(element, "encoding", file_path=saved_file_path)
                
                try:
                    with open(saved_file_path, 'r', encoding=encoding, errors='replace') as f:
                        new_content = f.read()
                    
                    # 現在のコンテンツと比較し、変更がなければ何もしない
                    current_content = ""
                    if hasattr(widget, "toPlainText"):
                        current_content = widget.toPlainText()
                    elif hasattr(widget, "content"):
                        current_content = widget.content
                        
                    if current_content == new_content:
                        continue

                    # 更新処理
                    if hasattr(widget, "setPlainText"):
                        # cursor位置などを保持する工夫が必要だが、一旦シンプルに更新
                        cursor = widget.textCursor()
                        pos = cursor.position()
                        widget.setPlainText(new_content)
                        cursor.setPosition(min(pos, len(new_content)))
                        widget.setTextCursor(cursor)
                    elif hasattr(widget, "plugin_controller") and hasattr(widget.plugin_controller, "set_content"):
                        widget.plugin_controller.set_content(new_content)
                        
                    widget._last_notified_content = new_content
                except Exception as e:
                    print(f"Failed to reload {saved_file_path}: {e}")

    core.api.register_file_saved_handler(on_file_saved)

    core.api.register_editor_handler({
        "get_element_for_file": get_element_for_path,
        "get_editors_for_file": lambda file_path, inc=True: 
            [{"id": e.editor_id, "name": e.name} for e in (editor_registry.get_editors_for_element(get_element_for_path(file_path)) or [])] + ([{"id": TEXT_EDITOR_ID, "name": editor_registry.get_editor(TEXT_EDITOR_ID).name}] if inc else [])
    })

    core.api.register_active_plugin_handler(lambda: project_tree.active_plugin)

    save_action = window.findChild(QAction, "actionSaveProject")
    if save_action:
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(save_current_file)
        # メニューに追加
        file_menu = window.findChild(QMenu, "menuFile")
        if file_menu:
            exit_action = window.findChild(QAction, "actionExit")
            file_menu.insertAction(exit_action, save_action)
            file_menu.insertSeparator(exit_action)
    else:
        # アクションが見つからない場合のフォールバック
        save_action = QAction("保存", window)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(save_current_file)
        window.addAction(save_action)

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
        
        label = QLabel("プラグイン:")
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
        settings_button.setToolTip("プラグイン設定")
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
