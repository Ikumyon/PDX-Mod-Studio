import fnmatch
import json
import os
import sys
import tomllib

import core.api
from core import save_result as save_result_utils
from core.dialog import EncodingActionDialog, LanguageSelectDialog
from core.i18n import I18nManager
from core.editor_tabs import EditorTabProxy, create_editor_tab_bar
from core.editor_tab_controller import EditorTabController
from core.save_controller import SaveController
from core.diagnostics_controller import DiagnosticsController

from core.encoding_controller import (
    decode_with_encoding,
    read_text_with_detected_encoding,
    reopen_text_widget_with_encoding,
)
from core.project_io import ProjectIOManager
from core.search_controller import SearchController
from core.file_open_controller import FileOpenController
from core.inspector import (
    EncodingType as InspectorEncodingType,
    FileType as InspectorFileType,
    inspect_file,
)
from core.syntax_engine import SyntaxBundle
from PySide6.QtCore import QFile, QCoreApplication, QSize, Qt, Signal, QObject, QEvent, QTimer
from PySide6.QtGui import QAction
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QToolButton,
    QWidget,
)

tr = QCoreApplication.translate

def main():
    app = QApplication(sys.argv)
    
    # 翻訳の初期化
    I18nManager().init_translation(app)
    
    # レンダラーの翻訳を適用
    from core.dashboard_tab_host import renderer_registry
    renderer_registry.install_translations(app)
    
    # Windowsのタスクバーアイコンを正しく表示するための設定
    try:
        import ctypes
        myappid = "pdx.mod.studio.v1"  # 任意の識別子
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    # --- 外部プラグインから import 可能にするための登録 ---
    sys.modules["core.api"] = core.api
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

    tab_ui_file_path = os.path.join(base_dir, "ui", "widgets", "tab.ui")
    tab_ui_file = QFile(tab_ui_file_path)
    if not tab_ui_file.open(QFile.OpenModeFlag.ReadOnly):
        print(tr("Main", "UIファイルを開けませんでした: {path}").format(path=tab_ui_file_path))
        sys.exit(-1)

    tab_widget = loader.load(tab_ui_file, window)
    tab_ui_file.close()
    if not tab_widget:
        print(tr("Main", "UIのロードに失敗しました: {error}").format(error=loader.errorString()))
        sys.exit(-1)
    window.setCentralWidget(tab_widget)

    # --- アプリケーションアイコンの設定 ---
    window.current_project_file = None
    window.current_project_type = "reference"
    window.embedded_project_workspace = None
    window.editor_word_wrap_enabled = False

    from PySide6.QtGui import QIcon
    icon_path = os.path.join(base_dir, "assets", "app_icon.ico")
    if os.path.exists(icon_path):
        window.setWindowIcon(QIcon(icon_path))
        # タスクバー用のアイコン設定 (Windows)
        app.setWindowIcon(QIcon(icon_path))

    # --- エディタパラメータ管理 ---
    window.pending_params = {} # {tab_id: params}
    window._tab_id_counter = 0

    def next_tab_id():
        window._tab_id_counter += 1
        return f"tab:{window._tab_id_counter}"

    # --- ドックの初期化 ---
    from core.home_sidebar_dock import HomeSidebarDock
    from core.project_tree_dock import ProjectTreeDock
    from core.project_search_dock import ProjectSearchDock
    from core.plugin_manager import PluginManager
    from core.editor_registry import EditorRegistry
    from core.editor import EditorWidget
    home_sidebar = HomeSidebarDock(window)
    home_sidebar_dock = home_sidebar.get_widget()
    project_tree = ProjectTreeDock(window)
    project_tree_dock = project_tree.get_widget()
    project_search = ProjectSearchDock(window)
    project_search_dock = project_search.get_widget()
    
    window.project_tree = project_tree
    
    view_menu = window.findChild(QMenu, "menuView")
    docks = []
    if home_sidebar_dock:
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, home_sidebar_dock)
        docks.append(home_sidebar_dock)
    if project_tree_dock:
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, project_tree_dock)
        docks.append(project_tree_dock)
    if project_search_dock:
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, project_search_dock)
        docks.append(project_search_dock)

    if view_menu:
        for dock in docks:
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        action_show_hidden_files = QAction(tr("MainWindow", "隠しファイルも表示"), window)
        action_show_hidden_files.setCheckable(True)
        action_show_hidden_files.setChecked(project_tree.show_hidden_files)
        action_show_hidden_files.toggled.connect(project_tree.set_show_hidden_files)
        view_menu.addAction(action_show_hidden_files)

    # --- エディタータブの設定 (QTabBar + QStackedWidget への適応) ---
    tab_bar_container = window.findChild(object, "editorTabBarContainer")
    editor_stacked = window.findChild(object, "editorStackedWidget")
    editor_splitter = window.findChild(object, "editorSplitter")
    editor_pane = window.findChild(object, "editorPane")
    tab_corner_container = window.findChild(object, "tabCornerContainer")

    if not tab_bar_container or not editor_stacked or not editor_splitter or not editor_pane or not tab_corner_container:
        print("Error: required editor tab widgets not found in UI")
        sys.exit(-1)



    editor_tab_bar = create_editor_tab_bar(tab_bar_container)
    if tab_bar_container.layout():
        tab_bar_container.layout().addWidget(editor_tab_bar)


    initial_pane = {
        "id": "pane:0",
        "widget": editor_pane,
        "tab_bar": editor_tab_bar,
        "stack": editor_stacked,
        "corner": tab_corner_container,
    }
    window.editorTabs = EditorTabProxy(editor_splitter, initial_pane)

    split_editor_button = window.findChild(QToolButton, "splitEditorButton")
    if split_editor_button:
        split_editor_button.setVisible(False)
        split_editor_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        split_editor_button.setIconSize(QSize(20, 20))
        split_editor_button.setFixedSize(32, 28)
        split_editor_button.setToolTip(tr("MainWindow", "エディタを右に分割"))
        split_icon_path = os.path.join(base_dir, "assets", "icons", "split-editor-right.svg")
        if os.path.exists(split_icon_path):
            from core.utils import load_svg_icon
            icon_color = window.palette().color(window.foregroundRole()).name()
            split_editor_button.setIcon(load_svg_icon(split_icon_path, icon_color))

    def update_split_editor_button():
        if not split_editor_button:
            return
        split_editor_button.setVisible(bool(window.editorTabs and window.editorTabs.count() > 0))

    # コントローラーの初期化
    tab_controller = EditorTabController(
        window,
        project_tree,
        next_tab_id,
        update_split_editor_button
    )
    diagnostics_controller = DiagnosticsController(window, tab_controller)
    tab_controller.diagnostics_controller = diagnostics_controller
    save_controller = SaveController(window, tab_controller)
    window.save_controller = save_controller
    window.tab_controller = tab_controller
    window.diagnostics_controller = diagnostics_controller

    # シグナルの接続
    window.editorTabs.tabCloseRequested.connect(tab_controller.close_editor_tab)
    window.editorTabs.currentChanged.connect(tab_controller.on_tab_changed)

    def on_focus_changed(old_widget, new_widget):
        if window.editorTabs and new_widget:
            window.editorTabs.focusWidgetChanged(new_widget)

    app.focusChanged.connect(on_focus_changed)
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


    def move_widget_to_layout(widget, target_layout):
        if not widget or not target_layout:
            return
        parent = widget.parentWidget()
        if parent and parent.layout():
            parent.layout().removeWidget(widget)
        target_layout.addWidget(widget)

    def update_editor_corner_controls_pane():
        if not window.editorTabs:
            return
        target_layout = window.editorTabs.activeCornerLayout()
        move_widget_to_layout(split_editor_button, target_layout)
        move_widget_to_layout(view_selector, target_layout)

    def get_element_for_path(file_path):
        """ファイルパスが属するプラグイン内のエレメントを特定する"""
        # 手動指定されている場合はそれを優先して返す
        if window.editorTabs:
            for i in range(window.editorTabs.count()):
                widget = window.editorTabs.widget(i)
                if widget and getattr(widget, "file_path", "") == file_path:
                    forced = getattr(widget, "forced_element", None)
                    if forced == "plain_text":
                        return None
                    elif forced is not None:
                        return forced
                    break

        if not file_path or file_path.startswith("untitled:"):
            return None
            
        plugin = project_tree.active_plugin
        if not plugin or not hasattr(project_tree, "current_project_path"):
            return None
        
        try:
            rel_path = os.path.relpath(file_path, project_tree.current_project_path).replace("\\", "/")
            for element in plugin.elements:
                pattern = str(element.path or "").replace("\\", "/")
                if not pattern or not fnmatch.fnmatch(rel_path, pattern):
                    continue
                excludes = element.raw.get("exclude") or []
                if any(isinstance(exclude, str) and fnmatch.fnmatch(rel_path, exclude) for exclude in excludes):
                    continue
                    return element
        except Exception:
            pass
        return None

    def get_element_for_widget(widget):
        if not widget:
            return None
        forced = getattr(widget, "forced_element", None)
        if forced == "plain_text":
            return None
        if forced is not None:
            return forced

        file_path = getattr(widget, "file_path", "")
        element = get_element_for_path(file_path)
        if element is not None:
            widget.active_element = element
            return element
        return getattr(widget, "active_element", None)

    def get_available_editors_for_file(file_path, include_script=True):
        editors = [
            {"id": e.editor_id, "name": e.name}
            for e in (editor_registry.get_editors_for_element(get_element_for_path(file_path)) or [])
        ]
        if include_script:
            editors.append({"id": TEXT_EDITOR_ID, "name": editor_registry.get_editor(TEXT_EDITOR_ID).name})
        return editors

    window.get_available_editors_for_file = get_available_editors_for_file


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

    def resolve_default_encoding(file_path):
        element = get_element_for_path(file_path)
        if not element:
            return "utf-8"
        encoding = element.plugin.get_element_attribute(element, "encoding", file_path=file_path)
        if not encoding:
            raise ValueError(f"Encoding is not defined for file: {file_path}")
        return encoding

    def get_widget_encoding(widget):
        return getattr(widget, "file_encoding", None) or "utf-8"

    def get_status_encoding_for_widget(widget):
        if not widget:
            return "utf-8"
        return get_widget_encoding(widget)



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
        file_open_controller.open_file(file_path, editor_id)

    # 後からコールバックをバインドするプレースホルダー
    pass

    def get_widget_text_content(widget):
        if widget is None:
            return None
        to_plain_text = getattr(widget, "toPlainText", None)
        if callable(to_plain_text):
            return to_plain_text()
        return None

    def apply_word_wrap_to_widget(widget):
        if not widget:
            return
        editor_id = editor_registry.normalize_editor_id(getattr(widget, "editor_id", TEXT_EDITOR_ID))
        if not editor_registry.is_text_editor(editor_id):
            return
        line_wrap_mode = (
            QPlainTextEdit.LineWrapMode.WidgetWidth
            if window.editor_word_wrap_enabled
            else QPlainTextEdit.LineWrapMode.NoWrap
        )
        widget.setLineWrapMode(line_wrap_mode)

    def apply_word_wrap_to_open_editors():
        if not window.editorTabs:
            return
        for index in range(window.editorTabs.count()):
            apply_word_wrap_to_widget(window.editorTabs.widget(index))

    def set_editor_word_wrap(enabled):
        window.editor_word_wrap_enabled = bool(enabled)
        apply_word_wrap_to_open_editors()

    if view_menu:
        view_menu.addSeparator()
        action_word_wrap = QAction(tr("MainWindow", "折り返しする"), window)
        action_word_wrap.setCheckable(True)
        action_word_wrap.setChecked(window.editor_word_wrap_enabled)
        action_word_wrap.toggled.connect(set_editor_word_wrap)
        view_menu.addAction(action_word_wrap)

    def resolve_schema_for_file(element, file_path):
        if not element:
            return None
        is_virtual_path = not file_path or str(file_path).startswith("untitled:")

        if not is_virtual_path:
            project_path = getattr(project_tree, "current_project_path", None)
            if not project_path:
                return None

            try:
                rel_path = os.path.relpath(file_path, project_path).replace("\\", "/")
            except Exception:
                return None

            match_glob = element.raw.get("match_glob")
            if isinstance(match_glob, str) and match_glob and not fnmatch.fnmatch(rel_path, match_glob):
                return None

            excludes = element.raw.get("exclude") or []
            for exclude in excludes:
                if isinstance(exclude, str) and fnmatch.fnmatch(rel_path, exclude):
                    return None

        schema = element.raw.get("schema")
        if isinstance(schema, str) and schema:
            return schema

        schema_rules = element.raw.get("schema_rules") or []
        for rule in schema_rules:
            if not isinstance(rule, dict):
                continue
            schema_path = rule.get("schema")
            if isinstance(schema_path, str) and schema_path:
                return schema_path
        return None

    # 診断処理コントローラーへ委譲
    pass

    def create_editor_widget(editor_id, file_path, content, available_editors, params=None, tab_id=None, file_encoding=None):
        editor_id = editor_registry.normalize_editor_id(editor_id)
        if not file_encoding:
            file_encoding = resolve_default_encoding(file_path) if file_path and not str(file_path).startswith("untitled:") else "utf-8"
        if editor_id == TEXT_EDITOR_ID:
            widget = EditorWidget()
            widget.tab_id = tab_id
            widget.setPlainText(content)
            widget.textChanged.connect(lambda w=widget: tab_controller.mark_tab_dirty(w))
            widget.textChanged.connect(lambda w=widget: diagnostics_controller.schedule_language_diagnostics(w))
        else:
            widget = editor_registry.create_editor_widget(editor_id, window.editorTabs, file_path, content, tab_id=tab_id)
            if not widget:
                # 失敗した場合はテキストエディタ
                return create_editor_widget(TEXT_EDITOR_ID, file_path, content, available_editors, params, tab_id=tab_id)
        
        widget.editor_id = editor_id
        widget.file_path = file_path
        widget.file_encoding = file_encoding
        widget.content = content
        widget.available_editors = available_editors
        widget.is_dirty = False
        widget.diagnostic_count = 0
        widget.save_plan = None
        if params:
            widget.params = params
        widget.tab_base_text = os.path.basename(file_path) if file_path and not str(file_path).startswith("untitled:") else ""
        element = get_element_for_path(file_path)
        if element:
            widget.active_element = element
            widget.active_plugin = element.plugin
        widget._last_notified_content = content # 最後に通知したときの内容

        # エディタ用フォントの初期適用
        from core.dialog.settings import settings_manager
        from PySide6.QtGui import QFont
        editor_family = settings_manager.get("editor_font_family", "")
        editor_size = int(settings_manager.get("editor_font_size", 12))
        font_editor = QFont()
        if editor_family:
            font_editor.setFamily(editor_family)
        font_editor.setPointSize(editor_size)
        widget.setFont(font_editor)
        
        if editor_id != TEXT_EDITOR_ID:
            def check_content_change(w=widget):
                try:
                    current_content = getattr(w, "content", None)
                    if current_content is not None and current_content != w._last_notified_content:
                        w._last_notified_content = current_content
                        tab_controller.mark_tab_dirty(w)
                except (RuntimeError, ReferenceError):
                    if hasattr(w, "_dirty_timer"):
                        w._dirty_timer.stop()

            widget._dirty_timer = QTimer(widget)
            widget._dirty_timer.timeout.connect(check_content_change)
            widget._dirty_timer.start(100)
        apply_word_wrap_to_widget(widget)
        diagnostics_controller.schedule_language_diagnostics(widget)
        return widget

    if split_editor_button:
        split_editor_button.clicked.connect(lambda checked=False: tab_controller.split_active_editor_right())

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

    file_open_controller = FileOpenController(
        window=window,
        editor_tabs=window.editorTabs,
        editor_registry=editor_registry,
        project_tree=project_tree,
        create_editor_widget=create_editor_widget,
        get_element_for_path=get_element_for_path,
        update_editor_selector=update_editor_selector,
        next_tab_id=next_tab_id,
        text_editor_id=TEXT_EDITOR_ID,
    )
    def open_home_tab():
        if window.editorTabs:
            for i in range(window.editorTabs.count()):
                widget = window.editorTabs.widget(i)
                if getattr(widget, "file_path", "") == "home:":
                    window.editorTabs.setCurrentIndex(i)
                    return
        from core.home_tab import HomeTabWidget
        widget = HomeTabWidget(window)
        widget.file_path = "home:"
        widget.tab_id = next_tab_id()
        widget.tab_base_text = tr("MainWindow", "ホーム")
        
        from PySide6.QtGui import QIcon
        icon = QIcon()
        icons_dir = os.path.join(base_dir, "assets", "icons")
        icon_path = os.path.join(icons_dir, "home-48.svg")
        if os.path.exists(icon_path):
            from core.utils import load_svg_icon
            icon_color = window.palette().color(window.foregroundRole()).name()
            icon = load_svg_icon(icon_path, icon_color)
            
        index = window.editorTabs.addTab(widget, icon, tr("MainWindow", "ホーム"))
        window.editorTabs.setTabToolTip(index, "home:")
        window.editorTabs.setCurrentIndex(index)
        
        project_tree.update_open_editors(window.editorTabs)
        update_split_editor_button()

    def open_dashboard_tab():
        if window.editorTabs:
            for i in range(window.editorTabs.count()):
                widget = window.editorTabs.widget(i)
                if getattr(widget, "file_path", "") == "dashboard:":
                    window.editorTabs.setCurrentIndex(i)
                    if hasattr(widget, "refresh"):
                        widget.refresh()
                    return
        from core.dashboard_tab_host import DashboardTabHostWidget
        widget = DashboardTabHostWidget(window)
        widget.file_path = "dashboard:"
        widget.tab_id = next_tab_id()
        widget.tab_base_text = tr("MainWindow", "ダッシュボード")
        
        from PySide6.QtGui import QIcon
        icon = QIcon()
        icons_dir = os.path.join(base_dir, "assets", "icons")
        icon_path = os.path.join(icons_dir, "data-area-20.svg")
        if os.path.exists(icon_path):
            from core.utils import load_svg_icon
            icon_color = window.palette().color(window.foregroundRole()).name()
            icon = load_svg_icon(icon_path, icon_color)

        active_plugin = getattr(project_tree, "active_plugin", None)
        if active_plugin:
            class PluginDashboardProvider:
                def __init__(self, plugin):
                    self.plugin = plugin
                def createDashboard(self, context):
                    res = self.plugin.call_named_hook("dashboard.create", {"context": context})
                    if not res:
                        provider_obj = self.plugin.call_named_hook("dashboard.provider", {"context": context})
                        if provider_obj and hasattr(provider_obj, "createDashboard"):
                            res = provider_obj.createDashboard(context)
                        return res

            widget.setDashboardProvider(PluginDashboardProvider(active_plugin))

        project_path = getattr(project_tree, "current_project_path", None)
        if project_path:
            widget.loadDashboard({"project_path": project_path})
        else:
            widget.showEmpty()

        index = window.editorTabs.addTab(widget, icon, tr("MainWindow", "ダッシュボード"))
        window.editorTabs.setTabToolTip(index, "dashboard:")
        window.editorTabs.setCurrentIndex(index)
        
        project_tree.update_open_editors(window.editorTabs)
        update_split_editor_button()

    window.open_home_tab = open_home_tab
    window.open_dashboard_tab = open_dashboard_tab
    window.open_file = file_open_controller.open_file
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

    def handle_dock_visibility(changed_dock, visible):
        if not visible:
            return
        if window.dockWidgetArea(changed_dock) == Qt.DockWidgetArea.LeftDockWidgetArea:
            for d in docks:
                if d is not changed_dock and window.dockWidgetArea(d) == Qt.DockWidgetArea.LeftDockWidgetArea:
                    d.blockSignals(True)
                    d.setVisible(False)
                    d.blockSignals(False)

    for dock in docks:
        dock.dockLocationChanged.connect(lambda area, d=dock: update_activity_bar(d, area))
        dock.topLevelChanged.connect(lambda floating, d=dock: update_activity_bar(d, window.dockWidgetArea(d)))
        dock.visibilityChanged.connect(lambda visible, d=dock: handle_dock_visibility(d, visible))
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
        
        # プラグイン切り替え時は最新の文法定義ファイルを再読込できるようにキャッシュをクリア
        if hasattr(window, "_grammar_bundles"):
            window._grammar_bundles.pop(plugin.id, None)
        if hasattr(window, "_shown_definition_errors"):
            window._shown_definition_errors.clear()

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
                    w.active_element = elem
                    w.available_editors = editor_registry.get_editors_for_element(elem)
                else:
                    w.available_editors = []
            update_editor_selector(window.editorTabs.currentIndex())
            if "update_encoding_status" in locals():
                update_encoding_status()
            diagnostics_controller.schedule_all_language_diagnostics()


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

    project_io = ProjectIOManager(
        window=window,
        project_tree=project_tree,
        base_dir=base_dir,
        get_plugin_by_id=get_plugin_by_id,
        select_plugin=select_plugin,
        active_required_plugins=active_required_plugins,
        export_all_plugin_data=export_all_plugin_data,
        plugin_import_project_data=plugin_import_project_data,
    )



    action_open_project = window.findChild(object, "actionOpenProject")
    if action_open_project:
        action_open_project.triggered.connect(project_io.open_project_dialog)

    action_save_project = window.findChild(object, "actionSaveProject")
    if action_save_project:
        action_save_project.triggered.connect(project_io.save_project)

    action_save_project_as = window.findChild(object, "actionSaveProjectAs")
    if action_save_project_as:
        action_save_project_as.triggered.connect(project_io.save_project_as)

    action_save = window.findChild(object, "actionSave")
    if action_save:
        action_save.triggered.connect(lambda checked=False: save_controller.save_active_tab(False))

    action_save_as = window.findChild(object, "actionSaveAs")
    if action_save_as:
        action_save_as.triggered.connect(lambda checked=False: save_controller.save_active_tab(True))

    action_new_file = window.findChild(object, "actionNewFile")
    if action_new_file:
        action_new_file.triggered.connect(lambda checked=False: open_untitled_tab(tr("MainWindow", "無題")))

    action_open_file = window.findChild(object, "actionOpenFile")
    if action_open_file:
        action_open_file.triggered.connect(lambda checked=False: file_open_controller.open_file_dialog())

    def open_settings_dialog():
        from core.dialog.settings import SettingsDialog
        dialog = SettingsDialog(window)
        dialog.exec()

    action_settings = window.findChild(object, "actionSettings")
    if action_settings:
        action_settings.triggered.connect(open_settings_dialog)

    def open_plugin_manager_dialog():
        from core.dialog.plugin_manager_dialog import PluginManagerDialog
        dialog = PluginManagerDialog(window, plugin_manager)
        if dialog.exec() == PluginManagerDialog.DialogCode.Accepted:
            if dialog.has_changes:
                QMessageBox.information(
                    window,
                    tr("再起動の確認", "MainWindow"),
                    tr("プラグインの設定が変更されました。変更を適用するには、アプリケーションを再起動してください。", "MainWindow")
                )

    action_plugin_manager = window.findChild(object, "actionPluginManager")
    if action_plugin_manager:
        action_plugin_manager.triggered.connect(open_plugin_manager_dialog)

    core.api._message_handler = lambda text, timeout: window.statusBar().showMessage(text, timeout)

    encoding_display_names = {
        "ascii": "ASCII",
        "utf-8": "UTF-8",
        "utf-8-sig": "UTF-8 BOM",
        "cp932": "CP932",
        "shift_jis": "Shift_JIS",
        "utf-16-le": "UTF-16 LE",
        "utf-16-be": "UTF-16 BE",
    }
    selectable_encodings = [
        "utf-8",
        "utf-8-sig",
        "cp932",
        "shift_jis",
        "utf-16-le",
        "utf-16-be",
    ]

    def format_encoding_label(encoding):
        if not encoding:
            return "UTF-8"
        return encoding_display_names.get(encoding.lower(), encoding)

    def reopen_with_encoding(encoding):
        widget = window.editorTabs.currentWidget() if window.editorTabs else None
        if not widget:
            return
        if not editor_registry.is_text_editor(getattr(widget, "editor_id", TEXT_EDITOR_ID)):
            return
        if getattr(widget, "is_dirty", False) and not str(getattr(widget, "file_path", "")).startswith("untitled:"):
            answer = QMessageBox.question(
                window,
                tr("MainWindow", "文字コードの再解釈"),
                tr("MainWindow", "未保存の変更があります。破棄してこの文字コードで再読込しますか？"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            reopen_text_widget_with_encoding(widget, encoding)
            tab_controller.mark_tab_clean(widget)
        except Exception as error:
            QMessageBox.warning(
                window,
                tr("MainWindow", "文字コードの再解釈"),
                tr("MainWindow", "この文字コードでは開き直せませんでした: {error}").format(error=error),
            )
            return
        update_encoding_status()

    def save_with_encoding(encoding):
        widget = window.editorTabs.currentWidget() if window.editorTabs else None
        if not widget:
            return
        if not editor_registry.is_text_editor(getattr(widget, "editor_id", TEXT_EDITOR_ID)):
            return
        widget.file_encoding = encoding
        update_encoding_status()
        save_controller.save_active_tab(False)

    def open_encoding_dialog():
        widget = window.editorTabs.currentWidget() if window.editorTabs else None
        if not widget:
            return
        if not editor_registry.is_text_editor(getattr(widget, "editor_id", TEXT_EDITOR_ID)):
            return

        dialog = EncodingActionDialog(window, get_widget_encoding(widget), selectable_encodings, format_encoding_label)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        if dialog.selected_action == "reopen" and dialog.selected_encoding:
            reopen_with_encoding(dialog.selected_encoding)
            return
        if dialog.selected_action == "save" and dialog.selected_encoding:
            save_with_encoding(dialog.selected_encoding)

    def open_language_dialog():
        widget = window.editorTabs.currentWidget() if window.editorTabs else None
        if not widget:
            return
        if not editor_registry.is_text_editor(getattr(widget, "editor_id", TEXT_EDITOR_ID)):
            return

        forced = getattr(widget, "forced_element", None)
        current_mode = forced if forced is not None else "auto"

        plugin = project_tree.active_plugin
        available_elements = plugin.elements if plugin and hasattr(plugin, "elements") else []

        dialog = LanguageSelectDialog(window, current_mode, available_elements)
        if dialog.exec() == dialog.DialogCode.Accepted:
            selected = dialog.selected_mode
            if selected == "auto":
                widget.forced_element = None
                widget.active_element = get_element_for_path(getattr(widget, "file_path", ""))
            elif selected == "plain_text":
                widget.forced_element = "plain_text"
                widget.active_element = None
            else:
                widget.forced_element = selected
                widget.active_element = selected

            update_language_status()
            diagnostics_controller.schedule_language_diagnostics(widget)

    def update_language_status():
        widget = window.editorTabs.currentWidget() if window.editorTabs else None
        if not widget:
            language_button.setText("プレーンテキスト")
            language_button.setEnabled(False)
            return

        is_text = editor_registry.is_text_editor(getattr(widget, "editor_id", TEXT_EDITOR_ID))
        language_button.setEnabled(is_text)

        if not is_text:
            language_button.setText("プレーンテキスト")
            return

        forced = getattr(widget, "forced_element", None)
        if forced == "plain_text":
            language_button.setText("プレーンテキスト")
            diagnostics_controller.clear_language_diagnostics(widget)
        elif forced is not None:
            name = getattr(forced, "name", getattr(forced, "id", "不明なモード"))
            language_button.setText(f"{name} (手動)")
        else:
            element = get_element_for_widget(widget)
            if element:
                name = getattr(element, "name", getattr(element, "id", "不明なモード"))
                language_button.setText(name)
            else:
                language_button.setText("プレーンテキスト")

    def update_encoding_status():
        widget = window.editorTabs.currentWidget() if window.editorTabs else None
        if not widget:
            encoding_button.setText("UTF-8")
            encoding_button.setEnabled(False)
            update_language_status()
            return

        current_encoding = get_status_encoding_for_widget(widget)
        encoding_button.setText(format_encoding_label(current_encoding))

        if editor_registry.is_text_editor(getattr(widget, "editor_id", TEXT_EDITOR_ID)):
            encoding_button.setEnabled(True)
        else:
            encoding_button.setEnabled(False)
        update_language_status()

    # 2. 進捗 (ステータスバーにプログレスバーを追加)
    from PySide6.QtWidgets import QProgressBar
    language_button = QToolButton()
    language_button.setText("プレーンテキスト")
    language_button.setEnabled(False)
    language_button.clicked.connect(open_language_dialog)
    window.statusBar().addPermanentWidget(language_button)

    encoding_button = QToolButton()
    encoding_button.setText("UTF-8")
    encoding_button.setEnabled(False)
    encoding_button.clicked.connect(open_encoding_dialog)
    window.statusBar().addPermanentWidget(encoding_button)

    progress_bar = QProgressBar()
    progress_bar.setMaximumWidth(200)
    progress_bar.setTextVisible(True)
    progress_bar.setVisible(False)
    window.statusBar().addPermanentWidget(progress_bar)
    
    def on_progress(value, text):
        if value < 0 or value >= 100:
            progress_bar.setVisible(False)
            if text:
                window.statusBar().showMessage(text, 3000)
        else:
            progress_bar.setVisible(True)
            progress_bar.setValue(value)
            if text:
                progress_bar.setFormat(f"{text}: %p%")
            else:
                progress_bar.setFormat("%p%")

    core.api._progress_handler = on_progress

    # コールバックの紐付け
    tab_controller.update_editor_corner_controls_pane = update_editor_corner_controls_pane
    tab_controller.update_editor_selector = update_editor_selector
    tab_controller.update_encoding_status = update_encoding_status
    tab_controller.get_widget_text_content = get_widget_text_content
    tab_controller.get_widget_encoding = get_widget_encoding
    tab_controller.create_editor_widget = create_editor_widget

    core.api._open_tab_handler = file_open_controller.open_file
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
    update_encoding_status()

    # --- 検索・置換ポップアップの初期化とエディタ連携 ---
    search_controller = SearchController(window, window.editorTabs)

    # ウィンドウの移動・リサイズ・ドラッグ＆ドロップ時に適切な処理を行うためのイベントフィルター
    class WindowEventFilter(QObject):
        def eventFilter(self, watched, event):
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
                search_controller.update_search_popup_position()
            elif event.type() == QEvent.Type.DragEnter:
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                else:
                    event.ignore()
                return True
            elif event.type() == QEvent.Type.Drop:
                for url in event.mimeData().urls():
                    file_path = url.toLocalFile()
                    if not file_path:
                        continue
                    if os.path.isfile(file_path):
                        # ファイルの場合のみそのままエディタで開く（プロジェクト外でも同様に開く）
                        file_open_controller.open_file(file_path)
                event.acceptProposedAction()
                return True
            return False
            
    filter_obj = WindowEventFilter(window)
    window.installEventFilter(filter_obj)



    # 起動時のフォント設定適用
    from core.dialog.settings import settings_manager
    settings_manager.apply_fonts(window)

    # ドラッグ＆ドロップによるファイルオープンの有効化
    window.setAcceptDrops(True)

    # 起動時にHomeタブを開く
    open_home_tab()

    # ウィンドウを表示
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
