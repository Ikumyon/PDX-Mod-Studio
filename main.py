import sys
import os
from PySide6.QtWidgets import QApplication, QMenu
from core.editor import EditorWidget
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt

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
    # ---------------------------------------
    
    # ウィンドウを表示
    window.show()
    
    # イベントループの開始
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
