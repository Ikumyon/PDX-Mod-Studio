import os
import types
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile

class ModeDefinition:
    def __init__(self, mode_id, name, py_path, ui_path):
        self.mode_id = mode_id
        self.name = name
        self.py_path = py_path
        self.ui_path = ui_path

class ModeManager:
    def __init__(self):
        self.modes = {} # {mode_id: ModeDefinition}
        self.script_mode_id = "script_mode"

    def scan_directory(self, directory):
        """ディレクトリ内の .py と .ui のペアを探してモードとして登録する"""
        if not os.path.exists(directory):
            return

        for filename in os.listdir(directory):
            if filename.endswith(".py"):
                base_name = filename[:-3]
                ui_filename = base_name + ".ui"
                ui_path = os.path.join(directory, ui_filename)
                
                if os.path.exists(ui_path):
                    py_path = os.path.join(directory, filename)
                    mode_id = f"{directory}_{base_name}" # 一意なID
                    
                    # MODE_NAME を取得
                    mode_name = self._extract_mode_name(py_path) or base_name
                    
                    self.modes[mode_id] = ModeDefinition(
                        mode_id=mode_id,
                        name=mode_name,
                        py_path=py_path,
                        ui_path=ui_path
                    )

    def _extract_mode_name(self, py_path):
        """ .py ファイルから MODE_NAME 定数を抽出する """
        try:
            with open(py_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            import sys
            # 1. ファイル自身のディレクトリをパスに追加 (import event_parser 等)
            py_dir = os.path.dirname(py_path)
            if py_dir not in sys.path:
                sys.path.insert(0, py_dir)
            
            # 2. プロファイルのルートディレクトリをパスに追加 (import pdx_parser 等)
            profile_root = os.path.dirname(py_dir)
            if profile_root not in sys.path:
                sys.path.insert(0, profile_root)

            # 安全のため exec ではなく辞書内での実行、または簡易パースを検討
            namespace = {
                '__file__': py_path
            }
            exec(content, namespace)
            return namespace.get("MODE_NAME")
        except Exception as e:
            print(f"Failed to extract MODE_NAME from {py_path}: {e}")
            return None

    def get_modes_for_element(self, profile_path, element_path):
        """特定のエレメントに関連するモードを取得する"""
        full_element_dir = os.path.join(profile_path, element_path)
        # まだスキャンされていない場合はスキャン
        self.scan_directory(full_element_dir)
        
        relevant_modes = []
        prefix = f"{full_element_dir}_"
        for mode_id, mode in self.modes.items():
            if mode_id.startswith(prefix):
                relevant_modes.append(mode)
        
        return relevant_modes

    def create_mode_widget(self, mode_id, parent, file_path, content):
        """指定されたモードのウィジェットを生成し、ロジックを結合する"""
        if mode_id not in self.modes:
            return None

        mode = self.modes[mode_id]
        
        # 1. UIのロード
        loader = QUiLoader()
        ui_file = QFile(mode.ui_path)
        if not ui_file.open(QFile.ReadOnly):
            return None
        
        widget = loader.load(ui_file, parent)
        ui_file.close()
        
        if not widget:
            return None

        # 2. ロジックの結合 (.py の実行)
        try:
            import sys
            # 1. ファイル自身のディレクトリをパスに追加
            py_dir = os.path.dirname(mode.py_path)
            if py_dir not in sys.path:
                sys.path.insert(0, py_dir)

            # 2. プロファイルのルートディレクトリをパスに追加
            profile_root = os.path.dirname(py_dir)
            if profile_root not in sys.path:
                sys.path.insert(0, profile_root)

            with open(mode.py_path, 'r', encoding='utf-8') as f:
                py_code = f.read()
            
            # ウィジェットにメタデータを付与
            widget.file_path = file_path
            widget.mode_id = mode_id
            widget.content = content # 初期コンテンツを保持
            
            # 名前空間の用意。widget 自体を self として扱えるように工夫するか、
            # あるいは特定の関数を呼び出す形にする。
            # ここでは exec で widget に属性やメソッドを追加できるようにする。
            namespace = {
                'widget': widget,
                'parent': parent,
                'file_path': file_path,
                'content': content,
                '__file__': mode.py_path
            }
            exec(py_code, namespace)
            
            # もしセットアップ関数などが定義されていれば呼ぶ、といった拡張も可能
            if "setup" in namespace and callable(namespace["setup"]):
                namespace["setup"](widget, file_path, content)
                
        except Exception as e:
            print(f"Error binding logic for mode {mode_id}: {e}")
            
        return widget
