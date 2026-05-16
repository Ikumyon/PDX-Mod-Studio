from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import core.api
from PySide6.QtCore import QFile, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from plugins.hoi4.script_parser import (
    AssignmentNode,
    ObjectNode,
    ParsedEntity,
    Parser,
    ScalarNode,
    SchemaEvaluator,
)

class ParsedAchievement:
    def __init__(self, entity: ParsedEntity):
        self.entity = entity
        self.id = entity.id
        self.node = entity.node
        self.source_path = entity.source_path

    def first(self, key: str) -> Optional[AssignmentNode]:
        return self.entity.first(key)

@dataclass
class AchievementDocument:
    achievements: list[ParsedAchievement] = field(default_factory=list)
    properties: dict = field(default_factory=dict)
    ast: Any = None

class AchievementParser:
    def __init__(self):
        base_dir = os.path.dirname(__file__)
        schema_path = os.path.join(base_dir, "achievement_schema.json")
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema_data = json.load(f)
        self.evaluator = SchemaEvaluator(self.schema_data)

    def parse_document(self, path: str, content: str) -> AchievementDocument:
        parser = Parser(content)
        ast, _, _ = parser.parse()
        
        doc = AchievementDocument()
        doc.ast = ast
        
        # ファイルレベルのプロパティ (unique_id) の抽出
        for item in getattr(ast, "items", []):
            if isinstance(item, AssignmentNode) and item.key == "unique_id":
                if isinstance(item.value, ScalarNode):
                    doc.properties["unique_id"] = str(item.value.value)
        
        # 各実績の抽出
        entities = self.evaluator.evaluate(ast, path)
        for e in entities:
            doc.achievements.append(ParsedAchievement(e))
            
        return doc

def setup(widget, file_path, content):
    controller = AchievementEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    # core側から呼ばれるインターフェース
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    controller.bind()

