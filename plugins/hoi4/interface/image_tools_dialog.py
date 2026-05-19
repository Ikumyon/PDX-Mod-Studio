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

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

import urllib.request
import numpy as np

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
        self.scene.setBackgroundBrush(QBrush(QColor(50, 50, 50)))
        self.ui.graphicsViewPreview.setScene(self.scene)
        
        # 透過画像背後用のチェッカーボードパターン
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
        self.background_checker_item.setZValue(-1)
        self.background_checker_item.setVisible(False)
        self.scene.addItem(self.background_checker_item)
        
        self.pixmap_item = QGraphicsPixmapItem()
        self.pixmap_item.setZValue(0)
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
        
        # デバウンス用のタイマー
        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(50)
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
        if HAS_PIL:
            try:
                pil_img = Image.open(path)
                pil_img = pil_img.convert("RGBA")
                data = pil_img.tobytes("raw", "RGBA")
                qimg = QImage(data, pil_img.size[0], pil_img.size[1], QImage.Format.Format_RGBA8888)
                return qimg.copy()
            except Exception as e:
                print(f"Pillow failed to load image ({path}): {e}. Retrying with native QImage...")
        return QImage(path)

    def bind_controls(self):
        # ツールボタンのバインド
        self.ui.toolButtonCrop.clicked.connect(lambda: self.switch_mode("crop", 0))
        self.ui.toolButtonBlur.clicked.connect(lambda: self.switch_mode("effect", 1))
        self.ui.toolButtonSharpen.clicked.connect(lambda: self.switch_mode("effect", 2))
        self.ui.toolButtonRemoveBg.clicked.connect(lambda: self.switch_mode("effect", 3))
        self.ui.toolButtonColorize.clicked.connect(lambda: self.switch_mode("effect", 4))
        
        # トリミングコントロールのバインド
        self.ui.comboMainPreset.currentIndexChanged.connect(self.on_crop_preset_changed)
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

        # カラー化コントロールのバインド
        self.ui.sliderColorizeHue.valueChanged.connect(self.ui.spinColorizeHue.setValue)
        self.ui.spinColorizeHue.valueChanged.connect(self.ui.sliderColorizeHue.setValue)
        self.ui.sliderColorizeHue.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderColorizeSaturation.valueChanged.connect(self.ui.spinColorizeSaturation.setValue)
        self.ui.spinColorizeSaturation.valueChanged.connect(self.ui.sliderColorizeSaturation.setValue)
        self.ui.sliderColorizeSaturation.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderColorizeLightness.valueChanged.connect(self.ui.spinColorizeLightness.setValue)
        self.ui.spinColorizeLightness.valueChanged.connect(self.ui.sliderColorizeLightness.setValue)
        self.ui.sliderColorizeLightness.valueChanged.connect(self.trigger_preview_update)

        # 有効化チェックボックスのバインド
        self.ui.chkBlurEnable.toggled.connect(self.on_blur_enable_toggled)
        self.ui.chkSharpenEnable.toggled.connect(self.on_sharpen_enable_toggled)
        self.ui.chkRemoveBgEnable.toggled.connect(self.on_remove_bg_enable_toggled)
        self.ui.chkColorizeEnable.toggled.connect(self.on_colorize_enable_toggled)

        # OK / Cancel の接続
        self.ui.buttonBox.accepted.connect(self.on_accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    def load_masks(self):
        """masks/ ディレクトリ直下のJSONファイルおよびローカライズ定義を読み込み、コンボボックスに追加する"""
        import json
        
        base_dir = os.path.dirname(__file__)
        masks_dir = os.path.normpath(os.path.join(base_dir, "masks"))
        
        # 1. ローカライズ定義の読み込み
        loc_data = {}
        # 日本語を最優先、無ければ英語をフォールバック
        for lang in ["ja-jp", "en-us"]:
            loc_path = os.path.join(masks_dir, "localisation", f"{lang}.json")
            if os.path.exists(loc_path):
                try:
                    with open(loc_path, "r", encoding="utf-8") as f:
                        loc_data = json.load(f)
                    break
                except Exception as e:
                    print(f"Failed to load localization {lang}.json: {e}")
                    
        # 2. コンボボックスのクリアと「選択なし」の追加
        self.ui.comboMaskImage.clear()
        no_mask_label = loc_data.get("NO_MASK", "選択なし")
        self.ui.comboMaskImage.addItem(no_mask_label, None)
        
        # 3. マスクJSONファイルの検索とロード
        if os.path.exists(masks_dir):
            for file_name in os.listdir(masks_dir):
                if file_name.endswith(".json"):
                    file_path = os.path.join(masks_dir, file_name)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            mask_config = json.load(f)
                            
                        mask_id = mask_config.get("id")
                        name_key = mask_config.get("name_key")
                        # ローカライズ名を取得
                        display_name = loc_data.get(name_key, mask_id or file_name)
                        
                        # コンボボックスに追加 (itemData に mask_config を設定)
                        self.ui.comboMaskImage.addItem(display_name, mask_config)
                    except Exception as e:
                        print(f"Failed to load mask config {file_name}: {e}")

    def init_ui_states(self):
        self.ui.stackedWidgetSettings.setCurrentIndex(0)
        self.ui.comboMainPreset.setCurrentIndex(0)
        
        # ぼかし初期化（有効化依存）
        self.ui.chkBlurEnable.setChecked(False)
        self.ui.sliderBlurRadius.setEnabled(False)
        self.ui.spinBlurRadius.setEnabled(False)
        self.ui.sliderBlurThreshold.setEnabled(False)
        self.ui.spinBlurThreshold.setEnabled(False)
        
        self.ui.sliderBlurRadius.setValue(1)
        self.ui.spinBlurRadius.setValue(1)
        self.ui.sliderBlurThreshold.setValue(30)
        self.ui.spinBlurThreshold.setValue(30)
        
        # シャープネス初期化（有効化依存）
        self.ui.chkSharpenEnable.setChecked(False)
        self.ui.sliderSharpenStrength.setEnabled(False)
        self.ui.spinSharpenStrength.setEnabled(False)
        
        self.ui.sliderSharpenStrength.setValue(0)
        self.ui.spinSharpenStrength.setValue(0)
        
        # 背景削除初期化（有効化依存）
        self.ui.chkRemoveBgEnable.setChecked(False)
        self.ui.sliderRemoveBgTolerance.setEnabled(False)
        self.ui.spinRemoveBgTolerance.setEnabled(False)
        self.ui.sliderRemoveBgFeather.setEnabled(False)
        self.ui.spinRemoveBgFeather.setEnabled(False)
        self.ui.btnSelectKeyColor.setEnabled(False)
        
        self.ui.sliderRemoveBgTolerance.setValue(30)
        self.ui.spinRemoveBgTolerance.setValue(30)
        self.ui.sliderRemoveBgFeather.setValue(5)
        self.ui.spinRemoveBgFeather.setValue(5)
        self.update_key_color_preview()

        # AIカラー化初期化
        self.ui.chkColorizeEnable.setChecked(False)
        self.ui.sliderColorizeHue.setValue(0)
        self.ui.spinColorizeHue.setValue(0)
        self.ui.sliderColorizeSaturation.setValue(0)
        self.ui.spinColorizeSaturation.setValue(0)
        self.ui.sliderColorizeLightness.setValue(0)
        self.ui.spinColorizeLightness.setValue(0)
        
        self.init_colorize_models()
        
        # トリミング枠の初期位置
        if self.original_image and not self.original_image.isNull():
            w = min(60, self.original_image.width())
            h = min(60, self.original_image.height())
            self.ui.spinCropWidth.setValue(w)
            self.ui.spinCropHeight.setValue(h)
            x = (self.original_image.width() - w) / 2
            y = (self.original_image.height() - h) / 2
            self.crop_rect_item.setPos(x, y)
            
        # マスク一覧のロード
        self.load_masks()

    def switch_mode(self, mode: str, index: int):
        self.mode = mode
        self.ui.stackedWidgetSettings.setCurrentIndex(index)
        self.update_preview()

    def on_crop_preset_changed(self, index: int):
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
        self.crop_rect_item.setRect(0, 0, w, h)
        pos = self.crop_rect_item.pos()
        x = max(0, min(pos.x(), self.original_image.width() - w))
        y = max(0, min(pos.y(), self.original_image.height() - h))
        self.crop_rect_item.setPos(x, y)
        self.update_preview()

    def trigger_preview_update(self):
        self.preview_timer.start()

    def update_preview(self):
        self.update_preview_real()

    def update_preview_real(self):
        if not self.original_image or self.original_image.isNull():
            return
            
        if self.mode == "crop":
            self.crop_rect_item.setVisible(True)
            self.pixmap_item.setPixmap(QPixmap.fromImage(self.original_image))
            w = self.original_image.width()
            h = self.original_image.height()
            self.background_checker_item.setRect(0, 0, w, h)
            self.background_checker_item.setPos(0, 0)
            self.background_checker_item.setVisible(True)
            self.scene.setSceneRect(0, 0, w, h)
            self.ui.graphicsViewPreview.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self.crop_rect_item.setVisible(False)
            pos = self.crop_rect_item.pos()
            rect = self.crop_rect_item.rect()
            
            x = int(max(0, min(pos.x(), self.original_image.width() - rect.width())))
            y = int(max(0, min(pos.y(), self.original_image.height() - rect.height())))
            w = int(rect.width())
            h = int(rect.height())
            
            img = self.original_image.copy(x, y, w, h)
            
            # 2. AIカラー化適用
            if self.ui.chkColorizeEnable.isChecked():
                img = self.apply_ai_colorization(img)
                
            # 3. ぼかし適用
            if self.ui.chkBlurEnable.isChecked():
                radius = self.ui.spinBlurRadius.value()
                threshold = self.ui.spinBlurThreshold.value()
                if radius > 1:
                    img = self.apply_selective_blur(img, radius, threshold)
                    
            # 4. シャープネス適用
            if self.ui.chkSharpenEnable.isChecked():
                strength = self.ui.spinSharpenStrength.value()
                if strength > 0:
                    img = self.apply_sharpen(img, strength)
                    
            # 5. 背景削除適用
            if self.ui.chkRemoveBgEnable.isChecked():
                tolerance = self.ui.spinRemoveBgTolerance.value()
                feather = self.ui.spinRemoveBgFeather.value()
                if tolerance > 0:
                    img = self.apply_remove_background(img, tolerance, feather)
            
            self.processed_image = img
            self.pixmap_item.setPixmap(QPixmap.fromImage(self.processed_image))
            self.background_checker_item.setRect(0, 0, w, h)
            self.background_checker_item.setPos(0, 0)
            self.background_checker_item.setVisible(True)
            self.scene.setSceneRect(0, 0, w, h)
            self.ui.graphicsViewPreview.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def on_blur_enable_toggled(self, checked: bool):
        self.ui.sliderBlurRadius.setEnabled(checked)
        self.ui.spinBlurRadius.setEnabled(checked)
        self.ui.sliderBlurThreshold.setEnabled(checked)
        self.ui.spinBlurThreshold.setEnabled(checked)
        self.trigger_preview_update()

    def on_sharpen_enable_toggled(self, checked: bool):
        self.ui.sliderSharpenStrength.setEnabled(checked)
        self.ui.spinSharpenStrength.setEnabled(checked)
        self.trigger_preview_update()

    def on_remove_bg_enable_toggled(self, checked: bool):
        self.ui.sliderRemoveBgTolerance.setEnabled(checked)
        self.ui.spinRemoveBgTolerance.setEnabled(checked)
        self.ui.sliderRemoveBgFeather.setEnabled(checked)
        self.ui.spinRemoveBgFeather.setEnabled(checked)
        self.ui.btnSelectKeyColor.setEnabled(checked)
        self.trigger_preview_update()

    def on_colorize_enable_toggled(self, checked: bool):
        self.ui.labelColorizeModel.setEnabled(checked)
        self.ui.comboColorizeModel.setEnabled(checked)
        self.ui.sliderColorizeHue.setEnabled(checked)
        self.ui.spinColorizeHue.setEnabled(checked)
        self.ui.sliderColorizeSaturation.setEnabled(checked)
        self.ui.spinColorizeSaturation.setEnabled(checked)
        self.ui.sliderColorizeLightness.setEnabled(checked)
        self.ui.spinColorizeLightness.setEnabled(checked)
        
        if checked:
            if self.ensure_model_files():
                self.trigger_preview_update()
        else:
            self.trigger_preview_update()

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
                        
                        max_diff = max(abs(r - r0), abs(g - g0), abs(b - b0))
                        
                        if max_diff <= threshold:
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
                
                diff = max(abs(r - bg_r), abs(g - bg_g), abs(b - bg_b))
                
                if diff <= tolerance:
                    new_a = 0
                elif feather > 0 and diff <= (tolerance + feather):
                    ratio = (diff - tolerance) / feather
                    new_a = int(a * ratio)
                else:
                    new_a = a
                    
                out.setPixel(x, y, qRgba(r, g, b, new_a))
                
        return out

    def select_key_color(self):
        initial_color = QColor(0, 0, 0)
        if self.remove_bg_key_color:
            initial_color = self.remove_bg_key_color
        else:
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
        if hasattr(self.ui, "frameRemoveBgKeyColor"):
            color = self.remove_bg_key_color
            if color:
                self.ui.frameRemoveBgKeyColor.setStyleSheet(
                    f"background-color: rgb({color.red()}, {color.green()}, {color.blue()}); border: 1px solid palette(mid);"
                )
            else:
                self.ui.frameRemoveBgKeyColor.setStyleSheet(
                    "background-color: transparent; border: 1px dashed palette(mid);"
                )

    def on_accept(self):
        self.switch_mode("effect", self.ui.stackedWidgetSettings.currentIndex())
        self.saved_png_path = None
        self.accept()

    # ==========================================
    # 🌟 AIカラー化モデル定義・ロード・推論ハンドラ群
    # ==========================================
    def init_colorize_models(self):
        self.all_models = []
        
        # 1. 内蔵の標準モデルを静的インポート（疎結合）で直接ロード
        from .colorize.core.eccv2016_model import ECCV2016Model
        base_dir = os.path.dirname(__file__)
        eccv2016_json_path = os.path.join(base_dir, "colorize", "definitions", "eccv2016.json")
        try:
            import json
            with open(eccv2016_json_path, "r", encoding="utf-8") as f:
                eccv2016_metadata = json.load(f)
            self.all_models.append(ECCV2016Model(eccv2016_metadata))
        except Exception as e:
            # 設定JSONから100%駆動するため、例外をそのまま投げて通知
            raise RuntimeError(f"Failed to load core model config (eccv2016.json): {e}")

        # 2. 外部アドオンモデルを専用ローダーでスキャン＆マージ
        from .colorize.core.loader import ColorizePluginLoader
        self.plugin_loader = ColorizePluginLoader(base_dir)
        external_models = self.plugin_loader.load_plugin_models(reserved_ids=[m.get_id() for m in self.all_models])
        self.all_models.extend(external_models)
        
        self.active_model = self.all_models[0] if self.all_models else None
        
        self.ui.comboColorizeModel.clear()
        for model in self.all_models:
            self.ui.comboColorizeModel.addItem(model.get_name(), model.get_id())
            
        self.ui.labelColorizeModel.setEnabled(False)
        self.ui.comboColorizeModel.setEnabled(False)
        self.ui.comboColorizeModel.currentIndexChanged.connect(self.on_colorize_model_changed)

    def on_colorize_model_changed(self, index: int):
        selected_id = self.ui.comboColorizeModel.itemData(index)
        for model in self.all_models:
            if model.get_id() == selected_id:
                self.active_model = model
                break
                
        if self.ui.chkColorizeEnable.isChecked():
            if self.ensure_model_files():
                self.trigger_preview_update()

    def ensure_model_files(self) -> bool:
        if not hasattr(self, "active_model") or self.active_model is None:
            return True
            
        base_dir = os.path.dirname(__file__)
        models_dir = os.path.join(base_dir, "colorize", "models")
        
        model_sub_dir = os.path.join(models_dir, self.active_model.get_id())
        os.makedirs(model_sub_dir, exist_ok=True)
        
        files = self.active_model.get_files_config()
        
        mirrors = {
            "colorization_release_v2.caffemodel": [
                "https://dl.opencv.org/models/colorization_release_v2.caffemodel",
                "https://lms.comp.nus.edu.sg/wp-content/uploads/2018/research/colorization/colorization_release_v2.caffemodel"
            ]
        }
        
        def check_for_updates(filename: str, url: str) -> bool:
            path = os.path.join(model_sub_dir, filename)
            if not os.path.exists(path):
                return False
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}, method='HEAD')
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    server_size = int(response.info().get('Content-Length', 0))
                    local_size = os.path.getsize(path)
                    if server_size > 0 and local_size != server_size:
                        return True
            except Exception:
                pass
            return False

        missing_files = []
        updated_files = []
        
        for filename in files.keys():
            path = os.path.join(model_sub_dir, filename)
            if not os.path.exists(path) or os.path.getsize(path) < 1000:
                missing_files.append(filename)
                
        for filename, url in files.items():
            if filename not in missing_files:
                if check_for_updates(filename, url):
                    updated_files.append(filename)
                    
        if updated_files:
            reply = QMessageBox.question(
                self,
                "AIモデルファイルの更新検出",
                f"新しいバージョンのモデルファイルが検出されました：\n{', '.join(updated_files)}\n\n最新バージョンをダウンロードして更新しますか？\n（※「いいえ」を選択した場合は、現在の古いモデルを使い続けます）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                for filename in updated_files:
                    path = os.path.join(model_sub_dir, filename)
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                        missing_files.append(filename)
                    except Exception:
                        pass

        if not missing_files:
            return True
            
        if not updated_files:
            reply = QMessageBox.question(
                self,
                "AIカラー化モデルのダウンロード",
                f"AIモデル（{self.active_model.get_name()}）を利用するには、学習済みモデルファイル等のダウンロードが必要です。\n\nダウンロードを開始しますか？\n（※通信環境によっては完了まで数分かかる場合があります）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
        else:
            reply = QMessageBox.StandardButton.Yes
        
        if reply == QMessageBox.StandardButton.No:
            return False
            
        from PySide6.QtWidgets import QProgressDialog
        progress = QProgressDialog("モデルファイルをダウンロード中...", "キャンセル", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        def download_progress(block_num, block_size, total_size):
            if progress.wasCanceled():
                raise Exception("Download canceled by user")
            if total_size > 0:
                percent = int(block_num * block_size * 100 / total_size)
                progress.setValue(min(100, percent))
                QCoreApplication.processEvents()
                
        try:
            for filename in missing_files:
                path = os.path.join(model_sub_dir, filename)
                progress.setLabelText(f"{filename} をダウンロード中...")
                progress.setValue(0)
                QCoreApplication.processEvents()
                
                urls_to_try = mirrors.get(filename, [files[filename]])
                success = False
                last_err = None
                
                for url in urls_to_try:
                    try:
                        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                        with urllib.request.urlopen(req) as response, open(path, 'wb') as out_file:
                            total_size = int(response.info().get('Content-Length', 0))
                            block_size = 8192
                            downloaded = 0
                            while True:
                                block = response.read(block_size)
                                if not block:
                                    break
                                out_file.write(block)
                                downloaded += len(block)
                                download_progress(downloaded // block_size + 1, block_size, total_size)
                        success = True
                        break
                    except Exception as e:
                        last_err = e
                        if os.path.exists(path):
                            os.remove(path)
                        continue
                        
                if not success:
                    raise last_err or Exception(f"Failed to download {filename}")
                    
            progress.setValue(100)
            QMessageBox.information(self, "完了", "AIモデルファイルのダウンロードが完了しました。")
            return True
            
        except Exception as e:
            progress.close()
            return False

    def apply_ai_colorization(self, img: QImage) -> QImage:
        if not HAS_CV2 or not hasattr(self, "active_model") or self.active_model is None:
            return img
            
        try:
            img_format = img.format()
            if img_format != QImage.Format.Format_ARGB32 and img_format != QImage.Format.Format_RGB32:
                img = img.convertToFormat(QImage.Format.Format_ARGB32)
                
            width, height = img.width(), img.height()
            
            ptr = img.bits()
            import cv2
            bgra = np.array(ptr).reshape((height, width, 4)).copy()
            bgr = bgra[:, :, :3]
            
            if not hasattr(self.active_model, "net") or self.active_model.net is None:
                base_dir = os.path.dirname(__file__)
                models_dir = os.path.join(base_dir, "colorize", "models")
                print(f"[AI Colorize] Dynamically loading network for model: {self.active_model.get_id()}")
                self.active_model.load_network(models_dir)
                
            result_bgr = self.active_model.predict(bgr)
            
            h_shift = self.ui.sliderColorizeHue.value()
            s_shift = self.ui.sliderColorizeSaturation.value()
            l_shift = self.ui.sliderColorizeLightness.value()
            
            if h_shift != 0 or s_shift != 0 or l_shift != 0:
                result_bgr = self.apply_hsl_adjustment(result_bgr, h_shift, s_shift, l_shift)
            
            result_rgba = cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGBA)
            rgba_contiguous = np.ascontiguousarray(result_rgba)
            
            qimg = QImage(rgba_contiguous.data, width, height, QImage.Format.Format_RGBA8888)
            return qimg.copy()
            
        except Exception as e:
            print(f"[AI Colorize] Inference error: {e}")
            return img

    def apply_hsl_adjustment(self, bgr_img, h_shift, s_shift, l_shift) -> np.ndarray:
        import cv2
        hls = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HLS).astype("float32")
        if h_shift != 0:
            hls[:, :, 0] = (hls[:, :, 0] + h_shift) % 180
        if s_shift != 0:
            hls[:, :, 2] = np.clip(hls[:, :, 2] + s_shift, 0, 255)
        if l_shift != 0:
            hls[:, :, 1] = np.clip(hls[:, :, 1] + l_shift, 0, 255)
        adjusted_bgr = cv2.cvtColor(hls.astype("uint8"), cv2.COLOR_HLS2BGR)
        return adjusted_bgr
