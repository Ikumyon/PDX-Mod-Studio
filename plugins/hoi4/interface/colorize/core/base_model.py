import numpy as np

class ColorizeModelBase:
    """AIカラー化モデルの抽象ベースクラス (すべての標準および外部モデルプラグインの共通親クラス)"""
    
    def __init__(self, metadata: dict = None):
        """JSONからロードされた定義情報を保持する"""
        self.metadata = metadata or {}
        
    def get_id(self) -> str:
        """モデルの一意な識別子 (英数字。例: 'eccv2016')"""
        return self.metadata.get("id", "")
        
    def get_name(self) -> str:
        """UIのコンボボックスに表示するモデルの日本語名"""
        return self.metadata.get("name", "")

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
