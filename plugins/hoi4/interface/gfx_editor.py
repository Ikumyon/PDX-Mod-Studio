from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any, Optional
import core.api
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QStackedWidget, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox, QComboBox, QGroupBox,
    QPushButton
)
from plugins.hoi4.interface.image_tools_dialog import ImageToolsDialog
from plugins.hoi4.script_parser import (
    AssignmentNode, ObjectNode, ScalarNode, ParsedEntity
)
from plugins.hoi4.base_editor import (
    BaseDocument, BaseEditorController, BaseParsedEntity, BaseParser,
    set_line, set_plain, set_spin, set_checked, set_combo,
    prop_text, prop_bool, block_text
)

TYPE_TO_PAGE = {
    "spriteType": 0,
    "frameAnimatedSpriteType": 1,
    "progressbartype": 2,
    "corneredTileSpriteType": 3,
    "maskedShieldType": 4,
    "bitmapfont": 5,
    "bitmapfont_override": 6,
    "animatedmaptext": 7,
}

class ParsedGfx(BaseParsedEntity):
    pass

@dataclass
class GfxDocument(BaseDocument):
    gfx_items: list[ParsedGfx] = field(default_factory=list)

class GfxParser(BaseParser):
    document_class = GfxDocument
    entity_class = ParsedGfx
    collection_attr = "gfx_items"
    project_subdir = "interface"
    progress_label = "Parsing GFX files"
    cache_key = "gfx_items"

    def __init__(self):
        base_dir = os.path.dirname(__file__)
        schema_path = os.path.join(base_dir, "gfx_schema.json")
        super().__init__(schema_path)

    def parse_project(self, project_path: str) -> list[ParsedGfx]:
        return super().parse_project(project_path)

# ブレンドモードの表示名と内部値のマッピング
BLEND_MODE_MAP = {
    "加算 (add)": "add",
    "乗算 (multiply)": "multiply",
    "オーバーレイ (overlay)": "overlay"
}

# 逆引き用
BLEND_MODE_REV_MAP = {v: k for k, v in BLEND_MODE_MAP.items()}



