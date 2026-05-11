import sys
import os
from PySide6.QtWidgets import QApplication, QMenu, QVBoxLayout, QToolButton, QWidget
from core.editor import EditorWidget
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt, QSize

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

    # --- エディタータブの設定 ---
    window.editorTabs = window.findChild(object, "editorTabs")
    if window.editorTabs:
        window.editorTabs.tabCloseRequested.connect(lambda index: window.editorTabs.removeTab(index))

    def open_file(file_path):
        if not window.editorTabs:
            return
            
        # 既に開いているか確認（ToolTipにフルパスを保存している前提）
        for i in range(window.editorTabs.count()):
            if window.editorTabs.tabToolTip(i) == file_path:
                window.editorTabs.setCurrentIndex(i)
                return
        
        # 新しく開く
        try:
            # とりあえずテキストファイルとして読み込み
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            editor = EditorWidget()
            # フォント設定などは EditorWidget 内で行われる
            editor.setPlainText(content)
            
            file_name = os.path.basename(file_path)
            index = window.editorTabs.addTab(editor, file_name)
            window.editorTabs.setTabToolTip(index, file_path)
            window.editorTabs.setCurrentIndex(index)
        except Exception as e:
            print(f"ファイルを開けませんでした: {e}")

    window.open_file = open_file
    # ---------------------------

    # --- ドックの管理と表示メニューの設定 ---
    view_menu = window.findChild(QMenu, "menuView")
    docks = []

    # 1. プロジェクトツリードック
    from core.project_tree_dock import ProjectTreeDock
    project_tree = ProjectTreeDock(window)
    project_tree_dock = project_tree.get_widget()
    if project_tree_dock:
        window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, project_tree_dock)
        docks.append(project_tree_dock)
    
    # メニューにアクションを登録
    if view_menu:
        for dock in docks:
            view_menu.addAction(dock.toggleViewAction())
            
    # --- アクティビティバーの動的更新設定 ---
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
    
    # ウィンドウを表示
    window.show()
    
    # イベントループの開始
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
