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
        モデルに必要な学習済みファイル名とダウンロードURLのマップを返す
        例: { "filename.caffemodel": "https://...", ... }
        """
        return self.metadata.get("files", {})

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
