import sys
import os
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QToolButton, QWidget
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
    from core.mode_manager import ModeManager
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

    # --- エディタータブの設定 ---
    window.editorTabs = window.findChild(object, "editorTabs")
    if window.editorTabs:
        window.editorTabs.tabCloseRequested.connect(lambda index: (
            window.editorTabs.removeTab(index),
            project_tree.update_open_editors(window.editorTabs)
        ))
        def on_tab_changed(index):
            project_tree.sync_selection(index)
            update_mode_selector(index)
            
        window.editorTabs.currentChanged.connect(on_tab_changed)
        # 初期状態のリスト更新
        project_tree.update_open_editors(window.editorTabs)

    # --- モード管理の初期化 ---
    mode_manager = ModeManager()
    
    # モード切り替え用のコンボボックスをタブの右端に配置
    from PySide6.QtWidgets import QComboBox
    mode_selector = QComboBox()
    mode_selector.setMinimumWidth(150)
    mode_selector.setVisible(False) # 初期状態は非表示
    if window.editorTabs:
        window.editorTabs.setCornerWidget(mode_selector, Qt.Corner.TopRightCorner)

    def get_element_for_path(file_path):
        """ファイルパスが属するプラグイン内のエレメントを特定する"""
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

    def update_mode_selector(index):
        if not window.editorTabs or index < 0:
            mode_selector.setVisible(False)
            return
            
        widget = window.editorTabs.widget(index)
        if not widget:
            mode_selector.setVisible(False)
            return
            
        # タブに紐付けられた利用可能なモードリストを取得
        available_modes = getattr(widget, "available_modes", [])
        current_mode_id = getattr(widget, "current_mode_id", "script_mode")
        
        mode_selector.blockSignals(True)
        mode_selector.clear()
        
        # 1. 外部定義モード
        for mode in available_modes:
            mode_selector.addItem(mode.name, mode.mode_id)
            
        # 2. 標準スクリプトモード (常に最後に追加)
        mode_selector.addItem("スクリプトモード", "script_mode")
        
        # 現在のモードを選択
        idx = mode_selector.findData(current_mode_id)
        if idx >= 0:
            mode_selector.setCurrentIndex(idx)
        
        mode_selector.blockSignals(False)
        mode_selector.setVisible(True)

    def on_mode_selector_changed(index):
        current_tab_idx = window.editorTabs.currentIndex()
        if current_tab_idx < 0:
            return
            
        mode_id = mode_selector.itemData(index)
        widget = window.editorTabs.widget(current_tab_idx)
        if not widget or getattr(widget, "current_mode_id", "") == mode_id:
            return
            
        was_dirty = getattr(widget, "is_dirty", False)

        # モードの差し替え
        file_path = window.editorTabs.tabToolTip(current_tab_idx)
        # 現在のコンテンツを保持（変更されている可能性があるため）
        content = ""
        if hasattr(widget, "toPlainText"):
            content = widget.toPlainText()
        elif hasattr(widget, "content"): # カスタムモードの場合
            content = widget.content
            
        new_widget = create_widget_for_mode(mode_id, file_path, content, getattr(widget, "available_modes", []))
        if new_widget:
            # タブのウィジェットを差し替え
            window.editorTabs.removeTab(current_tab_idx)
            icon = project_tree.get_icon_for_path(file_path)
            file_name = os.path.basename(file_path)
            window.editorTabs.insertTab(current_tab_idx, new_widget, icon, file_name)
            window.editorTabs.setTabToolTip(current_tab_idx, file_path)
            window.editorTabs.setCurrentIndex(current_tab_idx)
            
            # 未保存状態を引き継ぐ
            if was_dirty:
                set_tab_dirty(current_tab_idx, True)

    mode_selector.currentIndexChanged.connect(on_mode_selector_changed)

    def create_widget_for_mode(mode_id, file_path, content, available_modes):
        if mode_id == "script_mode":
            widget = EditorWidget()
            widget.setPlainText(content)
        else:
            widget = mode_manager.create_mode_widget(mode_id, window.editorTabs, file_path, content)
            if not widget:
                # 失敗した場合はスクリプトモード
                return create_widget_for_mode("script_mode", file_path, content, available_modes)
        
        widget.current_mode_id = mode_id
        widget.available_modes = available_modes
        widget.is_dirty = False
        widget._last_notified_content = content # 最後に通知したときの内容

        # --- 自動変更検知の仕組み（安全なタイマー監視） ---
        from PySide6.QtCore import QTimer
        def check_content_change():
            # ウィジェットが破棄されていたら停止
            try:
                current_content = getattr(widget, "content", None)
                if current_content is not None and current_content != widget._last_notified_content:
                    widget._last_notified_content = current_content
                    idx = window.editorTabs.indexOf(widget)
                    if idx >= 0:
                        set_tab_dirty(idx, True)
            except (RuntimeError, ReferenceError):
                # ウィジェットが既に削除されている場合
                if hasattr(widget, "_dirty_timer"):
                    widget._dirty_timer.stop()

        # 100msごとにチェック（負荷は無視できるほど低いです）
        widget._dirty_timer = QTimer(widget)
        widget._dirty_timer.timeout.connect(check_content_change)
        widget._dirty_timer.start(100)

        if mode_id == "script_mode":
            widget.textChanged.connect(lambda: set_tab_dirty(window.editorTabs.indexOf(widget), True))

        return widget

    def open_file(file_path):
        if not window.editorTabs:
            return
            
        # 既に開いているか確認
        for i in range(window.editorTabs.count()):
            if window.editorTabs.tabToolTip(i) == file_path:
                window.editorTabs.setCurrentIndex(i)
                return
        
        # エレメントと利用可能なモードの特定
        element = get_element_for_path(file_path)
        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)
        
        try:
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                content = f.read()
            
            available_modes = []
            if element:
                available_modes = mode_manager.get_modes_for_element(element)
            
            # 初期モードの決定
            initial_mode_id = available_modes[0].mode_id if available_modes else "script_mode"
            
            # ウィジェットの生成
            editor = create_widget_for_mode(initial_mode_id, file_path, content, available_modes)
            
            file_name = os.path.basename(file_path)
            icon = project_tree.get_icon_for_path(file_path)
            index = window.editorTabs.addTab(editor, icon, file_name)
            window.editorTabs.setTabToolTip(index, file_path)
            window.editorTabs.setCurrentIndex(index)
            
            # 「開いているエディター」リストの更新
            project_tree.update_open_editors(window.editorTabs)
        except Exception as e:
            print(f"ファイルを開けませんでした: {e}")

    window.open_file = open_file

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
            
        # エレメントからエンコーディングを取得
        element = get_element_for_path(file_path)
        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)
            
        try:
            with open(file_path, 'w', encoding=encoding) as f:
                f.write(content)
            window.statusBar().showMessage(f"保存しました: {file_path}", 3000)
            widget._last_notified_content = content
            set_tab_dirty(current_idx, False)
        except Exception as e:
            QMessageBox.critical(window, "保存エラー", f"ファイルを保存できませんでした: {e}")

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
                tabs.append({
                    "index": i,
                    "name": window.editorTabs.tabText(i),
                    "path": window.editorTabs.tabToolTip(i),
                    "widget": window.editorTabs.widget(i),
                    "is_dirty": getattr(window.editorTabs.widget(i), "is_dirty", False)
                })
        return tabs

    core.api.register_tabs_handler({
        "get_tabs": get_open_tabs,
        "open_tab": open_file
    })

    # ウィンドウを表示
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
