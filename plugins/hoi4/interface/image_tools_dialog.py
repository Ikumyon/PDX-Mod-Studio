import os
from PySide6.QtCore import QFile, Qt, QRectF, QTimer, QCoreApplication
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QBrush, QPainter, qRed, qGreen, qBlue, qAlpha, qRgb, qRgba
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsItem, QToolButton, QStackedWidget, QComboBox, QSpinBox, QSlider,
    QMessageBox, QColorDialog
)
from PySide6.QtUiTools import QUiLoader

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

tr = QCoreApplication.translate

class ImageToolsDialog(QDialog):
    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.saved_png_path = None
        self.original_image = None
        self.processed_image = None
        self.remove_bg_key_color = None  # クロマキー透過の基準色（Noneなら左上から自動検出）
        
        self.setWindowTitle("🎨 画像アセット調整・加工ツール")
        
        # UIファイルのロード
        loader = QUiLoader()
        base_dir = os.path.dirname(__file__)
        ui_path = os.path.join(base_dir, "image_tools_dialog.ui")
        
        file = QFile(ui_path)
        if not file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Failed to open UI file: {ui_path}")

        self.ui = loader.load(file)
        file.close()

        if not self.ui:
            raise RuntimeError(f"Failed to load UI file: {ui_path}")

        # The .ui root is a QDialog. Reparent it as an embedded widget so the
        # controls are painted inside this controller dialog on all platforms.
        self.setWindowTitle(self.ui.windowTitle() or self.windowTitle())
        self.resize(self.ui.size())
        self.ui.setParent(self)
        self.ui.setWindowFlags(Qt.WindowType.Widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui)
        self.ui.show()
        
        # シーンとビューのセットアップ
        self.scene = QGraphicsScene(self)
        
        # シーン全体の背景はすっきりとしたダークグレーにし、画像の境界をはっきりさせる
        self.scene.setBackgroundBrush(QBrush(QColor(50, 50, 50)))
        
        self.ui.graphicsViewPreview.setScene(self.scene)
        
        # 透過画像背後用のチェッカーボード（市松模様）パターンアイテムを作成
        tile_size = 8
        checker_pixmap = QPixmap(tile_size * 2, tile_size * 2)
        checker_pixmap.fill(Qt.GlobalColor.white)
        painter = QPainter(checker_pixmap)
        gray_color = QColor(180, 180, 180)
        painter.fillRect(0, 0, tile_size, tile_size, gray_color)
        painter.fillRect(tile_size, tile_size, tile_size, tile_size, gray_color)
        painter.end()
        
        self.background_checker_item = QGraphicsRectItem()
        self.background_checker_item.setPen(QPen(Qt.PenStyle.NoPen))
        self.background_checker_item.setBrush(QBrush(checker_pixmap))
        self.background_checker_item.setZValue(-1) # 画像の背後に配置
        self.background_checker_item.setVisible(False)
        self.scene.addItem(self.background_checker_item)
        
        self.pixmap_item = QGraphicsPixmapItem()
        self.pixmap_item.setZValue(0) # 手前に配置
        self.scene.addItem(self.pixmap_item)
        
        # トリミング枠のセットアップ
        self.crop_rect_item = QGraphicsRectItem()
        self.crop_rect_item.setPen(QPen(QColor("#efc84a"), 2, Qt.PenStyle.DashLine))
        self.crop_rect_item.setBrush(QBrush(QColor(0, 0, 0, 80)))
        self.crop_rect_item.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable | 
            QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.scene.addItem(self.crop_rect_item)
        
        # 編集モード ("crop" または "effect")
        self.mode = "crop"
        
        # デバウンス用のタイマー（プレビュー処理の負荷軽減）
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(50) # 50ms 遅延
        self.preview_timer.timeout.connect(self.update_preview_real)
        
        # 画像の読み込み
        if os.path.exists(self.image_path):
            self.original_image = self.load_image(self.image_path)
            if self.original_image.isNull():
                print(f"Failed to load image: {self.image_path}")

        self.bind_controls()
        self.init_ui_states()
        self.update_preview()

    def load_image(self, path: str) -> QImage:
        # Pillow (PIL) をメインの画像ローダーとし、DDS/TGA/PNG等の読み込み挙動を完全に統一する
        if HAS_PIL:
            try:
                pil_img = Image.open(path)
                pil_img = pil_img.convert("RGBA")
                data = pil_img.tobytes("raw", "RGBA")
                # QImage を作成し、内部バッファにデータをコピーして安全に取得
                qimg = QImage(data, pil_img.size[0], pil_img.size[1], QImage.Format.Format_RGBA8888)
                return qimg.copy()
            except Exception as e:
                print(f"Pillow failed to load image ({path}): {e}. Retrying with native QImage...")
                
        # Pillow が未インストール、または読み込みエラー時の最終フォールバック
        return QImage(path)

    def bind_controls(self):
        # ツールボタンのバインド
        self.ui.toolButtonCrop.clicked.connect(lambda: self.switch_mode("crop", 0))
        self.ui.toolButtonBlur.clicked.connect(lambda: self.switch_mode("effect", 1))
        self.ui.toolButtonSharpen.clicked.connect(lambda: self.switch_mode("effect", 2))
        self.ui.toolButtonRemoveBg.clicked.connect(lambda: self.switch_mode("effect", 3))
        self.ui.toolButtonColorize.clicked.connect(lambda: self.switch_mode("effect", 4))
        
        # トリミングコントロールのバインド
        self.ui.comboCropPreset.currentIndexChanged.connect(self.on_crop_preset_changed)
        self.ui.spinCropWidth.valueChanged.connect(self.on_crop_spin_changed)
        self.ui.spinCropHeight.valueChanged.connect(self.on_crop_spin_changed)
        
        # ぼかしコントロールのバインド
        self.ui.sliderBlurRadius.valueChanged.connect(self.ui.spinBlurRadius.setValue)
        self.ui.spinBlurRadius.valueChanged.connect(self.ui.sliderBlurRadius.setValue)
        self.ui.sliderBlurRadius.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderBlurThreshold.valueChanged.connect(self.ui.spinBlurThreshold.setValue)
        self.ui.spinBlurThreshold.valueChanged.connect(self.ui.sliderBlurThreshold.setValue)
        self.ui.sliderBlurThreshold.valueChanged.connect(self.trigger_preview_update)
        
        # シャープネスコントロールのバインド
        self.ui.sliderSharpenStrength.valueChanged.connect(self.ui.spinSharpenStrength.setValue)
        self.ui.spinSharpenStrength.valueChanged.connect(self.ui.sliderSharpenStrength.setValue)
        self.ui.sliderSharpenStrength.valueChanged.connect(self.trigger_preview_update)

        # 背景削除コントロールのバインド
        self.ui.sliderRemoveBgTolerance.valueChanged.connect(self.ui.spinRemoveBgTolerance.setValue)
        self.ui.spinRemoveBgTolerance.valueChanged.connect(self.ui.sliderRemoveBgTolerance.setValue)
        self.ui.sliderRemoveBgTolerance.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderRemoveBgFeather.valueChanged.connect(self.ui.spinRemoveBgFeather.setValue)
        self.ui.spinRemoveBgFeather.valueChanged.connect(self.ui.sliderRemoveBgFeather.setValue)
        self.ui.sliderRemoveBgFeather.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.btnSelectKeyColor.clicked.connect(self.select_key_color)

        # OK / Cancel の接続
        self.ui.buttonBox.accepted.connect(self.on_accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    def init_ui_states(self):
        # 初期状態の設定
        self.ui.stackedWidgetSettings.setCurrentIndex(0)
        self.ui.comboCropPreset.setCurrentIndex(0)
        
        # ぼかし初期値
        self.ui.sliderBlurRadius.setValue(1)
        self.ui.spinBlurRadius.setValue(1)
        self.ui.sliderBlurThreshold.setValue(30)
        self.ui.spinBlurThreshold.setValue(30)
        
        # シャープネス初期値
        self.ui.sliderSharpenStrength.setValue(0)
        self.ui.spinSharpenStrength.setValue(0)
        
        self.ui.sliderRemoveBgTolerance.setValue(30)
        self.ui.spinRemoveBgTolerance.setValue(30)
        self.ui.sliderRemoveBgFeather.setValue(5)
        self.ui.spinRemoveBgFeather.setValue(5)
        self.update_key_color_preview()
        
        # トリミング枠の初期位置
        if self.original_image and not self.original_image.isNull():
            w = min(60, self.original_image.width())
            h = min(60, self.original_image.height())
            self.ui.spinCropWidth.setValue(w)
            self.ui.spinCropHeight.setValue(h)
            
            # 中央に配置
            x = (self.original_image.width() - w) / 2
            y = (self.original_image.height() - h) / 2
            self.crop_rect_item.setPos(x, y)

    def switch_mode(self, mode: str, index: int):
        self.mode = mode
        self.ui.stackedWidgetSettings.setCurrentIndex(index)
        self.update_preview()

    def on_crop_preset_changed(self, index: int):
        # プリセットサイズ連動
        presets = {
            1: (60, 60),    # 国民精神
            2: (82, 82),    # 国家方針
            3: (156, 210)   # 指導者肖像画
        }
        
        if index in presets:
            w, h = presets[index]
            self.ui.spinCropWidth.setValue(w)
            self.ui.spinCropHeight.setValue(h)
            self.ui.spinCropWidth.setEnabled(False)
            self.ui.spinCropHeight.setEnabled(False)
        else:
            # 自由選択
            self.ui.spinCropWidth.setEnabled(True)
            self.ui.spinCropHeight.setEnabled(True)
            
        self.update_crop_rect_size()

    def on_crop_spin_changed(self):
        self.update_crop_rect_size()

    def update_crop_rect_size(self):
        if not self.original_image or self.original_image.isNull():
            return
            
        w = min(self.ui.spinCropWidth.value(), self.original_image.width())
        h = min(self.ui.spinCropHeight.value(), self.original_image.height())
        
        # トリミング枠のサイズ変更
        self.crop_rect_item.setRect(0, 0, w, h)
        
        # 範囲外に出ないようにクリップする
        pos = self.crop_rect_item.pos()
        x = max(0, min(pos.x(), self.original_image.width() - w))
        y = max(0, min(pos.y(), self.original_image.height() - h))
        self.crop_rect_item.setPos(x, y)
        
        self.update_preview()

    def trigger_preview_update(self):
        # デバウンス開始
        self.preview_timer.start()

    def update_preview(self):
        # 即時プレビュー更新（トリミングなど）
        self.update_preview_real()

    def update_preview_real(self):
        if not self.original_image or self.original_image.isNull():
            return
            
        if self.mode == "crop":
            # トリミング位置調整モード：元画像全体＋黄色い枠線を表示
            self.crop_rect_item.setVisible(True)
            self.pixmap_item.setPixmap(QPixmap.fromImage(self.original_image))
            
            # 画像と同サイズの背後チェッカーボードを更新
            w = self.original_image.width()
            h = self.original_image.height()
            self.background_checker_item.setRect(0, 0, w, h)
            self.background_checker_item.setPos(0, 0)
            self.background_checker_item.setVisible(True)
            
            # 画像サイズに合わせてビューポートを調整
            self.scene.setSceneRect(0, 0, w, h)
            self.ui.graphicsViewPreview.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            # エフェクトプレビューモード：トリミング後の画像にエフェクトを適用して表示
            self.crop_rect_item.setVisible(False)
            
            # 1. トリミングを適用
            pos = self.crop_rect_item.pos()
            rect = self.crop_rect_item.rect()
            
            x = int(max(0, min(pos.x(), self.original_image.width() - rect.width())))
            y = int(max(0, min(pos.y(), self.original_image.height() - rect.height())))
            w = int(rect.width())
            h = int(rect.height())
            
            img = self.original_image.copy(x, y, w, h)
            
            # 2. カラー化（未実装のためスキップ）
            
            # 3. ぼかし適用
            radius = self.ui.spinBlurRadius.value()
            threshold = self.ui.spinBlurThreshold.value()
            if radius > 1:
                img = self.apply_selective_blur(img, radius, threshold)
                
            # 4. シャープネス適用
            strength = self.ui.spinSharpenStrength.value()
            if strength > 0:
                img = self.apply_sharpen(img, strength)
                
            # 5. 背景削除（透過）適用
            tolerance = self.ui.spinRemoveBgTolerance.value()
            feather = self.ui.spinRemoveBgFeather.value()
            if tolerance > 0:
                img = self.apply_remove_background(img, tolerance, feather)
            
            self.processed_image = img
            self.pixmap_item.setPixmap(QPixmap.fromImage(self.processed_image))
            
            # 加工後画像サイズに合わせて背後チェッカーボードを更新
            self.background_checker_item.setRect(0, 0, w, h)
            self.background_checker_item.setPos(0, 0)
            self.background_checker_item.setVisible(True)
            
            # シーンの境界を加工後画像サイズにセット
            self.scene.setSceneRect(0, 0, w, h)
            self.ui.graphicsViewPreview.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def apply_selective_blur(self, img: QImage, radius: int, threshold: int) -> QImage:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        width = img.width()
        height = img.height()
        out = QImage(width, height, QImage.Format.Format_ARGB32)
        
        for y in range(height):
            for x in range(width):
                center_pixel = img.pixel(x, y)
                r0 = qRed(center_pixel)
                g0 = qGreen(center_pixel)
                b0 = qBlue(center_pixel)
                a0 = qAlpha(center_pixel)
                
                sum_r, sum_g, sum_b, sum_a = 0, 0, 0, 0
                total_weight = 0
                
                for dy in range(-radius, radius + 1):
                    ny = y + dy
                    if ny < 0 or ny >= height:
                        continue
                    for dx in range(-radius, radius + 1):
                        nx = x + dx
                        if nx < 0 or nx >= width:
                            continue
                            
                        dist_sq = dx*dx + dy*dy
                        if dist_sq > radius*radius:
                            continue
                            
                        pixel = img.pixel(nx, ny)
                        r = qRed(pixel)
                        g = qGreen(pixel)
                        b = qBlue(pixel)
                        a = qAlpha(pixel)
                        
                        # 輝度/色差（最大チャンネル差）としきい値を比較
                        max_diff = max(abs(r - r0), abs(g - g0), abs(b - b0))
                        
                        if max_diff <= threshold:
                            # 距離に基づく逆二乗の重み付け
                            weight = 1.0 / (1.0 + dist_sq * 0.5)
                            sum_r += r * weight
                            sum_g += g * weight
                            sum_b += b * weight
                            sum_a += a * weight
                            total_weight += weight
                
                if total_weight > 0:
                    new_r = int(sum_r / total_weight)
                    new_g = int(sum_g / total_weight)
                    new_b = int(sum_b / total_weight)
                    new_a = int(sum_a / total_weight)
                    out.setPixel(x, y, qRgba(new_r, new_g, new_b, new_a))
                else:
                    out.setPixel(x, y, center_pixel)
                    
        return out

    def apply_sharpen(self, img: QImage, strength: float) -> QImage:
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        width = img.width()
        height = img.height()
        out = QImage(width, height, QImage.Format.Format_ARGB32)
        
        factor = strength / 100.0
        
        for y in range(height):
            for x in range(width):
                if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                    out.setPixel(x, y, img.pixel(x, y))
                    continue
                    
                center = img.pixel(x, y)
                r0 = qRed(center)
                g0 = qGreen(center)
                b0 = qBlue(center)
                a0 = qAlpha(center)
                
                # 3x3 ラプラシアン畳み込み (4 * Center - Up - Down - Left - Right)
                up = img.pixel(x, y - 1)
                down = img.pixel(x, y + 1)
                left = img.pixel(x - 1, y)
                right = img.pixel(x + 1, y)
                
                sum_r = 4 * r0 - qRed(up) - qRed(down) - qRed(left) - qRed(right)
                sum_g = 4 * g0 - qGreen(up) - qGreen(down) - qGreen(left) - qGreen(right)
                sum_b = 4 * b0 - qBlue(up) - qBlue(down) - qBlue(left) - qBlue(right)
                
                new_r = max(0, min(255, int(r0 + sum_r * factor)))
                new_g = max(0, min(255, int(g0 + sum_g * factor)))
                new_b = max(0, min(255, int(b0 + sum_b * factor)))
                
                out.setPixel(x, y, qRgba(new_r, new_g, new_b, a0))
                
        return out

    def apply_remove_background(self, img: QImage, tolerance: int, feather: int) -> QImage:
        """手動で選択された基準背景色としきい値、ぼかしを適用して透過する（未選択時は透過しない）"""
        if not self.remove_bg_key_color:
            return img
            
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        width = img.width()
        height = img.height()
        out = QImage(width, height, QImage.Format.Format_ARGB32)
        
        bg_r = self.remove_bg_key_color.red()
        bg_g = self.remove_bg_key_color.green()
        bg_b = self.remove_bg_key_color.blue()
            
        for y in range(height):
            for x in range(width):
                pixel = img.pixel(x, y)
                r = qRed(pixel)
                g = qGreen(pixel)
                b = qBlue(pixel)
                a = qAlpha(pixel)
                
                # 背景色との差（RGB各チャンネルの最大絶対差）
                diff = max(abs(r - bg_r), abs(g - bg_g), abs(b - bg_b))
                
                if diff <= tolerance:
                    # 完全透明
                    new_a = 0
                elif feather > 0 and diff <= (tolerance + feather):
                    # フェザー（グラデーション透過）領域
                    ratio = (diff - tolerance) / feather
                    new_a = int(a * ratio)
                else:
                    # 元のまま
                    new_a = a
                    
                out.setPixel(x, y, qRgba(r, g, b, new_a))
                
        return out

    def select_key_color(self):
        """ユーザーが透過対象のカラーを手動で選択できるようにダイアログを起動する"""
        # 現在のカラーを初期値として設定
        initial_color = QColor(0, 0, 0)
        if self.remove_bg_key_color:
            initial_color = self.remove_bg_key_color
        else:
            # ダイアログ初期値のフォールバックとして左上ピクセルの色を推薦する
            if self.original_image and not self.original_image.isNull():
                bg_pixel = self.original_image.pixel(0, 0)
                if qAlpha(bg_pixel) > 0:
                    initial_color = QColor(qRed(bg_pixel), qGreen(bg_pixel), qBlue(bg_pixel))
                    
        color = QColorDialog.getColor(initial_color, self, "透過対象の色（キーカラー）を選択")
        if color.isValid():
            self.remove_bg_key_color = color
            self.update_key_color_preview()
            self.trigger_preview_update()
            
    def update_key_color_preview(self):
        """カラープレビューフレームの背景色を選択された色で塗りつぶす。未選択時は破線枠にする"""
        if hasattr(self.ui, "frameRemoveBgKeyColor"):
            color = self.remove_bg_key_color
            if color:
                # スタイルシートを使ってプレビューフレームの背景色を設定
                self.ui.frameRemoveBgKeyColor.setStyleSheet(
                    f"background-color: rgb({color.red()}, {color.green()}, {color.blue()}); border: 1px solid palette(mid);"
                )
            else:
                # 未選択時は透明かつ破線にする
                self.ui.frameRemoveBgKeyColor.setStyleSheet(
                    "background-color: transparent; border: 1px dashed palette(mid);"
                )

    def on_accept(self):
        # 現時点ではOKでファイル保存しない。プレビュー結果だけ更新して閉じる。
        self.switch_mode("effect", self.ui.stackedWidgetSettings.currentIndex())
        self.saved_png_path = None
        self.accept()
