import sys
import os
import json
import tempfile
import zipfile
from core import save_result as save_result_utils
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

    # --- エディタパラメータ管理 ---
    window.pending_params = {} # {tab_id: params}
    window._tab_id_counter = 0

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
        def currentWidget(self): return self.stacked_widget.currentWidget()
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
    def close_editor_tab(index):
        widget = window.editorTabs.widget(index)
        tab_id = getattr(widget, "tab_id", None)
        if tab_id in window.pending_params:
            del window.pending_params[tab_id]
        window.editorTabs.removeTab(index)
        project_tree.update_open_editors(window.editorTabs)

    window.editorTabs.tabCloseRequested.connect(close_editor_tab)

    def on_tab_changed(index):
        project_tree.sync_selection(index)
        update_editor_selector(index)

    window.editorTabs.currentChanged.connect(on_tab_changed)
    # 初期状態のリスト更新
    project_tree.update_open_editors(window.editorTabs)

    # --- エディタ管理の初期化 ---
    editor_registry = EditorRegistry()
    TEXT_EDITOR_ID = editor_registry.text_editor_id
    window.editor_registry = editor_registry
    
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

    def get_available_editors_for_file(file_path, include_script=True):
        editors = [
            {"id": e.editor_id, "name": e.name}
            for e in (editor_registry.get_editors_for_element(get_element_for_path(file_path)) or [])
        ]
        if include_script:
            editors.append({"id": TEXT_EDITOR_ID, "name": editor_registry.get_editor(TEXT_EDITOR_ID).name})
        return editors

    window.get_available_editors_for_file = get_available_editors_for_file

    def next_tab_id():
        window._tab_id_counter += 1
        return f"tab:{window._tab_id_counter}"

    def find_widget_by_tab_id(tab_id):
        if not tab_id or not window.editorTabs:
            return None
        for i in range(window.editorTabs.count()):
            widget = window.editorTabs.widget(i)
            if getattr(widget, "tab_id", None) == tab_id:
                return widget
        return None

    def get_active_tab_info():
        if not window.editorTabs:
            return None
        index = window.editorTabs.currentIndex()
        if index < 0:
            return None
        widget = window.editorTabs.currentWidget()
        if not widget:
            return None
        plugin = getattr(widget, "active_plugin", None)
        return {
            "tab_id": getattr(widget, "tab_id", None),
            "path": window.editorTabs.tabToolTip(index),
            "editor_id": editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID)),
            "is_dirty": getattr(widget, "is_dirty", False),
            "plugin_id": getattr(plugin, "id", None),
        }

    def get_tab_plugin_id(tab_id=None):
        target_tab_id = tab_id
        if target_tab_id is None:
            active_tab = get_active_tab_info()
            target_tab_id = active_tab.get("tab_id") if active_tab else None
        target_widget = find_widget_by_tab_id(target_tab_id)
        if target_widget is not None:
            plugin = getattr(target_widget, "active_plugin", None)
            if plugin:
                return plugin.id
        return getattr(project_tree.active_plugin, "id", None)

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

    def is_virtual_tab_path(path):
        return not path or str(path).startswith("untitled:")

    def default_save_dialog_path(widget):
        current_path = getattr(widget, "file_path", "")
        if current_path and not is_virtual_tab_path(current_path):
            return current_path

        project_path = core.api.get_project_path()
        if project_path:
            tab_name = window.editorTabs.tabText(window.editorTabs.indexOf(widget)) if window.editorTabs.indexOf(widget) >= 0 else "untitled"
            clean_name = _tab_text_without_dirty_marker(tab_name).replace("[E] ", "").strip() or "untitled"
            return os.path.join(project_path, clean_name)

        return base_dir

    def build_plain_text_save_plan(widget, save_as=False):
        widget.save_plan = None
        current_path = getattr(widget, "file_path", "")
        requires_dialog = save_as or is_virtual_tab_path(current_path)
        target_path = current_path

        if requires_dialog:
            target_path, _ = QFileDialog.getSaveFileName(
                window,
                tr("MainWindow", "名前を付けて保存"),
                default_save_dialog_path(widget),
                tr("MainWindow", "All Files (*.*)"),
            )
            if not target_path:
                return save_result_utils.save_cancelled()

        widget.save_plan = {
            "tab_kind": "text",
            "dialog": "os_standard" if requires_dialog else None,
            "save_as": bool(requires_dialog),
            "targets": [
                {
                    "role": "primary",
                    "path": target_path,
                    "format": "text",
                }
            ],
        }
        return save_result_utils.save_success()

    def update_saved_widget_path(widget, path):
        if not path:
            return
        widget.file_path = path
        index = window.editorTabs.indexOf(widget)
        if index >= 0:
            window.editorTabs.setTabToolTip(index, path)
            clean_text = _tab_text_without_dirty_marker(window.editorTabs.tabText(index))
            editor_prefix = "[E] " if clean_text.startswith("[E] ") else ""
            window.editorTabs.setTabText(index, f"{editor_prefix}{os.path.basename(path)}")
            project_tree.update_open_editors(window.editorTabs)

    def show_save_result_message(result, default_timeout=5000):
        message = save_result_utils.save_result_message(result)
        if message:
            window.statusBar().showMessage(message, default_timeout)

    def write_plain_text_save_plan(widget):
        plan = getattr(widget, "save_plan", None) or {}
        targets = plan.get("targets", [])
        primary_target = targets[0] if targets else None
        target_path = primary_target.get("path", "") if isinstance(primary_target, dict) else ""
        if not target_path:
            window.statusBar().showMessage(tr("MainWindow", "保存先が未設定です。"), 4000)
            return save_result_utils.save_failed()

        try:
            parent = os.path.dirname(target_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            content = widget.toPlainText() if hasattr(widget, "toPlainText") else getattr(widget, "content", "")
            with open(target_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        except Exception as error:
            window.statusBar().showMessage(
                tr("MainWindow", "ファイルを書き込めませんでした: {error}").format(error=error),
                5000,
            )
            return save_result_utils.save_failed(message=str(error))

        update_saved_widget_path(widget, target_path)
        core.api.emit_event("file_saved", target_path)
        return save_result_utils.save_success(primary_path=target_path)

    def finish_successful_save(widget, result=None):
        if result is None:
            result = {}
        if not isinstance(result, dict):
            result = save_result_utils.normalize_save_result(result)

        primary_path = result.get("primary_path", "")
        if not primary_path:
            save_plan = getattr(widget, "save_plan", None)
            if isinstance(save_plan, dict):
                targets = save_plan.get("targets", [])
                primary_target = targets[0] if targets else None
                if isinstance(primary_target, dict):
                    primary_path = primary_target.get("path", "")
        if not primary_path:
            primary_path = getattr(widget, "file_path", "")

        if primary_path:
            update_saved_widget_path(widget, primary_path)
        mark_tab_clean(widget)

    def save_active_tab(save_as=False):
        if not window.editorTabs:
            return False

        widget = window.editorTabs.currentWidget()
        if not widget:
            window.statusBar().showMessage(tr("MainWindow", "保存するタブがありません。"), 3000)
            return False

        handler_name = "on_save_as_triggered" if save_as else "on_save_triggered"
        handler = getattr(widget, handler_name, None)
        if not callable(handler):
            window.statusBar().showMessage(tr("MainWindow", "このタブはまだ保存に対応していません。"), 4000)
            return False

        try:
            plan_result = save_result_utils.normalize_save_result(handler())
        except Exception as error:
            window.statusBar().showMessage(
                tr("MainWindow", "保存処理の呼び出しに失敗しました: {error}").format(error=error),
                5000,
            )
            return False

        if save_result_utils.is_save_cancelled(plan_result):
            show_save_result_message(plan_result)
            return False

        if not save_result_utils.is_save_success(plan_result):
            show_save_result_message(plan_result)
            return False

        save_plan = getattr(widget, "save_plan", None)
        if not save_plan:
            finish_successful_save(widget, plan_result)
            return True

        writer = getattr(widget, "on_write_save_plan", None)
        if not callable(writer):
            window.statusBar().showMessage(tr("MainWindow", "このタブはまだ書き込み処理に対応していません。"), 4000)
            return False

        try:
            write_result = save_result_utils.normalize_save_result(writer())
        except Exception as error:
            window.statusBar().showMessage(
                tr("MainWindow", "保存書き込みに失敗しました: {error}").format(error=error),
                5000,
            )
            return False

        if save_result_utils.is_save_success(write_result):
            finish_successful_save(widget, write_result)
            return True
        show_save_result_message(write_result)
        return False

    def create_editor_widget(editor_id, file_path, content, available_editors, params=None, tab_id=None):
        editor_id = editor_registry.normalize_editor_id(editor_id)
        if editor_id == TEXT_EDITOR_ID:
            widget = EditorWidget()
            widget.tab_id = tab_id
            widget.setPlainText(content)
            widget.textChanged.connect(lambda w=widget: mark_tab_dirty(w))
        else:
            widget = editor_registry.create_editor_widget(editor_id, window.editorTabs, file_path, content, tab_id=tab_id)
            if not widget:
                # 失敗した場合はテキストエディタ
                return create_editor_widget(TEXT_EDITOR_ID, file_path, content, available_editors, params, tab_id=tab_id)
        
        widget.editor_id = editor_id
        widget.file_path = file_path
        widget.content = content
        widget.available_editors = available_editors
        widget.is_dirty = False
        widget.save_plan = None
        if params:
            widget.params = params
        element = get_element_for_path(file_path)
        if element:
            widget.active_plugin = element.plugin
        widget._last_notified_content = content # 最後に通知したときの内容
        
        # 初回のエラー波線診断を実行
        if hasattr(widget, "run_diagnostics"):
            widget.run_diagnostics()
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
        else:
            widget.on_save_triggered = lambda w=widget: build_plain_text_save_plan(w, False)
            widget.on_save_as_triggered = lambda w=widget: build_plain_text_save_plan(w, True)
            widget.on_write_save_plan = lambda w=widget: write_plain_text_save_plan(w)

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
        
            editor = create_editor_widget(editor_id, virtual_path, content, available_editors, tab_id=next_tab_id())
        
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

    def open_file(file_path, editor_id=None, params=None):
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
                # 既に開いている場合は即座に適用
                if params and hasattr(widget, "set_params"):
                    widget.set_params(params)
                elif params:
                    widget.params = params
                update_editor_selector(i)
                return

        encoding = "utf-8"
        if element:
            encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)

        try:
            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                content = f.read()

            # 新しく開く場合は、まずウィジェットを生成
            editor = create_editor_widget(editor_id, file_path, content, available_editors, tab_id=next_tab_id())
            
            # パラメータがあれば「準備完了後」に適用されるように予約
            if params:
                window.pending_params[getattr(editor, "tab_id", None)] = params
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

    core.api._active_plugin_id_handler = lambda: getattr(project_tree.active_plugin, "id", None)


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
    plugin_by_id = {plugin.id: plugin for plugin in plugins}
    core.api._plugin_object_resolver = lambda plugin_id: plugin_by_id.get(plugin_id) if plugin_id else None

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
        if not plugin:
            return {}
        return plugin.export_project_data(context)

    def plugin_import_project_data(plugin, context, data):
        if not plugin:
            return
        plugin.import_project_data(context, data)

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

    action_save = window.findChild(object, "actionSave")
    if action_save:
        action_save.triggered.connect(lambda checked=False: save_active_tab(False))

    action_save_as = window.findChild(object, "actionSaveAs")
    if action_save_as:
        action_save_as.triggered.connect(lambda checked=False: save_active_tab(True))

    core.api._message_handler = lambda text, timeout: window.statusBar().showMessage(text, timeout)

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

    core.api._progress_handler = on_progress

    core.api._open_tab_handler = open_file
    core.api._open_untitled_tab_handler = open_untitled_tab
    core.api._active_tab_handler = get_active_tab_info
    core.api._tab_plugin_id_handler = get_tab_plugin_id

    # 4. エディタ準備完了通知のハンドリング
    def on_editor_ready(tab_id):
        if tab_id in window.pending_params:
            params = window.pending_params.pop(tab_id)
            widget = find_widget_by_tab_id(tab_id)
            if not widget:
                return
            if hasattr(widget, "set_params"):
                widget.set_params(params)
            else:
                widget.params = params

    core.api._editor_ready_handler = on_editor_ready


    # ウィンドウを表示
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
