import os
from PySide6.QtCore import QEvent, QFile, Qt, QTimer, QCoreApplication
from PySide6.QtGui import QImage, QPixmap, QPen, QColor, QBrush, qRed, qGreen, qBlue, qAlpha
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem,
    QGraphicsItem, QMessageBox, QColorDialog
)
from PySide6.QtUiTools import QUiLoader

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

import numpy as np
from plugins.hoi4.interface.image_effects import (
    adjust_hsl,
    apply_alpha_mask_pil,
    edge_enhance_cv2,
    remove_background_cv2,
    resize_pil,
    selective_blur_cv2,
    sharpen_cv2,
)
from plugins.hoi4.interface.mask_repository import load_mask_choices, resolve_mask_image_path
from plugins.hoi4.interface.ui_image_helpers import create_checker_item, load_pil_image, pil_to_qimage, qimage_to_pil
from plugins.hoi4.interface.colorize.core.model_assets import (
    download_model_assets,
    inspect_model_assets,
    remove_model_asset_ids,
)

tr = QCoreApplication.translate

class ImageToolsDialog(QDialog):
    ANIMATED_EXTENSIONS = {".gif", ".webp", ".apng"}

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.saved_png_path = None
        self.original_image = None
        self.original_pil = None
        self.processed_image = None
        self.preview_image = None
        self.filter_settings = None
        self.remove_bg_key_color = None  # クロマキー透過の基準色（Noneなら左上から自動検出）
        self.edge_color = QColor(255, 255, 255)  # エッジ強調のエッジ色
        
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
        
        self.background_checker_item = create_checker_item()
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
            self.original_pil = load_pil_image(self.image_path)
            if self.original_pil:
                self.original_image = pil_to_qimage(self.original_pil)
            else:
                self.original_image = QImage(self.image_path)
            if self.original_image.isNull():
                print(f"Failed to load image: {self.image_path}")

        self.bind_controls()
        self.update_animation_controls_visibility()
        self.init_ui_states()
        self.update_preview()

    def bind_controls(self):
        # ツールボタンのバインド
        self.ui.toolButtonCrop.clicked.connect(lambda: self.switch_mode("crop", 0))
        self.ui.toolButtonBlur.clicked.connect(lambda: self.switch_mode("effect", 1))
        self.ui.toolButtonSharpen.clicked.connect(lambda: self.switch_mode("effect", 2))
        self.ui.toolButtonRemoveBg.clicked.connect(lambda: self.switch_mode("effect", 3))
        self.ui.toolButtonColorize.clicked.connect(lambda: self.switch_mode("effect", 4))
        self.ui.toolButtonEdge.clicked.connect(lambda: self.switch_mode("effect", 5))
        
        # トリミングコントロールのバインド
        self.ui.comboMainPreset.currentIndexChanged.connect(self.on_crop_preset_changed)
        self.ui.spinCropWidth.valueChanged.connect(self.on_crop_spin_changed)
        self.ui.spinCropHeight.valueChanged.connect(self.on_crop_spin_changed)
        self.ui.spinCropX.valueChanged.connect(self.on_crop_position_changed)
        self.ui.spinCropY.valueChanged.connect(self.on_crop_position_changed)
        self.ui.comboMaskImage.currentIndexChanged.connect(self.on_mask_changed)
        self.ui.spinMaskScale.valueChanged.connect(self.trigger_preview_update)
        self.ui.spinMaskX.valueChanged.connect(self.trigger_preview_update)
        self.ui.spinMaskY.valueChanged.connect(self.trigger_preview_update)
        self.ui.chkCropMaskOutside.toggled.connect(self.trigger_preview_update)
        self.ui.spinScale.valueChanged.connect(self.trigger_preview_update)
        self.ui.comboInterpolation.currentIndexChanged.connect(self.trigger_preview_update)
        self.ui.chkZoomFit.toggled.connect(self.on_zoom_fit_toggled)
        self.ui.sliderZoom.valueChanged.connect(self.ui.spinZoom.setValue)
        self.ui.spinZoom.valueChanged.connect(self.ui.sliderZoom.setValue)
        self.ui.sliderZoom.valueChanged.connect(lambda _value: self.update_preview_view_scale())
        
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

        # エッジ強調コントロールのバインド
        self.ui.sliderEdgeThreshold1.valueChanged.connect(self.ui.spinEdgeThreshold1.setValue)
        self.ui.spinEdgeThreshold1.valueChanged.connect(self.ui.sliderEdgeThreshold1.setValue)
        self.ui.sliderEdgeThreshold1.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderEdgeThreshold2.valueChanged.connect(self.ui.spinEdgeThreshold2.setValue)
        self.ui.spinEdgeThreshold2.valueChanged.connect(self.ui.sliderEdgeThreshold2.setValue)
        self.ui.sliderEdgeThreshold2.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderEdgeStrength.valueChanged.connect(self.ui.spinEdgeStrength.setValue)
        self.ui.spinEdgeStrength.valueChanged.connect(self.ui.sliderEdgeStrength.setValue)
        self.ui.sliderEdgeStrength.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.comboEdgeMethod.currentIndexChanged.connect(self.trigger_preview_update)
        self.ui.btnSelectEdgeColor.clicked.connect(self.select_edge_color)
        
        self.ui.sliderEdgeWidth.valueChanged.connect(self.ui.spinEdgeWidth.setValue)
        self.ui.spinEdgeWidth.valueChanged.connect(self.ui.sliderEdgeWidth.setValue)
        self.ui.sliderEdgeWidth.valueChanged.connect(self.trigger_preview_update)
        
        self.ui.sliderEdgeSmooth.valueChanged.connect(self.ui.spinEdgeSmooth.setValue)
        self.ui.spinEdgeSmooth.valueChanged.connect(self.ui.sliderEdgeSmooth.setValue)
        self.ui.sliderEdgeSmooth.valueChanged.connect(self.trigger_preview_update)

        # 有効化チェックボックスのバインド
        self.ui.chkBlurEnable.toggled.connect(self.on_blur_enable_toggled)
        self.ui.chkSharpenEnable.toggled.connect(self.on_sharpen_enable_toggled)
        self.ui.chkRemoveBgEnable.toggled.connect(self.on_remove_bg_enable_toggled)
        self.ui.chkColorizeEnable.toggled.connect(self.on_colorize_enable_toggled)
        self.ui.chkEdgeEnable.toggled.connect(self.on_edge_enable_toggled)

        # OK / Cancel の接続
        self.ui.buttonBox.accepted.connect(self.on_accept)
        self.ui.buttonBox.rejected.connect(self.reject)
        self.ui.graphicsViewPreview.viewport().installEventFilter(self)

    def load_masks(self):
        """masks/ ディレクトリの定義を読み込み、コンボボックスに追加する"""
        self.ui.comboMaskImage.clear()
        base_dir = os.path.dirname(__file__)
        for choice in load_mask_choices(base_dir):
            self.ui.comboMaskImage.addItem(choice.label, choice.config)

    def load_presets(self):
        """presets/ ディレクトリの定義を読み込み、コンボボックスに追加する"""
        from plugins.hoi4.interface.preset_repository import load_preset_choices
        self.ui.comboMainPreset.blockSignals(True)
        self.ui.comboMainPreset.clear()
        base_dir = os.path.dirname(__file__)
        for choice in load_preset_choices(base_dir):
            self.ui.comboMainPreset.addItem(choice.label, choice.config)
        self.ui.comboMainPreset.blockSignals(False)

    def update_animation_controls_visibility(self):
        preview_control_group = getattr(self.ui, "groupPreviewControl", None)
        if not preview_control_group:
            return
        preview_control_group.setVisible(self.is_animated_image_source())

    def is_animated_image_source(self) -> bool:
        ext = os.path.splitext(self.image_path or "")[1].lower()
        return ext in self.ANIMATED_EXTENSIONS

    def init_ui_states(self):
        self.ui.stackedWidgetSettings.setCurrentIndex(0)
        self.ui.comboMainPreset.setCurrentIndex(-1)
        self.init_interpolation_options()
        self.on_zoom_fit_toggled(self.ui.chkZoomFit.isChecked())
        
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

        # エッジ強調初期化
        self.ui.chkEdgeEnable.setChecked(False)
        self.ui.comboEdgeMethod.setEnabled(False)
        self.ui.sliderEdgeThreshold1.setEnabled(False)
        self.ui.spinEdgeThreshold1.setEnabled(False)
        self.ui.sliderEdgeThreshold2.setEnabled(False)
        self.ui.spinEdgeThreshold2.setEnabled(False)
        self.ui.sliderEdgeStrength.setEnabled(False)
        self.ui.spinEdgeStrength.setEnabled(False)
        self.ui.sliderEdgeWidth.setEnabled(False)
        self.ui.spinEdgeWidth.setEnabled(False)
        self.ui.sliderEdgeSmooth.setEnabled(False)
        self.ui.spinEdgeSmooth.setEnabled(False)
        
        self.ui.comboEdgeMethod.setCurrentIndex(0) # Canny
        self.ui.sliderEdgeThreshold1.setValue(50)
        self.ui.spinEdgeThreshold1.setValue(50)
        self.ui.sliderEdgeThreshold2.setValue(150)
        self.ui.spinEdgeThreshold2.setValue(150)
        self.ui.sliderEdgeStrength.setValue(50)
        self.ui.spinEdgeStrength.setValue(50)
        self.ui.sliderEdgeWidth.setValue(1)
        self.ui.spinEdgeWidth.setValue(1)
        self.ui.sliderEdgeSmooth.setValue(1)
        self.ui.spinEdgeSmooth.setValue(1)
        self.ui.btnSelectEdgeColor.setEnabled(False)
        self.update_edge_color_preview()
        
        # トリミング枠の初期位置
        if self.original_image and not self.original_image.isNull():
            w = self.original_image.width()
            h = self.original_image.height()
            self.ui.spinCropWidth.setValue(w)
            self.ui.spinCropHeight.setValue(h)
            self.ui.spinCropX.setValue(0)
            self.ui.spinCropY.setValue(0)
            self.crop_rect_item.setRect(0, 0, w, h)
            self.crop_rect_item.setPos(0, 0)
            self.update_crop_position_ranges()
            
            # マスク位置調整スピンボックスの範囲設定
            self.ui.spinMaskX.setRange(-self.original_image.width(), self.original_image.width())
            self.ui.spinMaskY.setRange(-self.original_image.height(), self.original_image.height())
            
        # マスク一覧とプリセット一覧のロード
        self.load_masks()
        self.load_presets()

    def init_interpolation_options(self):
        self.ui.comboInterpolation.clear()
        self.ui.comboInterpolation.addItem("双線形補間", "bilinear")
        self.ui.comboInterpolation.addItem("最近傍補間", "nearest")
        self.ui.comboInterpolation.addItem("バイキュービック補間", "bicubic")
        self.ui.comboInterpolation.addItem("Lanczos補間", "lanczos")
        self.ui.comboInterpolation.addItem("面積補間", "area")

    def switch_mode(self, mode: str, index: int):
        self.mode = mode
        self.ui.stackedWidgetSettings.setCurrentIndex(index)
        self.update_preview()

    def on_crop_preset_changed(self, index: int):
        if index < 0:
            return
            
        settings_data = self.ui.comboMainPreset.itemData(index)
        
        if isinstance(settings_data, dict) and "settings" in settings_data:
            filter_settings = settings_data["settings"]
            
            self.ui.spinCropWidth.blockSignals(True)
            self.ui.spinCropHeight.blockSignals(True)
            self.ui.spinCropX.blockSignals(True)
            self.ui.spinCropY.blockSignals(True)
            
            self.apply_filter_settings(filter_settings)
            
            self.ui.spinCropWidth.blockSignals(False)
            self.ui.spinCropHeight.blockSignals(False)
            self.ui.spinCropX.blockSignals(False)
            self.ui.spinCropY.blockSignals(False)
            self.ui.spinCropWidth.setEnabled(True)
            self.ui.spinCropHeight.setEnabled(True)
                
        else:
            self.ui.spinCropWidth.setEnabled(True)
            self.ui.spinCropHeight.setEnabled(True)
            
        self.update_crop_rect_size()

    def on_crop_spin_changed(self):
        self.update_crop_rect_size()

    def on_mask_changed(self, index: int):
        self.auto_adjust_mask_scale()
        self.trigger_preview_update()

    def auto_adjust_mask_scale(self):
        mask_index = self.ui.comboMaskImage.currentIndex()
        if mask_index <= 0:
            return
            
        mask_config = self.ui.comboMaskImage.itemData(mask_index)
        if not mask_config:
            return
            
        base_dir = os.path.dirname(__file__)
        from plugins.hoi4.interface.mask_repository import resolve_mask_image_path
        mask_path = resolve_mask_image_path(base_dir, mask_config)
        if not mask_path:
            return
            
        from plugins.hoi4.interface.ui_image_helpers import load_pil_image
        mask_img = load_pil_image(mask_path)
        if not mask_img or mask_img.width <= 0 or mask_img.height <= 0:
            return

        target_w = self.ui.spinCropWidth.value()
        target_h = self.ui.spinCropHeight.value()
        
        if target_w <= 0 or target_h <= 0:
            return
            
        scale_w = target_w / mask_img.width
        scale_h = target_h / mask_img.height
        
        scale = max(scale_w, scale_h) * 100.0
        
        self.ui.spinMaskScale.blockSignals(True)
        self.ui.spinMaskX.blockSignals(True)
        self.ui.spinMaskY.blockSignals(True)
        
        self.ui.spinMaskScale.setValue(int(round(scale)))
        self.ui.spinMaskX.setValue(0)
        self.ui.spinMaskY.setValue(0)
        
        self.ui.spinMaskScale.blockSignals(False)
        self.ui.spinMaskX.blockSignals(False)
        self.ui.spinMaskY.blockSignals(False)

    def on_crop_position_changed(self):
        self.update_crop_rect_position()

    def update_crop_rect_size(self):
        if not self.original_image or self.original_image.isNull():
            return
        w = min(self.ui.spinCropWidth.value(), self.original_image.width())
        h = min(self.ui.spinCropHeight.value(), self.original_image.height())
        self.crop_rect_item.setRect(0, 0, w, h)
        self.update_crop_position_ranges()
        self.update_crop_rect_position()

    def update_crop_position_ranges(self):
        if not self.original_image or self.original_image.isNull():
            return

        max_x = max(0, self.original_image.width() - self.ui.spinCropWidth.value())
        max_y = max(0, self.original_image.height() - self.ui.spinCropHeight.value())
        self.ui.spinCropX.setRange(0, max_x)
        self.ui.spinCropY.setRange(0, max_y)

    def update_crop_rect_position(self):
        if not self.original_image or self.original_image.isNull():
            return

        x = self.ui.spinCropX.value()
        y = self.ui.spinCropY.value()
        self.crop_rect_item.setPos(x, y)
        self.update_preview()

    def trigger_preview_update(self):
        self.preview_timer.start()

    def update_preview(self):
        self.update_preview_real()

    def update_preview_real(self):
        if not self.original_pil:
            return

        self.crop_rect_item.setVisible(False)
        processed_pil = self.build_processed_image()
        self.processed_image = pil_to_qimage(processed_pil)
        self.preview_image = pil_to_qimage(self.build_preview_image(processed_pil))
        self.pixmap_item.setPixmap(QPixmap.fromImage(self.preview_image))

        final_w = self.preview_image.width()
        final_h = self.preview_image.height()
        self.background_checker_item.setRect(0, 0, final_w, final_h)
        self.background_checker_item.setPos(0, 0)
        self.background_checker_item.setVisible(True)
        self.scene.setSceneRect(0, 0, final_w, final_h)
        self.update_preview_view_scale()

    def build_processed_image(self):
        img = self.original_pil.copy()
        img = self.apply_image_scale(img)

        # 2. AIカラー化適用
        if self.ui.chkColorizeEnable.isChecked():
            colorized = self.apply_ai_colorization(pil_to_qimage(img))
            img = qimage_to_pil(colorized) or img

        # 3. ぼかし適用
        if self.ui.chkBlurEnable.isChecked():
            radius = self.ui.spinBlurRadius.value()
            threshold = self.ui.spinBlurThreshold.value()
            if radius > 1:
                img = selective_blur_cv2(img, radius, threshold)

        # 4. シャープネス適用
        if self.ui.chkSharpenEnable.isChecked():
            strength = self.ui.spinSharpenStrength.value()
            if strength > 0:
                img = sharpen_cv2(img, strength)

        # 4.5. エッジ強調適用
        if self.ui.chkEdgeEnable.isChecked() and HAS_CV2:
            method_map = {0: "Canny", 1: "Sobel", 2: "Laplacian"}
            method_name = method_map.get(self.ui.comboEdgeMethod.currentIndex(), "Canny")
            t1 = self.ui.spinEdgeThreshold1.value()
            t2 = self.ui.spinEdgeThreshold2.value()
            strength = self.ui.spinEdgeStrength.value()
            width = self.ui.spinEdgeWidth.value()
            smooth = self.ui.spinEdgeSmooth.value()
            img = edge_enhance_cv2(img, method_name, t1, t2, strength, self.edge_color, width, smooth)

        # 5. 背景削除適用
        if self.ui.chkRemoveBgEnable.isChecked():
            tolerance = self.ui.spinRemoveBgTolerance.value()
            feather = self.ui.spinRemoveBgFeather.value()
            if tolerance > 0:
                img = remove_background_cv2(img, self.remove_bg_key_color, tolerance, feather)

        return img

    def build_preview_image(self, img):
        pos = self.crop_rect_item.pos()
        rect = self.crop_rect_item.rect()

        x = int(max(0, min(pos.x(), self.original_pil.width - rect.width())))
        y = int(max(0, min(pos.y(), self.original_pil.height - rect.height())))
        w = int(rect.width())
        h = int(rect.height())

        img = self.apply_clip_window(img, x, y, w, h)

        # 6. マスク画像適用
        mask_index = self.ui.comboMaskImage.currentIndex()
        if mask_index > 0: # 0は「選択なし」
            mask_config = self.ui.comboMaskImage.itemData(mask_index)
            if mask_config:
                base_dir = os.path.dirname(__file__)
                mask_path = resolve_mask_image_path(base_dir, mask_config)
                if mask_path:
                    mask_img = load_pil_image(mask_path)
                    if not mask_img:
                        return img
                    img = apply_alpha_mask_pil(
                        img,
                        mask_img,
                        self.ui.spinMaskScale.value(),
                        self.ui.spinMaskX.value(),
                        self.ui.spinMaskY.value(),
                        self.ui.chkCropMaskOutside.isChecked(),
                    )

        return img

    def apply_clip_window(self, img, x: int, y: int, width: int, height: int):
        scale_percent = self.ui.spinScale.value()
        scale = scale_percent / 100.0
        left = int(round(x * scale))
        top = int(round(y * scale))
        right = int(round((x + width) * scale))
        bottom = int(round((y + height) * scale))

        left = max(0, min(left, img.width))
        top = max(0, min(top, img.height))
        right = max(left + 1, min(right, img.width))
        bottom = max(top + 1, min(bottom, img.height))
        return img.crop((left, top, right, bottom))

    def apply_image_scale(self, img):
        scale_percent = self.ui.spinScale.value()
        if scale_percent == 100:
            return img

        scaled_w = max(1, int(round(img.width * scale_percent / 100.0)))
        scaled_h = max(1, int(round(img.height * scale_percent / 100.0)))
        interpolation = self.ui.comboInterpolation.currentData() or "bilinear"

        return resize_pil(img, scaled_w, scaled_h, interpolation)

    def on_zoom_fit_toggled(self, checked: bool):
        self.ui.sliderZoom.setEnabled(not checked)
        self.ui.spinZoom.setEnabled(not checked)
        self.update_preview_view_scale()

    def update_preview_view_scale(self):
        if not self.scene.sceneRect().isValid():
            return

        view = self.ui.graphicsViewPreview
        view.resetTransform()
        if self.ui.chkZoomFit.isChecked():
            view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        else:
            zoom = self.ui.spinZoom.value() / 100.0
            view.scale(zoom, zoom)

    def eventFilter(self, watched, event):
        if watched == self.ui.graphicsViewPreview.viewport():
            if event.type() == QEvent.Type.Resize:
                if self.ui.chkZoomFit.isChecked():
                    QTimer.singleShot(0, self.update_preview_view_scale)
            
            elif event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    if self.ui.comboMaskImage.currentIndex() > 0:
                        self._dragging_mask = True
                        self._drag_start_pos = event.pos()
                        self._drag_start_mask_x = self.ui.spinMaskX.value()
                        self._drag_start_mask_y = self.ui.spinMaskY.value()
                        return True
                elif event.button() == Qt.MouseButton.MiddleButton:
                    self._panning_view = True
                    self._pan_start_pos = event.pos()
                    return True
                    
            elif event.type() == QEvent.Type.MouseMove:
                if getattr(self, "_dragging_mask", False):
                    start_scene = self.ui.graphicsViewPreview.mapToScene(self._drag_start_pos)
                    current_scene = self.ui.graphicsViewPreview.mapToScene(event.pos())
                    delta = current_scene - start_scene
                    
                    new_x = self._drag_start_mask_x + int(round(delta.x()))
                    new_y = self._drag_start_mask_y + int(round(delta.y()))
                    
                    self.ui.spinMaskX.setValue(new_x)
                    self.ui.spinMaskY.setValue(new_y)
                    return True
                    
                elif getattr(self, "_panning_view", False):
                    delta = event.pos() - self._pan_start_pos
                    scrollbar_h = self.ui.graphicsViewPreview.horizontalScrollBar()
                    scrollbar_v = self.ui.graphicsViewPreview.verticalScrollBar()
                    
                    scrollbar_h.setValue(scrollbar_h.value() - delta.x())
                    scrollbar_v.setValue(scrollbar_v.value() - delta.y())
                    
                    self._pan_start_pos = event.pos()
                    return True
                    
            elif event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton and getattr(self, "_dragging_mask", False):
                    self._dragging_mask = False
                    return True
                elif event.button() == Qt.MouseButton.MiddleButton and getattr(self, "_panning_view", False):
                    self._panning_view = False
                    return True

        return super().eventFilter(watched, event)

    def on_blur_enable_toggled(self, checked: bool):
        if checked and not HAS_CV2:
            QMessageBox.warning(
                self,
                "機能制限",
                "選択的ガウスぼかし機能を利用するには OpenCV (cv2) が必要です。\n"
                "Python環境に opencv-python をインストールしてください。"
            )
            self.ui.chkBlurEnable.blockSignals(True)
            self.ui.chkBlurEnable.setChecked(False)
            self.ui.chkBlurEnable.blockSignals(False)
            return

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
        if checked:
            if not HAS_CV2:
                QMessageBox.warning(
                    self,
                    "機能制限",
                    "AI自動カラー化機能を利用するには OpenCV (cv2) が必要です。\n"
                    "Python環境に opencv-python をインストールしてください。"
                )
                self.ui.chkColorizeEnable.blockSignals(True)
                self.ui.chkColorizeEnable.setChecked(False)
                self.ui.chkColorizeEnable.blockSignals(False)
                return
            
            # モデルファイルの存在チェック（不足していればダウンロードを促す）
            if not self.ensure_model_files():
                self.ui.chkColorizeEnable.blockSignals(True)
                self.ui.chkColorizeEnable.setChecked(False)
                self.ui.chkColorizeEnable.blockSignals(False)
                return

        self.ui.sliderColorizeHue.setEnabled(checked)
        self.ui.spinColorizeHue.setEnabled(checked)
        self.ui.sliderColorizeSaturation.setEnabled(checked)
        self.ui.spinColorizeSaturation.setEnabled(checked)
        self.ui.sliderColorizeLightness.setEnabled(checked)
        self.ui.spinColorizeLightness.setEnabled(checked)
        self.trigger_preview_update()

    def on_edge_enable_toggled(self, checked: bool):
        if checked and not HAS_CV2:
            QMessageBox.warning(
                self,
                "機能制限",
                "エッジ強調機能を利用するには OpenCV (cv2) が必要です。\n"
                "Python環境に opencv-python をインストールしてください。"
            )
            self.ui.chkEdgeEnable.blockSignals(True)
            self.ui.chkEdgeEnable.setChecked(False)
            self.ui.chkEdgeEnable.blockSignals(False)
            return

        self.ui.comboEdgeMethod.setEnabled(checked)
        self.ui.sliderEdgeThreshold1.setEnabled(checked)
        self.ui.spinEdgeThreshold1.setEnabled(checked)
        self.ui.sliderEdgeThreshold2.setEnabled(checked)
        self.ui.spinEdgeThreshold2.setEnabled(checked)
        self.ui.sliderEdgeStrength.setEnabled(checked)
        self.ui.spinEdgeStrength.setEnabled(checked)
        self.ui.sliderEdgeWidth.setEnabled(checked)
        self.ui.spinEdgeWidth.setEnabled(checked)
        self.ui.sliderEdgeSmooth.setEnabled(checked)
        self.ui.spinEdgeSmooth.setEnabled(checked)
        self.ui.btnSelectEdgeColor.setEnabled(checked)
        self.trigger_preview_update()

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

    def select_edge_color(self):
        color = QColorDialog.getColor(self.edge_color, self, "エッジの色を選択")
        if color.isValid():
            self.edge_color = color
            self.update_edge_color_preview()
            self.trigger_preview_update()

    def update_edge_color_preview(self):
        if hasattr(self.ui, "frameEdgeColor"):
            color = self.edge_color
            if color:
                self.ui.frameEdgeColor.setStyleSheet(
                    f"background-color: rgb({color.red()}, {color.green()}, {color.blue()}); border: 1px solid palette(mid);"
                )
            else:
                self.ui.frameEdgeColor.setStyleSheet(
                    "background-color: transparent; border: 1px dashed palette(mid);"
                )

    def on_accept(self):
        self.update_preview_real()
        self.filter_settings = self.export_filter_settings()
        self.saved_png_path = None
        self.accept()

    def export_filter_settings(self) -> dict:
        color = self.remove_bg_key_color
        return {
            "source_path": self.image_path,
            "clip": {
                "x": self.ui.spinCropX.value(),
                "y": self.ui.spinCropY.value(),
                "width": self.ui.spinCropWidth.value(),
                "height": self.ui.spinCropHeight.value(),
            },
            "scale": {
                "percent": self.ui.spinScale.value(),
                "interpolation": self.ui.comboInterpolation.currentData() or "bilinear",
            },
            "mask": {
                "id": self.current_mask_id(),
                "scale": self.ui.spinMaskScale.value(),
                "x": self.ui.spinMaskX.value(),
                "y": self.ui.spinMaskY.value(),
                "cropOutside": self.ui.chkCropMaskOutside.isChecked(),
            },
            "filters": {
                "blur": {
                    "enabled": self.ui.chkBlurEnable.isChecked(),
                    "radius": self.ui.spinBlurRadius.value(),
                    "threshold": self.ui.spinBlurThreshold.value(),
                },
                "sharpen": {
                    "enabled": self.ui.chkSharpenEnable.isChecked(),
                    "strength": self.ui.spinSharpenStrength.value(),
                },
                "edge": {
                    "enabled": self.ui.chkEdgeEnable.isChecked(),
                    "method": self.ui.comboEdgeMethod.currentIndex(),
                    "threshold1": self.ui.spinEdgeThreshold1.value(),
                    "threshold2": self.ui.spinEdgeThreshold2.value(),
                    "strength": self.ui.spinEdgeStrength.value(),
                    "color": [self.edge_color.red(), self.edge_color.green(), self.edge_color.blue()] if self.edge_color else [255, 255, 255],
                    "width": self.ui.spinEdgeWidth.value(),
                    "smooth": self.ui.spinEdgeSmooth.value(),
                },
                "chromaKey": {
                    "enabled": self.ui.chkRemoveBgEnable.isChecked(),
                    "color": [color.red(), color.green(), color.blue()] if color else None,
                    "tolerance": self.ui.spinRemoveBgTolerance.value(),
                    "feather": self.ui.spinRemoveBgFeather.value(),
                },
                "colorize": {
                    "enabled": self.ui.chkColorizeEnable.isChecked(),
                    "model": self.ui.comboColorizeModel.currentData(),
                    "hue": self.ui.spinColorizeHue.value(),
                    "saturation": self.ui.spinColorizeSaturation.value(),
                    "lightness": self.ui.spinColorizeLightness.value(),
                },
            },
        }

    def current_mask_id(self) -> str | None:
        mask_config = self.ui.comboMaskImage.currentData()
        if isinstance(mask_config, dict):
            return mask_config.get("id")
        return None

    def apply_filter_settings(self, settings: dict):
        clip = settings.get("clip", {})
        self.ui.spinCropWidth.setValue(clip.get("width", self.ui.spinCropWidth.value()))
        self.ui.spinCropHeight.setValue(clip.get("height", self.ui.spinCropHeight.value()))
        self.ui.spinCropX.setValue(clip.get("x", 0))
        self.ui.spinCropY.setValue(clip.get("y", 0))

        scale = settings.get("scale", {})
        self.ui.spinScale.setValue(scale.get("percent", self.ui.spinScale.value()))
        interpolation = scale.get("interpolation")
        for i in range(self.ui.comboInterpolation.count()):
            if self.ui.comboInterpolation.itemData(i) == interpolation:
                self.ui.comboInterpolation.setCurrentIndex(i)
                break

        mask = settings.get("mask", {})
        mask_id = mask.get("id")
        self.ui.comboMaskImage.blockSignals(True)
        for i in range(self.ui.comboMaskImage.count()):
            mask_config = self.ui.comboMaskImage.itemData(i)
            if (not mask_id and not mask_config) or (isinstance(mask_config, dict) and mask_config.get("id") == mask_id):
                self.ui.comboMaskImage.setCurrentIndex(i)
                break
        self.ui.comboMaskImage.blockSignals(False)
        self.ui.spinMaskScale.setValue(mask.get("scale", self.ui.spinMaskScale.value()))
        self.ui.spinMaskX.setValue(mask.get("x", self.ui.spinMaskX.value()))
        self.ui.spinMaskY.setValue(mask.get("y", self.ui.spinMaskY.value()))
        self.ui.chkCropMaskOutside.setChecked(mask.get("cropOutside", self.ui.chkCropMaskOutside.isChecked()))

        filters = settings.get("filters", {})
        blur = filters.get("blur", {})
        colorize = filters.get("colorize", {})
        edge_filter = filters.get("edge", {})

        blur_enabled = blur.get("enabled", False)
        colorize_enabled = colorize.get("enabled", False)
        edge_enabled = edge_filter.get("enabled", False)

        # OpenCV不在時にロードされたOpenCV依存機能の一括警告判定
        if not HAS_CV2:
            unavailable_features = []
            if blur_enabled:
                unavailable_features.append("選択的ガウスぼかし")
                blur_enabled = False
            if colorize_enabled:
                unavailable_features.append("AI自動カラー化")
                colorize_enabled = False
            if edge_enabled:
                unavailable_features.append("エッジ強調")
                edge_enabled = False

            if unavailable_features:
                QMessageBox.warning(
                    self,
                    "機能制限",
                    "ロードされた設定には以下のOpenCV依存機能が含まれていますが、\n"
                    "現在の環境には OpenCV がインストールされていないため適用できません。\n\n"
                    f"対象機能: {', '.join(unavailable_features)}"
                )

        self.ui.chkBlurEnable.setChecked(blur_enabled)
        self.ui.spinBlurRadius.setValue(blur.get("radius", self.ui.spinBlurRadius.value()))
        self.ui.spinBlurThreshold.setValue(blur.get("threshold", self.ui.spinBlurThreshold.value()))

        sharpen_filter = filters.get("sharpen", {})
        self.ui.chkSharpenEnable.setChecked(sharpen_filter.get("enabled", False))
        self.ui.spinSharpenStrength.setValue(sharpen_filter.get("strength", self.ui.spinSharpenStrength.value()))

        chroma_key = filters.get("chromaKey", {})
        self.ui.chkRemoveBgEnable.setChecked(chroma_key.get("enabled", False))
        color = chroma_key.get("color")
        self.remove_bg_key_color = QColor(*color) if color else None
        self.ui.spinRemoveBgTolerance.setValue(chroma_key.get("tolerance", self.ui.spinRemoveBgTolerance.value()))
        self.ui.spinRemoveBgFeather.setValue(chroma_key.get("feather", self.ui.spinRemoveBgFeather.value()))
        self.update_key_color_preview()

        self.ui.chkColorizeEnable.setChecked(colorize_enabled)
        model_id = colorize.get("model")
        for i in range(self.ui.comboColorizeModel.count()):
            if self.ui.comboColorizeModel.itemData(i) == model_id:
                self.ui.comboColorizeModel.setCurrentIndex(i)
                self.on_colorize_model_changed(i)
                break
        self.ui.spinColorizeHue.setValue(colorize.get("hue", self.ui.spinColorizeHue.value()))
        self.ui.spinColorizeSaturation.setValue(colorize.get("saturation", self.ui.spinColorizeSaturation.value()))
        self.ui.spinColorizeLightness.setValue(colorize.get("lightness", self.ui.spinColorizeLightness.value()))

        self.ui.chkEdgeEnable.setChecked(edge_enabled)
        self.ui.comboEdgeMethod.setCurrentIndex(edge_filter.get("method", 0))
        self.ui.spinEdgeThreshold1.setValue(edge_filter.get("threshold1", 50))
        self.ui.spinEdgeThreshold2.setValue(edge_filter.get("threshold2", 150))
        self.ui.spinEdgeStrength.setValue(edge_filter.get("strength", 50))
        self.ui.spinEdgeWidth.setValue(edge_filter.get("width", 1))
        self.ui.spinEdgeSmooth.setValue(edge_filter.get("smooth", 1))
        color_list = edge_filter.get("color", [255, 255, 255])
        self.edge_color = QColor(*color_list)
        self.update_edge_color_preview()

        self.update_preview_real()

    @classmethod
    def render_preview_from_settings(cls, image_path: str, settings: dict, parent=None) -> QImage | None:
        dialog = cls(image_path, parent)
        dialog.apply_filter_settings(settings)
        return dialog.preview_image

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
            
        self.ui.labelColorizeModel.setEnabled(True)
        self.ui.comboColorizeModel.setEnabled(True)
        self.ui.comboColorizeModel.activated.connect(self.on_colorize_model_changed)
        
        # 初期状態のモデルに応じたページ切り替え
        if self.active_model and self.active_model.get_id() == "eccv2016":
            self.ui.stackedColorize.setCurrentWidget(self.ui.pageColorizeEccv2016)
        else:
            self.ui.stackedColorize.setCurrentWidget(self.ui.pageColorizeNone)

    def on_colorize_model_changed(self, index: int):
        selected_id = self.ui.comboColorizeModel.itemData(index)
        for model in self.all_models:
            if model.get_id() == selected_id:
                self.active_model = model
                break
                
        # モデルに連動して色塗り調整ページの表示を切り替える
        if hasattr(self, "active_model") and self.active_model and self.active_model.get_id() == "eccv2016":
            self.ui.stackedColorize.setCurrentWidget(self.ui.pageColorizeEccv2016)
        else:
            self.ui.stackedColorize.setCurrentWidget(self.ui.pageColorizeNone)
            
        if self.ensure_model_files() and self.ui.chkColorizeEnable.isChecked():
            self.trigger_preview_update()

    def ensure_model_files(self) -> bool:
        if not hasattr(self, "active_model") or self.active_model is None:
            return True
            
        base_dir = os.path.dirname(__file__)
        models_dir = self.active_model.get_models_dir(base_dir)
        status = inspect_model_assets(self.active_model, models_dir)
        missing_files = list(status.missing_files)
        updated_files = list(status.updated_files)
                    
        if updated_files:
            reply = QMessageBox.question(
                self,
                "AIモデルファイルの更新検出",
                f"新しいバージョンのモデルファイルが検出されました：\n{', '.join(updated_files)}\n\n最新バージョンをダウンロードして更新しますか？\n（※「いいえ」を選択した場合は、現在の古いモデルを使い続けます）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                remove_model_asset_ids(self.active_model, models_dir, updated_files)
                missing_files.extend(updated_files)

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
        
        def download_progress(filename: str, downloaded: int, total_size: int):
            if progress.wasCanceled():
                raise Exception("Download canceled by user")
            progress.setLabelText(f"{filename} をダウンロード中...")
            if total_size > 0:
                percent = int(downloaded * 100 / total_size)
                progress.setValue(min(100, percent))
            else:
                progress.setValue(0)
            QCoreApplication.processEvents()
                
        try:
            download_model_assets(self.active_model, models_dir, missing_files, download_progress)
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
                models_dir = self.active_model.get_models_dir(base_dir)
                print(f"[AI Colorize] Dynamically loading network for model: {self.active_model.get_id()}")
                self.active_model.load_network(models_dir)
                
            result_bgr = self.active_model.predict(bgr)
            
            h_shift = self.ui.sliderColorizeHue.value()
            s_shift = self.ui.sliderColorizeSaturation.value()
            l_shift = self.ui.sliderColorizeLightness.value()
            
            if h_shift != 0 or s_shift != 0 or l_shift != 0:
                result_bgr = adjust_hsl(result_bgr, h_shift, s_shift, l_shift)
            
            result_rgba = cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGBA)
            rgba_contiguous = np.ascontiguousarray(result_rgba)
            
            qimg = QImage(rgba_contiguous.data, width, height, QImage.Format.Format_RGBA8888)
            return qimg.copy()
            
        except Exception as e:
            print(f"[AI Colorize] Inference error: {e}")
            return img

    def keyPressEvent(self, event):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton
        
        # Enterキーによる意図しないクローズを防ぐ
        # フォーカスがボタン（例: OKボタン）にある場合は通常通り処理する
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not isinstance(self.focusWidget(), QPushButton):
                return
                
        super().keyPressEvent(event)