class AchievementEditorController:
    def __init__(self, widget, file_path, content):
        self.widget = widget
        self.file_path = file_path
        self.widget.content = content
        self.achievements: list[ParsedAchievement] = []
        self.parser = AchievementParser()
        self.updating = False

    def bind(self):
        # UIウィジェットの取得
        self.achievement_list = self.widget.findChild(QListWidget, "achievementList")
        
        # 実績基本情報
        self.achievement_id = self.widget.findChild(QLineEdit, "achievementIdEdit")
        self.achievement_title = self.widget.findChild(QLineEdit, "achievementTitleEdit")
        self.title_loc_path = self.widget.findChild(QLineEdit, "titleLocPathEdit")
        self.achievement_desc = self.widget.findChild(QPlainTextEdit, "achievementDescriptionEdit")
        self.desc_loc_path = self.widget.findChild(QLineEdit, "descriptionLocPathEdit")
        
        # 条件
        self.possible_cond = self.widget.findChild(QPlainTextEdit, "possibleConditionsEdit")
        self.happened_cond = self.widget.findChild(QPlainTextEdit, "happenedConditionsEdit")
        
        # リボン (Frame)
        self.frame_x = self.widget.findChild(QSpinBox, "frameXSpin")
        self.frame_y = self.widget.findChild(QSpinBox, "frameYSpin")
        self.frame_style = self.widget.findChild(QSpinBox, "frameStyleSpin")
        
        # リボン (Colors)
        self.color_widgets = []
        for i in range(1, 5):
            r = self.widget.findChild(QSpinBox, f"color{i}RSpin")
            g = self.widget.findChild(QSpinBox, f"color{i}GSpin")
            b = self.widget.findChild(QSpinBox, f"color{i}BSpin")
            btn = self.widget.findChild(QPushButton, f"color{i}PickerButton")
            if r and g and b and btn:
                self.color_widgets.append({"r": r, "g": g, "b": b, "btn": btn})
                btn.clicked.connect(lambda _, idx=i-1: self.pick_color(idx))

        # アイコン
        self.completed_icon = self.widget.findChild(QLineEdit, "completedIconPathEdit")
        self.possible_icon = self.widget.findChild(QLineEdit, "possibleIconPathEdit")
        self.not_eligible_icon = self.widget.findChild(QLineEdit, "notEligibleIconPathEdit")

        # リスト選択イベント
        if self.achievement_list:
            self.achievement_list.currentRowChanged.connect(self.on_selection_changed)

        # 初期リフレッシュ
        self.refresh()
        
        # ローカリゼーション更新の監視
        core.api.register_loc_changed_handler(self.refresh)

    def get_hoi4_plugin(self):
        """Find the active HOI4 plugin instance."""
        plugin = getattr(self.widget, "active_plugin", None)
        if plugin:
            return plugin
        plugin = core.api.get_active_plugin()
        if plugin:
            return plugin
        try:
            return self.widget.parent().parent().active_plugin
        except Exception:
            return None

    def set_content(self, content):
        self.widget.content = content
        self.refresh()

    def refresh(self):
        self.updating = True
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            self.achievements = doc.achievements
            
            # ローカライズレジストリの取得
            plugin = self.get_hoi4_plugin()
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
            
            if self.achievement_list:
                self.achievement_list.clear()
                for ach in self.achievements:
                    # IDをキーとして翻訳を検索
                    status, entry = registry.search_key_status(ach.id) if registry else ("not_found", None)
                    label = entry.get("value") if entry else ach.id
                    self.achievement_list.addItem(label)
                
                if self.achievement_list.count() > 0:
                    self.achievement_list.setCurrentRow(0)
        finally:
            self.updating = False

    def on_selection_changed(self, index):
        if self.updating or index < 0 or index >= len(self.achievements):
            return
        self.load_achievement(self.achievements[index])

    def load_achievement(self, ach: ParsedAchievement):
        self.updating = True
        try:
            # 基本情報
            if self.achievement_id:
                self.achievement_id.setText(ach.id)
            
            # 条件
            if self.possible_cond:
                self.possible_cond.setPlainText(self.get_block_content(ach, "possible"))
            if self.happened_cond:
                self.happened_cond.setPlainText(self.get_block_content(ach, "happened"))
            
            # リボン (Frame)
            ribbon_node = ach.first("ribbon")
            if ribbon_node and isinstance(ribbon_node.value, ObjectNode):
                frame_node = ribbon_node.value.first_assignment("frame")
                if frame_node and isinstance(frame_node.value, ObjectNode):
                    vals = [item.value for item in frame_node.value.items if isinstance(item, ScalarNode)]
                    if len(vals) >= 3:
                        if self.frame_x: self.frame_x.setValue(int(vals[0]))
                        if self.frame_y: self.frame_y.setValue(int(vals[1]))
                        if self.frame_style: self.frame_style.setValue(int(vals[2]))
                
                # リボン (Colors)
                colors_node = ribbon_node.value.first_assignment("colors")
                if colors_node and isinstance(colors_node.value, ObjectNode):
                    color_blocks = [item for item in colors_node.value.items if isinstance(item, ObjectNode)]
                    for i, block in enumerate(color_blocks):
                        if i >= len(self.color_widgets): break
                        vals = [item.value for item in block.items if isinstance(item, ScalarNode)]
                        if len(vals) >= 3:
                            self.color_widgets[i]["r"].setValue(int(vals[0]))
                            self.color_widgets[i]["g"].setValue(int(vals[1]))
                            self.color_widgets[i]["b"].setValue(int(vals[2]))
        finally:
            self.updating = False

    def get_block_content(self, ach: ParsedAchievement, key: str) -> str:
        node = ach.first(key)
        if node and isinstance(node.value, ObjectNode):
            # { } の内側を抽出
            start = node.value.open_range.end_offset if node.value.open_range else node.value.range.start_offset
            end = node.value.close_range.start_offset if node.value.close_range else node.value.range.end_offset
            return self.widget.content[start:end].strip()
        return ""

    def pick_color(self, idx):
        widgets = self.color_widgets[idx]
        current_color = QColor(widgets["r"].value(), widgets["g"].value(), widgets["b"].value())
        color = QColorDialog.getColor(current_color, self.widget, "色の選択")
        if color.isValid():
            widgets["r"].setValue(color.red())
            widgets["g"].setValue(color.green())
            widgets["b"].setValue(color.blue())
