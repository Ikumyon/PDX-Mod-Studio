import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt

def main():
    app = QApplication(sys.argv)
    
    # UIファイルのパスを取得
    ui_file_path = os.path.join(os.path.dirname(__file__), "ui", "main_window.ui")
    ui_file = QFile(ui_file_path)
    
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        print(f"UIファイルを開けませんでした: {ui_file_path}")
        print(f"エラー: {ui_file.errorString()}")
        sys.exit(-1)
        
    # UIのロード
    loader = QUiLoader()
    window = loader.load(ui_file)
    ui_file.close()
    
    if not window:
        print(f"UIのロードに失敗しました: {loader.errorString()}")
        sys.exit(-1)
        
    # ウィンドウを表示
    window.show()
    
    # イベントループの開始
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
