import os
import json
import numpy as np
from PySide6.QtCore import QLocale

class ColorizeModelBase:
    """AIカラー化モデルの抽象ベースクラス (すべての標準および外部モデルプラグインの共通親クラス)"""
    
    def __init__(self, metadata: dict = None):
        """JSONからロードされた定義情報を保持する"""
        self.metadata = metadata or {}
        
    def get_id(self) -> str:
        """モデルの一意な識別子 (英数字。例: 'eccv2016')"""
        return self.metadata.get("id", "")
        
    def get_name(self) -> str:
        """UIのコンボボックスに表示するモデルの表示名 (localisation/*.json から動的に辞書ロード・翻訳)"""
        # 1. 現在の言語コードを取得 (例: "ja-jp", "en-us")
        lang = QLocale.system().name().replace('_', '-').lower()
        
        # 2. 翻訳JSONファイルの配置パスを計算
        base_dir = os.path.dirname(os.path.dirname(__file__)) # .../colorize/
        local_json_path = os.path.join(base_dir, "localisation", f"{lang}.json")
        
        # 3. 言語ファイルが見つからない場合は英語 ("en-us") に自動フォールバック
        if not os.path.exists(local_json_path):
            local_json_path = os.path.join(base_dir, "localisation", "en-us.json")
            
        if os.path.exists(local_json_path):
            try:
                with open(local_json_path, "r", encoding="utf-8") as f:
                    translations = json.load(f)
                # 一意なキー "[モデルID].name" で辞書引き
                key = f"{self.get_id()}.name"
                return translations.get(key, self.get_id())
            except Exception as e:
                print(f"[AI Colorize Localisation] Error reading {local_json_path}: {e}")
                
        # 4. 万が一翻訳辞書ファイルが全滅している場合のフォールバックとしてIDを返す
        return self.metadata.get("name", self.get_id())

    def get_files_config(self) -> dict:
        """
        モデルに必要な学習済みファイル定義を返す。
        """
        return self.metadata.get("files", {})

    def get_file_entries(self) -> dict:
        """
        files 定義を検証して返す。
        必須形式: { "file_id": {"path": "file.bin", "url": "...", "mirrors": [...], "role": "..."} }
        """
        entries = {}
        for file_id, config in self.get_files_config().items():
            if not isinstance(config, dict):
                raise ValueError(f"Model file entry must be an object: {file_id}")

            path = config.get("path")
            url = config.get("url")
            if not path or not url:
                raise ValueError(f"Model file entry requires 'path' and 'url': {file_id}")

            mirrors = config.get("mirrors") or [url]
            entries[file_id] = {
                **config,
                "path": path,
                "url": url,
                "mirrors": mirrors,
                "role": config.get("role"),
            }
        return entries

    def get_asset_dir_name(self) -> str:
        """models/ 配下の保存ディレクトリ名を返す。"""
        asset_dir = self.metadata.get("asset_dir")
        if not asset_dir:
            raise ValueError(f"Model definition requires 'asset_dir': {self.get_id()}")
        return asset_dir

    def get_assets_root(self) -> str:
        """interface/ から見たモデル保存ルートを返す。"""
        assets_root = self.metadata.get("assets_root")
        if not assets_root:
            raise ValueError(f"Model definition requires 'assets_root': {self.get_id()}")
        return assets_root

    def get_models_dir(self, interface_dir: str) -> str:
        return os.path.normpath(os.path.join(interface_dir, self.get_assets_root()))

    def get_file_entry_by_role(self, role: str) -> dict:
        for entry in self.get_file_entries().values():
            if entry.get("role") == role:
                return entry
        raise KeyError(f"Model file role is not configured: {role}")

    def get_file_path_by_role(self, models_dir: str, role: str) -> str:
        entry = self.get_file_entry_by_role(role)
        return os.path.join(models_dir, self.get_asset_dir_name(), entry["path"])

    def load_network(self, models_dir: str):
        """
        モデルファイルをメモリ上にロード・初期化する
        models_dir: 'plugins/hoi4/interface/models/' の親パス
        """
        raise NotImplementedError

    def predict(self, bgr_img: np.ndarray) -> np.ndarray:
        """
        BGR画像 (numpy.ndarray / uint8) を受け取り、AIでカラー化したBGR画像 (uint8) を返す
        """
        raise NotImplementedError