class GfxEditorController(BaseEditorController):
    ELEMENT_ID = "interface"
    DEFAULT_FORMAT_FILE = "gfx_format.json"

    def __init__(self, widget, file_path: str, content: str):
        super().__init__(widget, file_path, content)
        self.gfx_items: list[ParsedGfx] = []
        self.parser = GfxParser()
        
        # UIウィジェットの参照
        self.list_gfx_nodes = None
        self.combo_gfx_type = None
        self.stacked_editor = None
        
        # ページ 0: spriteType
        self.edit_sprite_name = None
        self.edit_sprite_texture = None
        self.spin_sprite_frames = None
        self.edit_sprite_effect = None
        self.check_sprite_transparent = None
        self.check_sprite_lazy_load = None
        self.check_sprite_transparence_check = None
        
        self.group_sprite_anim = None
        self.edit_sprite_anim_mask = None
        self.edit_sprite_anim_texture = None
        self.spin_sprite_anim_rotation = None
        self.check_sprite_anim_looping = None
        self.spin_sprite_anim_time = None
        self.spin_sprite_anim_delay = None
        self.combo_sprite_anim_blend = None
        self.spin_sprite_anim_rot_x = None
        self.spin_sprite_anim_rot_y = None
        self.spin_sprite_anim_scale_x = None
        self.spin_sprite_anim_scale_y = None
        self.edit_sprite_anim_type = None
        
        # ページ 1: frameAnimatedSpriteType
        self.edit_frame_anim_name = None
        self.edit_frame_anim_texture = None
        self.spin_frame_anim_frames = None
        self.spin_frame_anim_rate = None
        self.edit_frame_anim_effect = None
        self.check_frame_anim_looping = None
        self.check_frame_anim_play = None
        self.spin_frame_anim_pause = None
        self.check_frame_anim_transparent = None
        
        # ページ 2: progressbartype
        self.edit_progress_name = None
        self.edit_progress_texture_one = None
        self.edit_progress_texture_two = None
        self.edit_progress_color_one = None
        self.edit_progress_color_two = None
        self.spin_progress_size_w = None
        self.spin_progress_size_h = None
        self.edit_progress_effect = None
        self.check_progress_horizontal = None
        self.spin_progress_steps = None
        
        # ページ 3: corneredTileSpriteType
        self.edit_cornered_name = None
        self.edit_cornered_texture = None
        self.spin_cornered_size_w = None
        self.spin_cornered_size_h = None
        self.spin_cornered_border_x = None
        self.spin_cornered_border_y = None
        self.edit_cornered_effect = None
        self.check_cornered_transparent = None
        self.check_cornered_tiling_center = None
        
        # ページ 4: maskedShieldType
        self.edit_shield_name = None
        self.edit_shield_texture = None
        self.edit_shield_mask = None
        self.edit_shield_effect = None
        
        # ページ 5: bitmapfont
        self.edit_font_name = None
        self.edit_font_path = None
        self.edit_font_color = None
        self.spin_font_cursor_x = None
        self.spin_font_cursor_y = None
        
        # ページ 6: bitmapfont_override
        self.edit_override_font = None
        self.combo_override_language = None
        self.edit_override_font_path = None
        
        # ページ 7: animatedmaptext
        self.edit_map_text_name = None
        self.edit_map_text_font = None
        self.spin_map_text_speed = None
        self.spin_map_text_pos_x = None
        self.spin_map_text_pos_y = None
        self.spin_map_text_size_w = None
        self.spin_map_text_size_h = None

    def bind(self):
        # 共通
        self.list_gfx_nodes = self.find(QTreeWidget, "listGfxNodes")
        self.combo_gfx_type = self.find(QComboBox, "comboGfxType")
        self.stacked_editor = self.find(QStackedWidget, "stackedEditor")
        
        # ページ 0
        self.edit_sprite_name = self.find(QLineEdit, "editSpriteName")
        self.edit_sprite_texture = self.find(QLineEdit, "editSpriteTexture")
        self.spin_sprite_frames = self.find(QSpinBox, "spinSpriteFrames")
        self.edit_sprite_effect = self.find(QLineEdit, "editSpriteEffect")
        self.check_sprite_transparent = self.find(QCheckBox, "checkSpriteTransparent")
        self.check_sprite_lazy_load = self.find(QCheckBox, "checkSpriteLazyLoad")
        self.check_sprite_transparence_check = self.find(QCheckBox, "checkSpriteTransparenceCheck")
        
        self.group_sprite_anim = self.find(QGroupBox, "groupSpriteAnim")
        self.edit_sprite_anim_mask = self.find(QLineEdit, "editSpriteAnimMask")
        self.edit_sprite_anim_texture = self.find(QLineEdit, "editSpriteAnimTexture")
        self.spin_sprite_anim_rotation = self.find(QDoubleSpinBox, "spinSpriteAnimRotation")
        self.check_sprite_anim_looping = self.find(QCheckBox, "checkSpriteAnimLooping")
        self.spin_sprite_anim_time = self.find(QDoubleSpinBox, "spinSpriteAnimTime")
        self.spin_sprite_anim_delay = self.find(QDoubleSpinBox, "spinSpriteAnimDelay")
        self.combo_sprite_anim_blend = self.find(QComboBox, "comboSpriteAnimBlend")
        self.spin_sprite_anim_rot_x = self.find(QDoubleSpinBox, "spinSpriteAnimRotX")
        self.spin_sprite_anim_rot_y = self.find(QDoubleSpinBox, "spinSpriteAnimRotY")
        self.spin_sprite_anim_scale_x = self.find(QDoubleSpinBox, "spinSpriteAnimScaleX")
        self.spin_sprite_anim_scale_y = self.find(QDoubleSpinBox, "spinSpriteAnimScaleY")
        self.edit_sprite_anim_type = self.find(QLineEdit, "editSpriteAnimType")
        
        # ページ 1
        self.edit_frame_anim_name = self.find(QLineEdit, "editFrameAnimName")
        self.edit_frame_anim_texture = self.find(QLineEdit, "editFrameAnimTexture")
        self.spin_frame_anim_frames = self.find(QSpinBox, "spinFrameAnimFrames")
        self.spin_frame_anim_rate = self.find(QDoubleSpinBox, "spinFrameAnimRate")
        self.edit_frame_anim_effect = self.find(QLineEdit, "editFrameAnimEffect")
        self.check_frame_anim_looping = self.find(QCheckBox, "checkFrameAnimLooping")
        self.check_frame_anim_play = self.find(QCheckBox, "checkFrameAnimPlay")
        self.spin_frame_anim_pause = self.find(QDoubleSpinBox, "spinFrameAnimPause")
        self.check_frame_anim_transparent = self.find(QCheckBox, "checkFrameAnimTransparent")
        
        # ページ 2
        self.edit_progress_name = self.find(QLineEdit, "editProgressName")
        self.edit_progress_texture_one = self.find(QLineEdit, "editProgressTextureOne")
        self.edit_progress_texture_two = self.find(QLineEdit, "editProgressTextureTwo")
        self.edit_progress_color_one = self.find(QLineEdit, "editProgressColorOne")
        self.edit_progress_color_two = self.find(QLineEdit, "editProgressColorTwo")
        self.spin_progress_size_w = self.find(QSpinBox, "spinProgressSizeW")
        self.spin_progress_size_h = self.find(QSpinBox, "spinProgressSizeH")
        self.edit_progress_effect = self.find(QLineEdit, "editProgressEffect")
        self.check_progress_horizontal = self.find(QCheckBox, "checkProgressHorizontal")
        self.spin_progress_steps = self.find(QSpinBox, "spinProgressSteps")
        
        # ページ 3
        self.edit_cornered_name = self.find(QLineEdit, "editCorneredName")
        self.edit_cornered_texture = self.find(QLineEdit, "editCorneredTexture")
        self.spin_cornered_size_w = self.find(QSpinBox, "spinCorneredSizeW")
        self.spin_cornered_size_h = self.find(QSpinBox, "spinCorneredSizeH")
        self.spin_cornered_border_x = self.find(QSpinBox, "spinCorneredBorderX")
        self.spin_cornered_border_y = self.find(QSpinBox, "spinCorneredBorderY")
        self.edit_cornered_effect = self.find(QLineEdit, "editCorneredEffect")
        self.check_cornered_transparent = self.find(QCheckBox, "checkCorneredTransparent")
        self.check_cornered_tiling_center = self.find(QCheckBox, "checkCorneredTilingCenter")
        
        # ページ 4
        self.edit_shield_name = self.find(QLineEdit, "editShieldName")
        self.edit_shield_texture = self.find(QLineEdit, "editShieldTexture")
        self.edit_shield_mask = self.find(QLineEdit, "editShieldMask")
        self.edit_shield_effect = self.find(QLineEdit, "editShieldEffect")
        
        # ページ 5
        self.edit_font_name = self.find(QLineEdit, "editFontName")
        self.edit_font_path = self.find(QLineEdit, "editFontPath")
        self.edit_font_color = self.find(QLineEdit, "editFontColor")
        self.spin_font_cursor_x = self.find(QSpinBox, "spinFontCursorX")
        self.spin_font_cursor_y = self.find(QSpinBox, "spinFontCursorY")
        
        # ページ 6
        self.edit_override_font = self.find(QLineEdit, "editOverrideFont")
        self.combo_override_language = self.find(QComboBox, "comboOverrideLanguage")
        self.edit_override_font_path = self.find(QLineEdit, "editOverrideFontPath")
        
        # ページ 7
        self.edit_map_text_name = self.find(QLineEdit, "editMapTextName")
        self.edit_map_text_font = self.find(QLineEdit, "editMapTextFont")
        self.spin_map_text_speed = self.find(QDoubleSpinBox, "spinMapTextSpeed")
        self.spin_map_text_pos_x = self.find(QDoubleSpinBox, "spinMapTextPosX")
        self.spin_map_text_pos_y = self.find(QDoubleSpinBox, "spinMapTextPosY")
        self.spin_map_text_size_w = self.find(QDoubleSpinBox, "spinMapTextSizeW")
        self.spin_map_text_size_h = self.find(QDoubleSpinBox, "spinMapTextSizeH")

        # ----------------------------------------------------
        # 変更イベントのシグナルバインド
        # ----------------------------------------------------
        # ページ 0
        self.connect_scalar(self.edit_sprite_name, "name")
        self.connect_scalar(self.edit_sprite_texture, "texturefile")
        self.connect_spin(self.spin_sprite_frames, "noOfFrames")
        self.connect_scalar(self.edit_sprite_effect, "effectFile")
        self.connect_bool(self.check_sprite_transparent, "allwaystransparent")
        self.connect_bool(self.check_sprite_lazy_load, "legacy_lazy_load")
        self.connect_bool(self.check_sprite_transparence_check, "transparencecheck")
        
        if self.edit_sprite_anim_mask:
            self.edit_sprite_anim_mask.editingFinished.connect(lambda: self.update_anim_property("animationmaskfile", self.edit_sprite_anim_mask.text()))
        if self.edit_sprite_anim_texture:
            self.edit_sprite_anim_texture.editingFinished.connect(lambda: self.update_anim_property("animationtexturefile", self.edit_sprite_anim_texture.text()))
        if self.spin_sprite_anim_rotation:
            self.spin_sprite_anim_rotation.valueChanged.connect(lambda val: self.update_anim_property("animationrotation", str(val)))
        if self.check_sprite_anim_looping:
            self.check_sprite_anim_looping.toggled.connect(lambda checked: self.update_anim_property("animationlooping", "yes" if checked else "no"))
        if self.spin_sprite_anim_time:
            self.spin_sprite_anim_time.valueChanged.connect(lambda val: self.update_anim_property("animationtime", str(val)))
        if self.spin_sprite_anim_delay:
            self.spin_sprite_anim_delay.valueChanged.connect(lambda val: self.update_anim_property("animationdelay", str(val)))
        if self.combo_sprite_anim_blend:
            # シグナル接続（選択された日本語（英語）表示テキストに対応する英語キーを書き戻す）
            self.combo_sprite_anim_blend.currentIndexChanged.connect(
                lambda: self.update_anim_property(
                    "animationblendmode", 
                    BLEND_MODE_MAP.get(self.combo_sprite_anim_blend.currentText(), "add")
                )
            )
            
        if self.spin_sprite_anim_rot_x or self.spin_sprite_anim_rot_y:
            def on_anim_rot_changed():
                x = self.spin_sprite_anim_rot_x.value() if self.spin_sprite_anim_rot_x else 0.0
                y = self.spin_sprite_anim_rot_y.value() if self.spin_sprite_anim_rot_y else 0.0
                self.update_anim_property("animationrotationoffset", "", is_vector=True, x_val=x, y_val=y)
            if self.spin_sprite_anim_rot_x: self.spin_sprite_anim_rot_x.valueChanged.connect(on_anim_rot_changed)
            if self.spin_sprite_anim_rot_y: self.spin_sprite_anim_rot_y.valueChanged.connect(on_anim_rot_changed)
            
        if self.spin_sprite_anim_scale_x or self.spin_sprite_anim_scale_y:
            def on_anim_scale_changed():
                x = self.spin_sprite_anim_scale_x.value() if self.spin_sprite_anim_scale_x else 1.0
                y = self.spin_sprite_anim_scale_y.value() if self.spin_sprite_anim_scale_y else 1.0
                self.update_anim_property("animationtexturescale", "", is_vector=True, x_val=x, y_val=y)
            if self.spin_sprite_anim_scale_x: self.spin_sprite_anim_scale_x.valueChanged.connect(on_anim_scale_changed)
            if self.spin_sprite_anim_scale_y: self.spin_sprite_anim_scale_y.valueChanged.connect(on_anim_scale_changed)
            
        if self.edit_sprite_anim_type:
            self.edit_sprite_anim_type.editingFinished.connect(lambda: self.update_anim_property("animationtype", self.edit_sprite_anim_type.text()))
            
        # ページ 1
        self.connect_scalar(self.edit_frame_anim_name, "name")
        self.connect_scalar(self.edit_frame_anim_texture, "texturefile")
        self.connect_spin(self.spin_frame_anim_frames, "noOfFrames")
        if self.spin_frame_anim_rate:
            self.spin_frame_anim_rate.valueChanged.connect(lambda val: self.replace_property("animation_rate_fps", str(val)))
        self.connect_scalar(self.edit_frame_anim_effect, "effectFile")
        self.connect_bool(self.check_frame_anim_looping, "looping")
        self.connect_bool(self.check_frame_anim_play, "play_on_show")
        if self.spin_frame_anim_pause:
            self.spin_frame_anim_pause.valueChanged.connect(lambda val: self.replace_property("pause_on_loop", str(val)))
        self.connect_bool(self.check_frame_anim_transparent, "allwaystransparent")
        
        # ページ 2
        self.connect_scalar(self.edit_progress_name, "name")
        self.connect_scalar(self.edit_progress_texture_one, "textureFile1")
        self.connect_scalar(self.edit_progress_texture_two, "textureFile2")
        self.connect_scalar(self.edit_progress_effect, "effectFile")
        self.connect_bool(self.check_progress_horizontal, "horizontal")
        self.connect_spin(self.spin_progress_steps, "steps")
        
        if self.edit_progress_color_one:
            self.edit_progress_color_one.editingFinished.connect(lambda: self.update_color_property("color", self.edit_progress_color_one.text()))
        if self.edit_progress_color_two:
            self.edit_progress_color_two.editingFinished.connect(lambda: self.update_color_property("colortwo", self.edit_progress_color_two.text()))
            
        if self.spin_progress_size_w or self.spin_progress_size_h:
            def on_progress_size_changed():
                w = self.spin_progress_size_w.value() if self.spin_progress_size_w else 0
                h = self.spin_progress_size_h.value() if self.spin_progress_size_h else 0
                self.update_vector_property("size", w, h)
            if self.spin_progress_size_w: self.spin_progress_size_w.valueChanged.connect(on_progress_size_changed)
            if self.spin_progress_size_h: self.spin_progress_size_h.valueChanged.connect(on_progress_size_changed)
            
        # ページ 3
        self.connect_scalar(self.edit_cornered_name, "name")
        self.connect_scalar(self.edit_cornered_texture, "texturefile")
        self.connect_scalar(self.edit_cornered_effect, "effectFile")
        self.connect_bool(self.check_cornered_transparent, "allwaystransparent")
        self.connect_bool(self.check_cornered_tiling_center, "tilingCenter")
        
        if self.spin_cornered_size_w or self.spin_cornered_size_h:
            def on_cornered_size_changed():
                w = self.spin_cornered_size_w.value() if self.spin_cornered_size_w else 0
                h = self.spin_cornered_size_h.value() if self.spin_cornered_size_h else 0
                self.update_vector_property("size", w, h)
            if self.spin_cornered_size_w: self.spin_cornered_size_w.valueChanged.connect(on_cornered_size_changed)
            if self.spin_cornered_size_h: self.spin_cornered_size_h.valueChanged.connect(on_cornered_size_changed)
            
        if self.spin_cornered_border_x or self.spin_cornered_border_y:
            def on_cornered_border_changed():
                x = self.spin_cornered_border_x.value() if self.spin_cornered_border_x else 0
                y = self.spin_cornered_border_y.value() if self.spin_cornered_border_y else 0
                self.update_vector_property("borderSize", x, y)
            if self.spin_cornered_border_x: self.spin_cornered_border_x.valueChanged.connect(on_cornered_border_changed)
            if self.spin_cornered_border_y: self.spin_cornered_border_y.valueChanged.connect(on_cornered_border_changed)
            
        # ページ 4
        self.connect_scalar(self.edit_shield_name, "name")
        self.connect_scalar(self.edit_shield_texture, "textureFile1")
        self.connect_scalar(self.edit_shield_mask, "textureFile2")
        self.connect_scalar(self.edit_shield_effect, "effectFile")
        
        # ページ 5
        self.connect_scalar(self.edit_font_name, "name")
        self.connect_scalar(self.edit_font_path, "path")
        self.connect_scalar(self.edit_font_color, "color")
        
        if self.spin_font_cursor_x or self.spin_font_cursor_y:
            def on_font_cursor_changed():
                x = self.spin_font_cursor_x.value() if self.spin_font_cursor_x else 0
                y = self.spin_font_cursor_y.value() if self.spin_font_cursor_y else 0
                self.update_vector_property("cursor_offset", x, y)
            if self.spin_font_cursor_x: self.spin_font_cursor_x.valueChanged.connect(on_font_cursor_changed)
            if self.spin_font_cursor_y: self.spin_font_cursor_y.valueChanged.connect(on_font_cursor_changed)
            
        # ページ 6
        self.connect_scalar(self.edit_override_font, "font")
        self.connect_combo(self.combo_override_language, "language")
        self.connect_scalar(self.edit_override_font_path, "path")
        
        # ページ 7
        self.connect_scalar(self.edit_map_text_name, "name")
        self.connect_scalar(self.edit_map_text_font, "font")
        if self.spin_map_text_speed:
            self.spin_map_text_speed.valueChanged.connect(lambda val: self.replace_property("speed", str(val)))
            
        if self.spin_map_text_pos_x or self.spin_map_text_pos_y:
            def on_map_text_pos_changed():
                x = self.spin_map_text_pos_x.value() if self.spin_map_text_pos_x else 0.0
                y = self.spin_map_text_pos_y.value() if self.spin_map_text_pos_y else 0.0
                self.update_vector_property("position", x, y)
            if self.spin_map_text_pos_x: self.spin_map_text_pos_x.valueChanged.connect(on_map_text_pos_changed)
            if self.spin_map_text_pos_y: self.spin_map_text_pos_y.valueChanged.connect(on_map_text_pos_changed)
            
        if self.spin_map_text_size_w or self.spin_map_text_size_h:
            def on_map_text_size_changed():
                w = self.spin_map_text_size_w.value() if self.spin_map_text_size_w else 0.0
                h = self.spin_map_text_size_h.value() if self.spin_map_text_size_h else 0.0
                self.update_vector_property("size", w, h)
            if self.spin_map_text_size_w: self.spin_map_text_size_w.valueChanged.connect(on_map_text_size_changed)
            if self.spin_map_text_size_h: self.spin_map_text_size_h.valueChanged.connect(on_map_text_size_changed)

        # シグナル
        if self.list_gfx_nodes:
            self.list_gfx_nodes.itemSelectionChanged.connect(self.on_selection_changed)
            
        # 画像編集ツールを開くボタンのバインド
        self.btn_open_image_tools = self.find(QPushButton, "btnOpenImageTools")
        if self.btn_open_image_tools:
            self.btn_open_image_tools.clicked.connect(self.open_image_tools)
            
        self.refresh()

    def open_image_tools(self):
        """画像編集ダイアログを表示する（表示のみ）"""
        dialog = ImageToolsDialog(self.widget)
        dialog.exec()

    def refresh(self):
        self.updating = True
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            self.gfx_items = doc.gfx_items
            
            if self.list_gfx_nodes:
                self.list_gfx_nodes.clear()
                for i, item in enumerate(self.gfx_items):
                    # 各ノードをリストに追加
                    tree_item = QTreeWidgetItem([item.id, item.node.key])
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, i)
                    self.list_gfx_nodes.addTopLevelItem(tree_item)
                
                if self.gfx_items:
                    self.set_current_index(0)
                else:
                    self.set_current_index(-1)
        finally:
            self.updating = False
            
        self.on_selection_changed()

    def refresh_on_edit(self, active_id):
        was_blocked = False
        if self.list_gfx_nodes:
            was_blocked = self.list_gfx_nodes.blockSignals(True)
            
        self.updating = True
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            self.gfx_items = doc.gfx_items
            
            if self.list_gfx_nodes:
                self.list_gfx_nodes.clear()
                select_idx = -1
                for i, item in enumerate(self.gfx_items):
                    tree_item = QTreeWidgetItem([item.id, item.node.key])
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, i)
                    self.list_gfx_nodes.addTopLevelItem(tree_item)
                    if item.id == active_id:
                        select_idx = i
                
                if select_idx >= 0:
                    self.set_current_index(select_idx)
                elif self.gfx_items:
                    self.set_current_index(0)
                else:
                    self.set_current_index(-1)
        finally:
            self.updating = False
            if self.list_gfx_nodes:
                self.list_gfx_nodes.blockSignals(was_blocked)

    def replace_property(self, property_name, replacement):
        if self.updating:
            return
        ach = self.current_gfx_item()
        if not ach:
            return
            
        text = self.widget.content
        assignment = ach.first(property_name)
        
        # 値の削除処理
        if not replacement:
            if assignment:
                start = assignment.range.start_offset
                end = assignment.range.end_offset
                while start > 0 and text[start-1] in " \t":
                    start -= 1
                if start > 0 and text[start-1] == "\n":
                    start -= 1
                self.widget.content = text[:start] + text[end:]
                self.refresh_on_edit(ach.id)
            return

        is_string_prop = property_name in {
            "name", "texturefile", "effectFile", "textureFile1", "textureFile2", 
            "path", "font", "animationmaskfile", "animationtexturefile", "animationtype",
            "animationblendmode"
        }
        
        if is_string_prop:
            if not (replacement.startswith('"') and replacement.endswith('"')):
                formatted_val = f'"{replacement}"'
            else:
                formatted_val = replacement
        else:
            formatted_val = replacement

        if assignment:
            # 更新
            value_range = assignment.value.range
            self.widget.content = text[:value_range.start_offset] + formatted_val + text[value_range.end_offset:]
        else:
            # 新規挿入
            insertion_offset = ach.node.value.close_range.start_offset if ach.node.value.close_range else ach.node.range.end_offset - 1
            new_prop = f"\t{property_name} = {formatted_val}\n"
            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]
            
        self.refresh_on_edit(ach.id)

    def update_vector_property(self, property_name, x, y):
        if self.updating:
            return
        ach = self.current_gfx_item()
        if not ach:
            return
            
        text = self.widget.content
        assignment = ach.first(property_name)
        
        x_str = str(int(x)) if isinstance(x, int) or x.is_integer() else str(x)
        y_str = str(int(y)) if isinstance(y, int) or y.is_integer() else str(y)
        formatted_val = f"{{ x = {x_str} y = {y_str} }}"
        
        if assignment:
            val_range = assignment.value.range
            self.widget.content = text[:val_range.start_offset] + formatted_val + text[val_range.end_offset:]
        else:
            insertion_offset = ach.node.value.close_range.start_offset if ach.node.value.close_range else ach.node.range.end_offset - 1
            new_prop = f"\t{property_name} = {formatted_val}\n"
            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]
            
        self.refresh_on_edit(ach.id)

    def update_color_property(self, property_name, color_str):
        if self.updating:
            return
        ach = self.current_gfx_item()
        if not ach:
            return
            
        color_str = color_str.strip()
        if not color_str:
            return
            
        text = self.widget.content
        assignment = ach.first(property_name)
        
        formatted_val = f"{{ {color_str} }}"
        
        if assignment:
            val_range = assignment.value.range
            self.widget.content = text[:val_range.start_offset] + formatted_val + text[val_range.end_offset:]
        else:
            insertion_offset = ach.node.value.close_range.start_offset if ach.node.value.close_range else ach.node.range.end_offset - 1
            new_prop = f"\t{property_name} = {formatted_val}\n"
            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]
            
        self.refresh_on_edit(ach.id)

    def update_anim_property(self, property_name, value, is_vector=False, x_val=None, y_val=None):
        if self.updating:
            return
        ach = self.current_gfx_item()
        if not ach:
            return
            
        text = self.widget.content
        anim_node = ach.first("animation")
        
        # 1. animationブロックが存在しない場合は、アセット末尾に空のanimationブロックを作成する
        if not anim_node or not isinstance(anim_node.value, ObjectNode):
            insertion_offset = ach.node.value.close_range.start_offset if ach.node.value.close_range else ach.node.range.end_offset - 1
            empty_anim = "\tanimation = {\n\t}\n"
            text = text[:insertion_offset] + empty_anim + text[insertion_offset:]
            self.widget.content = text
            
            # 再パースして最新の animation_node を取得
            doc = self.parser.parse_document(self.file_path, text)
            self.gfx_items = doc.gfx_items
            ach = self.gfx_items[self.current_gfx_index()]
            anim_node = ach.first("animation")
            
        if not anim_node or not isinstance(anim_node.value, ObjectNode):
            return
            
        # 2. 値のフォーマットを決定
        is_string_prop = property_name in {
            "animationmaskfile", "animationtexturefile", "animationtype", "animationblendmode"
        }
        
        if is_vector:
            x_str = str(int(x_val)) if isinstance(x_val, int) or x_val.is_integer() else str(x_val)
            y_str = str(int(y_val)) if isinstance(y_val, int) or y_val.is_integer() else str(y_val)
            formatted_val = f"{{ x = {x_str} y = {y_str} }}"
        elif is_string_prop:
            if not (value.startswith('"') and value.endswith('"')):
                formatted_val = f'"{value}"'
            else:
                formatted_val = value
        else:
            formatted_val = value

        assign = anim_node.value.first_assignment(property_name)
        
        if assign:
            val_range = assign.value.range
            self.widget.content = text[:val_range.start_offset] + formatted_val + text[val_range.end_offset:]
        else:
            anim_close_offset = anim_node.value.close_range.start_offset if anim_node.value.close_range else anim_node.value.range.end_offset - 1
            new_prop = f"\t\t{property_name} = {formatted_val}\n"
            self.widget.content = text[:anim_close_offset] + new_prop + text[anim_close_offset:]
            
        self.refresh_on_edit(ach.id)

    def on_save_triggered(self) -> bool:
        """本体からの保存要求時に呼ばれる。物理的なディスク保存を実行。"""
        if not self.file_path:
            return False
            
        try:
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(self.widget.content)
            return True
        except Exception as e:
            print(f"Failed to physically save GFX file {self.file_path}: {e}")
            return False

    def set_current_index(self, index: int):
        if self.list_gfx_nodes:
            if index >= 0 and index < self.list_gfx_nodes.topLevelItemCount():
                item = self.list_gfx_nodes.topLevelItem(index)
                self.list_gfx_nodes.setCurrentItem(item)
            else:
                self.list_gfx_nodes.setCurrentItem(None)

    def current_gfx_index(self) -> int:
        if self.list_gfx_nodes:
            item = self.list_gfx_nodes.currentItem()
            if item:
                val = item.data(0, Qt.ItemDataRole.UserRole)
                if val is not None:
                    return int(val)
        return -1

    def current_gfx_item(self) -> Optional[ParsedGfx]:
        idx = self.current_gfx_index()
        if 0 <= idx < len(self.gfx_items):
            return self.gfx_items[idx]
        return None

    def on_selection_changed(self):
        if self.updating:
            return
        ach = self.current_gfx_item()
        if ach:
            self.load_gfx_item(ach)

    def load_gfx_item(self, ach: ParsedGfx):
        self.updating = True
        try:
            typename = ach.node.key
            page_idx = TYPE_TO_PAGE.get(typename, 0)
            
            if self.combo_gfx_type:
                self.combo_gfx_type.setCurrentIndex(page_idx)
            if self.stacked_editor:
                self.stacked_editor.setCurrentIndex(page_idx)
                
            if page_idx == 0:
                self.load_sprite_type(ach)
            elif page_idx == 1:
                self.load_frame_animated(ach)
            elif page_idx == 2:
                self.load_progress_bar(ach)
            elif page_idx == 3:
                self.load_cornered_tile(ach)
            elif page_idx == 4:
                self.load_masked_shield(ach)
            elif page_idx == 5:
                self.load_bitmap_font(ach)
            elif page_idx == 6:
                self.load_font_override(ach)
            elif page_idx == 7:
                self.load_map_text(ach)
                
        finally:
            self.updating = False

    def load_sprite_type(self, ach: ParsedGfx):
        set_line(self.edit_sprite_name, prop_text(ach, "name"))
        set_line(self.edit_sprite_texture, prop_text(ach, "texturefile"))
        set_spin(self.spin_sprite_frames, prop_text(ach, "noOfFrames"))
        set_line(self.edit_sprite_effect, prop_text(ach, "effectFile"))
        set_checked(self.check_sprite_transparent, prop_bool(ach, "allwaystransparent"))
        set_checked(self.check_sprite_lazy_load, prop_bool(ach, "legacy_lazy_load"))
        set_checked(self.check_sprite_transparence_check, prop_bool(ach, "transparencecheck"))

        # animation
        anim_node = ach.first("animation")
        has_anim = anim_node is not None and isinstance(anim_node.value, ObjectNode)

        if has_anim:
            set_line(self.edit_sprite_anim_mask, self.anim_prop_text(anim_node, "animationmaskfile"))
            set_line(self.edit_sprite_anim_texture, self.anim_prop_text(anim_node, "animationtexturefile"))
            
            try:
                rot = float(self.anim_prop_text(anim_node, "animationrotation") or 0.0)
                if self.spin_sprite_anim_rotation:
                    self.spin_sprite_anim_rotation.setValue(rot)
            except Exception:
                pass
                
            set_checked(self.check_sprite_anim_looping, self.anim_prop_bool(anim_node, "animationlooping"))
            
            try:
                t = float(self.anim_prop_text(anim_node, "animationtime") or 0.0)
                if self.spin_sprite_anim_time:
                    self.spin_sprite_anim_time.setValue(t)
            except Exception:
                pass
                
            try:
                d = float(self.anim_prop_text(anim_node, "animationdelay") or 0.0)
                if self.spin_sprite_anim_delay:
                    self.spin_sprite_anim_delay.setValue(d)
            except Exception:
                pass
                
            blend_val = self.anim_prop_text(anim_node, "animationblendmode") or "add"
            display_text = BLEND_MODE_REV_MAP.get(blend_val, blend_val)
            set_combo(self.combo_sprite_anim_blend, display_text)
            
            rx, ry = self.anim_prop_object_xy(anim_node, "animationrotationoffset")
            if self.spin_sprite_anim_rot_x: self.spin_sprite_anim_rot_x.setValue(rx)
            if self.spin_sprite_anim_rot_y: self.spin_sprite_anim_rot_y.setValue(ry)
            
            sx, sy = self.anim_prop_object_xy(anim_node, "animationtexturescale")
            if self.spin_sprite_anim_scale_x: self.spin_sprite_anim_scale_x.setValue(sx)
            if self.spin_sprite_anim_scale_y: self.spin_sprite_anim_scale_y.setValue(sy)
            
            set_line(self.edit_sprite_anim_type, self.anim_prop_text(anim_node, "animationtype"))
        else:
            set_line(self.edit_sprite_anim_mask, "")
            set_line(self.edit_sprite_anim_texture, "")
            if self.spin_sprite_anim_rotation: self.spin_sprite_anim_rotation.setValue(0.0)
            set_checked(self.check_sprite_anim_looping, False)
            if self.spin_sprite_anim_time: self.spin_sprite_anim_time.setValue(0.0)
            if self.spin_sprite_anim_delay: self.spin_sprite_anim_delay.setValue(0.0)
            set_combo(self.combo_sprite_anim_blend, "加算 (add)")
            if self.spin_sprite_anim_rot_x: self.spin_sprite_anim_rot_x.setValue(0.0)
            if self.spin_sprite_anim_rot_y: self.spin_sprite_anim_rot_y.setValue(0.0)
            if self.spin_sprite_anim_scale_x: self.spin_sprite_anim_scale_x.setValue(1.0)
            if self.spin_sprite_anim_scale_y: self.spin_sprite_anim_scale_y.setValue(1.0)
            set_line(self.edit_sprite_anim_type, "")

    def load_frame_animated(self, ach: ParsedGfx):
        set_line(self.edit_frame_anim_name, prop_text(ach, "name"))
        set_line(self.edit_frame_anim_texture, prop_text(ach, "texturefile"))
        set_spin(self.spin_frame_anim_frames, prop_text(ach, "noOfFrames"))
        
        try:
            rate = float(prop_text(ach, "animation_rate_fps") or 0.0)
            if self.spin_frame_anim_rate: self.spin_frame_anim_rate.setValue(rate)
        except Exception:
            pass
            
        set_line(self.edit_frame_anim_effect, prop_text(ach, "effectFile"))
        set_checked(self.check_frame_anim_looping, prop_bool(ach, "looping"))
        set_checked(self.check_frame_anim_play, prop_bool(ach, "play_on_show"))
        
        try:
            pause = float(prop_text(ach, "pause_on_loop") or 0.0)
            if self.spin_frame_anim_pause: self.spin_frame_anim_pause.setValue(pause)
        except Exception:
            pass
            
        set_checked(self.check_frame_anim_transparent, prop_bool(ach, "allwaystransparent"))

    def load_progress_bar(self, ach: ParsedGfx):
        set_line(self.edit_progress_name, prop_text(ach, "name"))
        set_line(self.edit_progress_texture_one, prop_text(ach, "textureFile1"))
        set_line(self.edit_progress_texture_two, prop_text(ach, "textureFile2"))
        
        set_line(self.edit_progress_color_one, self.parse_color_prop(ach, "color"))
        set_line(self.edit_progress_color_two, self.parse_color_prop(ach, "colortwo"))
        
        w, h = self.parse_size_prop(ach, "size")
        if self.spin_progress_size_w: self.spin_progress_size_w.setValue(int(w))
        if self.spin_progress_size_h: self.spin_progress_size_h.setValue(int(h))
        
        set_line(self.edit_progress_effect, prop_text(ach, "effectFile"))
        set_checked(self.check_progress_horizontal, prop_bool(ach, "horizontal"))
        set_spin(self.spin_progress_steps, prop_text(ach, "steps"))

    def load_cornered_tile(self, ach: ParsedGfx):
        set_line(self.edit_cornered_name, prop_text(ach, "name"))
        set_line(self.edit_cornered_texture, prop_text(ach, "texturefile"))
        
        w, h = self.parse_size_prop(ach, "size")
        if self.spin_cornered_size_w: self.spin_cornered_size_w.setValue(int(w))
        if self.spin_cornered_size_h: self.spin_cornered_size_h.setValue(int(h))
        
        bx, by = self.parse_size_prop(ach, "borderSize")
        if self.spin_cornered_border_x: self.spin_cornered_border_x.setValue(int(bx))
        if self.spin_cornered_border_y: self.spin_cornered_border_y.setValue(int(by))
        
        set_line(self.edit_cornered_effect, prop_text(ach, "effectFile"))
        set_checked(self.check_cornered_transparent, prop_bool(ach, "allwaystransparent"))
        set_checked(self.check_cornered_tiling_center, prop_bool(ach, "tilingCenter"))

    def load_masked_shield(self, ach: ParsedGfx):
        set_line(self.edit_shield_name, prop_text(ach, "name"))
        set_line(self.edit_shield_texture, prop_text(ach, "textureFile1"))
        set_line(self.edit_shield_mask, prop_text(ach, "textureFile2"))
        set_line(self.edit_shield_effect, prop_text(ach, "effectFile"))

    def load_bitmap_font(self, ach: ParsedGfx):
        set_line(self.edit_font_name, prop_text(ach, "name"))
        set_line(self.edit_font_path, prop_text(ach, "path"))
        set_line(self.edit_font_color, prop_text(ach, "color"))
        
        cx, cy = self.parse_size_prop(ach, "cursor_offset")
        if self.spin_font_cursor_x: self.spin_font_cursor_x.setValue(int(cx))
        if self.spin_font_cursor_y: self.spin_font_cursor_y.setValue(int(cy))

    def load_font_override(self, ach: ParsedGfx):
        set_line(self.edit_override_font, prop_text(ach, "font"))
        set_combo(self.combo_override_language, prop_text(ach, "language"))
        set_line(self.edit_override_font_path, prop_text(ach, "path"))

    def load_map_text(self, ach: ParsedGfx):
        set_line(self.edit_map_text_name, prop_text(ach, "name"))
        set_line(self.edit_map_text_font, prop_text(ach, "font"))
        
        try:
            speed = float(prop_text(ach, "speed") or 0.0)
            if self.spin_map_text_speed: self.spin_map_text_speed.setValue(speed)
        except Exception:
            pass
            
        px, py = self.parse_size_prop(ach, "position")
        if self.spin_map_text_pos_x: self.spin_map_text_pos_x.setValue(px)
        if self.spin_map_text_pos_y: self.spin_map_text_pos_y.setValue(py)
        
        sx, sy = self.parse_size_prop(ach, "size")
        if self.spin_map_text_size_w: self.spin_map_text_size_w.setValue(sx)
        if self.spin_map_text_size_h: self.spin_map_text_size_h.setValue(sy)

    # 補助的なパース関数
    def anim_prop_text(self, anim_obj, key) -> str:
        if not anim_obj or not isinstance(anim_obj.value, ObjectNode):
            return ""
        assign = anim_obj.value.first_assignment(key)
        if assign and isinstance(assign.value, ScalarNode):
            return str(assign.value.value)
        return ""

    def anim_prop_bool(self, anim_obj, key) -> bool:
        if not anim_obj or not isinstance(anim_obj.value, ObjectNode):
            return False
        assign = anim_obj.value.first_assignment(key)
        if assign and isinstance(assign.value, ScalarNode):
            return str(assign.value.raw).lower() in {"yes", "true"}
        return False

    def anim_prop_object_xy(self, anim_obj, key) -> tuple[float, float]:
        if not anim_obj or not isinstance(anim_obj.value, ObjectNode):
            return 0.0, 0.0
        assign = anim_obj.value.first_assignment(key)
        if assign and isinstance(assign.value, ObjectNode):
            x_node = assign.value.first_assignment("x")
            y_node = assign.value.first_assignment("y")
            x = float(x_node.value.value) if x_node and isinstance(x_node.value, ScalarNode) else 0.0
            y = float(y_node.value.value) if y_node and isinstance(y_node.value, ScalarNode) else 0.0
            return x, y
        return 0.0, 0.0

    def parse_color_prop(self, ach, key) -> str:
        assign = ach.first(key)
        if assign and isinstance(assign.value, ObjectNode):
            vals = [str(item.value) for item in assign.value.items if isinstance(item, ScalarNode)]
            return " ".join(vals)
        return ""

    def parse_size_prop(self, ach, key) -> tuple[float, float]:
        assign = ach.first(key)
        if assign and isinstance(assign.value, ObjectNode):
            x_node = assign.value.first_assignment("x")
            y_node = assign.value.first_assignment("y")
            x = float(x_node.value.value) if x_node and isinstance(x_node.value, ScalarNode) else 0.0
            y = float(y_node.value.value) if y_node and isinstance(y_node.value, ScalarNode) else 0.0
            return x, y
        return 0.0, 0.0

def setup(widget, file_path: str, content: str):
    controller = GfxEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    widget.set_params = controller.set_params
    widget.setParams = controller.set_params
    
    controller.bind()
    
    core.api.notify_editor_ready(widget)
