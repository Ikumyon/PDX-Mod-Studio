import sys
import os
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QToolButton, QWidget
from core.editor import EditorWidget
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize
from core.profile_manager import ProfileManager
from core.mode_manager import ModeManager

def main():
    app = QApplication(sys.argv)
    
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

    # --- ドックの初期化 ---
    from core.project_tree_dock import ProjectTreeDock
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
        """ファイルパスが属するプロファイル内のエレメントを特定する"""
        profile = project_tree.active_profile
        if not profile or not hasattr(project_tree, "current_project_path"):
            return None
        
        try:
            rel_path = os.path.relpath(file_path, project_tree.current_project_path)
            norm_rel_dir = os.path.normpath(os.path.dirname(rel_path))
            
            for element in profile.elements:
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
            
        # モードの差し替え
        file_path = window.editorTabs.tabToolTip(current_tab_idx)
        # 現在のコンテンツを保持（変更されている可能性があるため）
        # ただし widget が EditorWidget かどうかで取得方法が異なる
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
        return widget

    def open_file(file_path):
        if not window.editorTabs:
            return
            
        # 既に開いているか確認
        for i in range(window.editorTabs.count()):
            if window.editorTabs.tabToolTip(i) == file_path:
                window.editorTabs.setCurrentIndex(i)
                return
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            # エレメントと利用可能なモードの特定
            element = get_element_for_path(file_path)
            available_modes = []
            if element:
                profile = project_tree.active_profile
                available_modes = mode_manager.get_modes_for_element(profile.path, element.path)
            
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
    # ---------------------------

    # ---------------------------------------
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

    # アイコンサイズの設定
    if activity_bar:
        activity_bar.setIconSize(QSize(28, 28))
        activity_bar.setMovable(False)

    # 初期状態の反映と監視設定
    for dock in docks:
        # ドックの場所が変わった時（別のエリアに移動した時など）
        dock.dockLocationChanged.connect(lambda area, d=dock: update_activity_bar(d, area))
        # フローティング状態が変わった時（切り離された時など）
        dock.topLevelChanged.connect(lambda floating, d=dock: update_activity_bar(d, window.dockWidgetArea(d)))
        
        # 初期エリアを取得して反映
        current_area = window.dockWidgetArea(dock)
        update_activity_bar(dock, current_area)
    # ---------------------------------------

    # --- プロファイルの読み込みとメニュー設定 ---
    from PySide6.QtWidgets import QComboBox, QLabel, QHBoxLayout, QFrame
    
    profiles_dir = os.path.join(base_dir, "profiles")
    profile_manager = ProfileManager(profiles_dir)
    profiles = profile_manager.load_profiles()

    def on_profile_selected(profile):
        if not profile:
            return
        print(f"プロファイルが選択されました: {profile.name} (Version: {profile.version})")
        window.statusBar().showMessage(f"プロファイル '{profile.name}' が選択されました。")
        # ProjectTreeDock にプロファイルを通知
        project_tree.set_active_profile(profile)

    # メニューバーにコンボボックスを配置
    menubar = window.menuBar()
    if menubar:
        profile_container = QWidget()
        profile_layout = QHBoxLayout(profile_container)
        profile_layout.setContentsMargins(10, 0, 10, 0)
        profile_layout.setSpacing(5)
        
        label = QLabel("プロファイル:")
        label.setStyleSheet("font-weight: bold; color: #888;")
        profile_layout.addWidget(label)
        
        from PySide6.QtGui import QIcon, QPixmap
        
        profile_combo = QComboBox()
        profile_combo.setMinimumWidth(200)
        profile_combo.setIconSize(QSize(20, 20))
        
        # プロファイルをコンボボックスに追加
        for profile in profiles:
            if profile.icon_path and os.path.exists(profile.icon_path):
                # 全ての状態でオリジナルの画像を使用するように設定して、色味の変化を防ぐ
                icon = QIcon()
                pixmap = QPixmap(profile.icon_path)
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.On)
                icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Active, QIcon.State.On)
                icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.Off)
                icon.addPixmap(pixmap, QIcon.Mode.Selected, QIcon.State.On)
                profile_combo.addItem(icon, profile.name, profile)
            else:
                profile_combo.addItem(profile.name, profile)
            
        profile_layout.addWidget(profile_combo)
        
        # コーナーウィジェットとしてセット
        menubar.setCornerWidget(profile_container, Qt.Corner.TopRightCorner)
        
        # シグナル接続
        profile_combo.currentIndexChanged.connect(
            lambda index: on_profile_selected(profile_combo.itemData(index))
        )
        
        # 初期状態の設定（最初のプロファイルを選択）
        if profiles:
            profile_combo.setCurrentIndex(0)
            on_profile_selected(profiles[0])
    # -----------------------------------------
    
    # ウィンドウを表示
    window.show()
    
    # イベントループの開始
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
