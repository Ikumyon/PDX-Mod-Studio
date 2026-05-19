import os
import cv2
import numpy as np
from .base_model import ColorizeModelBase

class ECCV2016Model(ColorizeModelBase):
    """標準内蔵モデル (ECCV 2016 / レトロな風合いのカラー化)"""
    
    def load_network(self, models_dir: str):
        # モデルごとの専用サブフォルダ
        model_sub_dir = os.path.join(models_dir, self.get_id())
        proto_path = os.path.join(model_sub_dir, "colorization_deploy_v2.prototxt")
        model_path = os.path.join(model_sub_dir, "colorization_release_v2.caffemodel")
        pts_path = os.path.join(model_sub_dir, "pts_in_hull.npy")
        
        # マルチバイト（日本語）パス対策として、バイナリバッファ経由でメモリから安全にロード
        with open(proto_path, "rb") as f:
            proto_buffer = bytearray(f.read())
        with open(model_path, "rb") as f:
            model_buffer = bytearray(f.read())
            
        self.net = cv2.dnn.readNetFromCaffe(proto_buffer, model_buffer)
        
        # NumPy配列もファイルオブジェクト経由で安全にロード
        with open(pts_path, "rb") as f:
            pts = np.load(f)
        pts = pts.transpose().reshape(2, 313, 1, 1)
        
        # レイヤの重みとスケールを設定
        class8_ab = self.net.getLayerId("class8_ab")
        conv8_313_rh = self.net.getLayerId("conv8_313_rh")
        self.net.getLayer(class8_ab).blobs = [pts.astype("float32")]
        self.net.getLayer(conv8_313_rh).blobs = [np.full([1, 313, 1, 1], 2.606, dtype="float32")]

    def predict(self, bgr_img: np.ndarray) -> np.ndarray:
        if not hasattr(self, "net") or self.net is None:
            raise RuntimeError("Model network is not loaded. Call load_network() first.")
            
        height, width = bgr_img.shape[:2]
        
        # BGRを浮動小数点の 0-1 にスケールし、Lab色空間に変換
        bgr_float = bgr_img.astype("float32") / 255.0
        lab = cv2.cvtColor(bgr_float, cv2.COLOR_BGR2Lab)
        
        # Lチャネルを抽出し、入力サイズ 224x224 にリサイズ
        l_channel = lab[:, :, 0]
        l_resized = cv2.resize(l_channel, (224, 224))
        
        # 平均減算処理 (50.0 減算)
        l_resized -= 50.0
        
        # Caffeの入力テンソル形状 (1, 1, 224, 224) に正確に変形
        blob = l_resized.reshape(1, 1, 224, 224).astype("float32")
        self.net.setInput(blob)
        
        # 推論 (a, b チャネルの予測)
        ab_predicted = self.net.forward()[0, :, :, :].transpose((1, 2, 0))
        
        # 出力された a, b チャネルを元の画像サイズにリサイズ
        ab_resized = cv2.resize(ab_predicted, (width, height))
        
        # 元の L チャネルと合成して Lab 画像を作成
        result_lab = np.zeros((height, width, 3), dtype="float32")
        result_lab[:, :, 0] = l_channel
        result_lab[:, :, 1:] = ab_resized
        
        # LabをBGRに変換し、0-255 の uint8 にスケールして返す
        result_bgr = cv2.cvtColor(result_lab, cv2.COLOR_Lab2BGR)
        return np.clip(result_bgr * 255.0, 0, 255).astype("uint8")
