import os
import json
import glob
import sys
import importlib

class ColorizePluginLoader:
    """外部の動的カラー化プラグイン（アドオン）の自動スキャンとロードを司る専用ローダー"""
    
    def __init__(self, base_dir: str):
        """
        base_dir: 'plugins/hoi4/interface/' などの親ディレクトリパス
        """
        self.base_dir = base_dir
        self.definitions_dir = os.path.join(base_dir, "colorize", "definitions")
        
    def load_plugin_models(self, reserved_ids: list = None) -> list:
        """
        definitions/ フォルダから、標準モデル以外の外部プラグインを自動スキャン・ロードして返す
        reserved_ids: コア標準モデル等のIDのリスト（重複スキャンのスキップガード用）
        """
        reserved_ids = reserved_ids or []
        plugin_models = []
        
        # 動的ロードを可能にするため、sys.path 調整を実行
        parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(self.base_dir)))
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        if self.base_dir not in sys.path:
            sys.path.insert(0, self.base_dir)
            
        # JSON定義ファイルを走査
        json_pattern = os.path.join(self.definitions_dir, "*.json")
        json_files = glob.glob(json_pattern)
        
        print(f"[AI Colorize] Scanning external plugin directory: {self.definitions_dir}")
        for json_path in json_files:
            # 標準モデルのJSONはスキャナー対象から完全にスキップ (静的ロードされているため)
            if os.path.basename(json_path) == "eccv2016.json":
                continue
                
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    
                model_id = metadata.get("id")
                class_name = metadata.get("class_name")
                module_path = metadata.get("module_path")
                
                if not all([model_id, class_name, module_path]):
                    print(f"[AI Colorize] Invalid JSON metadata in {os.path.basename(json_path)}")
                    continue
                    
                # コア標準モデル等の ID 重複検知時はスキップ保護
                if model_id in reserved_ids:
                    print(f"[AI Colorize] External plugin ID '{model_id}' skipped: reserved by core.")
                    continue
                    
                # 外部モジュールを動的ロード
                print(f"[AI Colorize] Loading external plugin model: {model_id} ({module_path})")
                module = importlib.import_module(module_path)
                model_class = getattr(module, class_name)
                
                # インスタンス化して追加
                plugin_models.append(model_class(metadata))
                
            except Exception as e:
                print(f"[AI Colorize Error] Failed to load external plugin config {os.path.basename(json_path)}: {e}")
                
        return plugin_models
