from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import core.api
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from plugins.hoi4.script_parser import (
    AssignmentNode,
    ObjectNode,
    ParsedEntity,
    Parser,
    ScalarNode,
    SchemaEvaluator,
)

@dataclass
class Document:
    categories: list['ParsedDecisionCategory'] = field(default_factory=list)

class ParsedDecision:
    def __init__(self, entity: ParsedEntity):
        self.entity = entity
        self.id = entity.id
        self.node = entity.node
        self.source_path = entity.source_path

    def first(self, key: str):
        return self.entity.first(key)

class ParsedDecisionCategory:
    def __init__(self, entity: ParsedEntity):
        self.entity = entity
        self.id = entity.id
        self.node = entity.node
        self.source_path = entity.source_path
        self.decisions: list[ParsedDecision] = []

    def first(self, key: str):
        return self.entity.first(key)

class DecisionParser:
    def __init__(self, plugin=None):
        self.plugin = plugin
        base_dir = os.path.dirname(__file__)
        with open(os.path.join(base_dir, "decision_schema.json"), "r", encoding="utf-8") as f:
            self.dec_schema = json.load(f)
        with open(os.path.join(base_dir, "decision_category_schema.json"), "r", encoding="utf-8") as f:
            self.cat_schema = json.load(f)
        
        self.dec_evaluator = SchemaEvaluator(self.dec_schema)
        self.cat_evaluator = SchemaEvaluator(self.cat_schema)
        self.cat_fields = set(self.cat_schema.get("fields", {}).keys())
        self.schema_rules = self._load_schema_rules(base_dir)
        
        self.schema = {"schemas": {
            "category": {"properties": self.cat_schema.get("fields", {})},
            "decision": {"properties": self.dec_schema.get("fields", {})}
        }}

    def _load_schema_rules(self, base_dir: str) -> list[dict[str, str]]:
        config_path = os.path.join(base_dir, "config.json")
        rules = []
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            configured_rules = config.get("schema_rules", [])
            if isinstance(configured_rules, list):
                for rule in configured_rules:
                    if isinstance(rule, dict) and rule.get("path") and rule.get("schema"):
                        rules.append({
                            "path": rule["path"],
                            "schema": rule["schema"],
                            "role": rule.get("role", "decision"),
                            "document_type": rule.get("document_type", "")
                        })
        except Exception:
            pass

        if not rules:
            rules = [
                {
                    "path": self.cat_schema.get("file_scope", "common/decisions/categories"),
                    "schema": "decision_category_schema.json",
                    "role": "category",
                    "document_type": "decision_category_file"
                },
                {
                    "path": self.dec_schema.get("file_scope", "common/decisions"),
                    "schema": "decision_schema.json",
                    "role": "decision",
                    "document_type": "decision_file"
                }
            ]

        return sorted(rules, key=lambda rule: len(self._normalise_rule_path(rule["path"])), reverse=True)

    def _normalise_rule_path(self, path: str) -> str:
        return os.path.normcase(os.path.normpath(path.replace("/", os.sep)))

    def _rule_matches_path(self, rule: dict[str, str], path: str) -> bool:
        rule_path = self._normalise_rule_path(rule["path"])
        file_dir = self._normalise_rule_path(os.path.dirname(path))
        return (
            file_dir == rule_path
            or file_dir.startswith(rule_path + os.sep)
            or file_dir.endswith(os.sep + rule_path)
            or (os.sep + rule_path + os.sep) in (os.sep + file_dir + os.sep)
        )

    def get_schema_rule(self, path: str) -> dict[str, str]:
        for rule in self.schema_rules:
            if self._rule_matches_path(rule, path):
                return rule
        return {"path": "", "schema": "decision_schema.json", "role": "decision", "document_type": "decision_file"}

    def get_schema_role(self, path: str) -> str:
        return self.get_schema_rule(path).get("role", "decision")

    def parse_document(self, path: str, content: str) -> Document:
        parser = Parser(content)
        ast, _, _ = parser.parse()

        if self.get_schema_role(path) == "category":
            return self._parse_category_document(ast, path)
        return self._parse_decision_document(ast, path)

    def _parse_category_document(self, ast, path: str) -> Document:
        cat_entities = self.cat_evaluator.evaluate(ast, path)
        return Document(categories=[ParsedDecisionCategory(ce) for ce in cat_entities])

    def _parse_decision_document(self, ast, path: str) -> Document:
        cats = {}
        if hasattr(ast, "items"):
            for outer in getattr(ast, "items", []):
                if not isinstance(outer, AssignmentNode) or not isinstance(outer.value, ObjectNode):
                    continue
                entity = ParsedEntity(
                    schema_name="hoi4_decision_category_container",
                    id=outer.key,
                    parent_id=None,
                    properties=self._extract_category_container_properties(outer),
                    node=outer,
                    source_path=path
                )
                cats[outer.key] = ParsedDecisionCategory(entity)

        dec_entities = self._evaluate_decisions(ast, path)
        for de in dec_entities:
            pid = de.parent_id
            if pid in cats:
                cats[pid].decisions.append(ParsedDecision(de))

        return Document(categories=list(cats.values()))

    def _extract_category_container_properties(self, node: AssignmentNode) -> dict[str, list[AssignmentNode]]:
        properties: dict[str, list[AssignmentNode]] = {}
        if not isinstance(node.value, ObjectNode):
            return properties

        for child in node.value.items:
            if isinstance(child, AssignmentNode) and child.key in self.cat_fields:
                properties.setdefault(child.key, []).append(child)
        return properties

    def _evaluate_decisions(self, ast, path: str) -> list[ParsedEntity]:
        entities: list[ParsedEntity] = []
        if not hasattr(ast, "items"):
            return entities

        for outer in getattr(ast, "items", []):
            if not isinstance(outer, AssignmentNode) or not isinstance(outer.value, ObjectNode):
                continue
            for inner in outer.value.items:
                if not isinstance(inner, AssignmentNode) or not isinstance(inner.value, ObjectNode):
                    continue
                if inner.key in self.cat_fields:
                    continue
                entity = self.dec_evaluator._evaluate_node(
                    node_key=inner.key,
                    parent_key=outer.key,
                    node=inner,
                    path=path
                )
                if entity:
                    entities.append(entity)
        return entities

    def parse_project(self, project_path: str) -> list[ParsedDecisionCategory]:
        categories = {}

        for rule in self.schema_rules:
            scan_dir = os.path.join(project_path, rule["path"])
            if not os.path.exists(scan_dir):
                continue
            for root, _, files in os.walk(scan_dir):
                for file in files:
                    if not file.endswith(".txt"):
                        continue
                    path = os.path.join(root, file)
                    if self.get_schema_role(path) != rule.get("role"):
                        continue
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            doc = self.parse_document(path, f.read())
                    except Exception:
                        continue

                    for cat in doc.categories:
                        if cat.id in categories:
                            categories[cat.id].decisions.extend(cat.decisions)
                        else:
                            categories[cat.id] = cat
                            
        return list(categories.values())

MODE_NAME = "ディシジョンエディタ"
EDITOR_ID = "decision_editor"

def setup(widget, file_path, content):
    controller = DecisionEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    controller.bind()

class DecisionEditorController:
    def __init__(self, widget, file_path, content):
        self.widget = widget
        self.file_path = file_path
        self.widget.content = content
        self.categories: list[ParsedDecisionCategory] = []
        self.file_contents: dict[str, str] = {}
        self.selected_id = ""
        self.updating = False
        self.parser = DecisionParser(self.get_hoi4_plugin() or object())
        
        self.is_detailed_mode = False
        self.system_widgets = []
        self.format_config = {}
        self.load_format_config()

    def load_format_config(self):
        path = os.path.join(os.path.dirname(__file__), "decision_format.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.format_config = json.load(f)
            except Exception:
                self.format_config = {}
        else:
            self.format_config = {}

    def get_hoi4_plugin(self):
        """Find the active HOI4 plugin instance from the editor context."""
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

    def get_plugin_settings(self):
        settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
        try:
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def get_item_content(self, path):
        if not path or path == self.file_path:
            return self.widget.content
        if path in self.file_contents:
            return self.file_contents[path]
        
        # ファイルから読み込む
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                self.file_contents[path] = content
                return content
        except Exception:
            return ""

    def bind(self):
        # ウィジェットの取得
        self.tree_decisions = find(self.widget, QTreeWidget, "treeDecisions")
        self.stacked_editor = find(self.widget, QStackedWidget, "stackedEditor")
        
        # ページ
        self.page_category = find(self.widget, QWidget, "pageCategory")
        self.page_decision = find(self.widget, QWidget, "pageDecision")
        
        # プレースホルダページの作成
        from PySide6.QtWidgets import QVBoxLayout, QLabel
        self.page_placeholder = QWidget()
        layout = QVBoxLayout(self.page_placeholder)
        self.label_placeholder = QLabel("左の一覧から編集する項目を選択してください")
        self.label_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_placeholder.setStyleSheet("color: palette(disabled-text); font-style: italic;")
        layout.addWidget(self.label_placeholder)
        if self.stacked_editor:
            self.stacked_editor.addWidget(self.page_placeholder)
        
        # 共通ヘッダー
        self.label_editor_title = find(self.widget, QWidget, "labelEditorTitle")
        
        # カテゴリ編集用
        self.edit_category_id = find(self.widget, QLineEdit, "editCategoryId")
        self.edit_category_name_key = find(self.widget, QLineEdit, "editCategoryNameKey")
        self.edit_category_icon = find(self.widget, QLineEdit, "editCategoryIcon")
        self.edit_category_localisation = find(self.widget, QLineEdit, "editCategoryLocalisation")
        self.text_category_allowed = find(self.widget, QPlainTextEdit, "textCategoryAllowed")
        self.text_category_visible = find(self.widget, QPlainTextEdit, "textCategoryVisible")
        self.text_category_highlight_states = find(self.widget, QPlainTextEdit, "textCategoryHighlightStates")
        self.text_category_highlight_provinces = find(self.widget, QPlainTextEdit, "textCategoryHighlightProvinces")
        self.edit_category_highlight_color_before = find(self.widget, QLineEdit, "editHighlightColorBefore")
        self.edit_category_highlight_color_while = find(self.widget, QLineEdit, "editHighlightColorActive")
        
        # ディシジョン編集用
        self.edit_decision_id = find(self.widget, QLineEdit, "editDecisionId")
        self.edit_decision_localisation = find(self.widget, QLineEdit, "editDecisionLocalisation")
        self.edit_decision_icon = find(self.widget, QLineEdit, "editDecisionIcon")
        
        # スピンボックス等
        self.spin_days_remove = find(self.widget, QSpinBox, "spinDaysRemove")
        self.spin_days_re_enable = find(self.widget, QSpinBox, "spinDaysReEnable")
        self.check_fire_only_once = find(self.widget, QCheckBox, "checkFireOnlyOnce")
        self.check_cancel_if_not_visible = find(self.widget, QCheckBox, "checkCancelIfNotVisible")
        self.check_fixed_random_seed = find(self.widget, QCheckBox, "checkFixedRandomSeed")
        
        # カテゴリ追加分
        self.text_category_priority = find(self.widget, QPlainTextEdit, "ptCategoryPriority")
        self.check_category_visible_when_empty = find(self.widget, QCheckBox, "checkCategoryVisibleWhenEmpty")
        self.edit_category_scripted_gui = find(self.widget, QLineEdit, "editCategoryScriptedGui")
        self.edit_category_on_map_area = find(self.widget, QLineEdit, "editCategoryOnMapArea")
        self.edit_category_map_area = find(self.widget, QLineEdit, "editCategoryMapArea")
        self.edit_category_picture = find(self.widget, QLineEdit, "editCategoryPicture")
        
        # テキストエリア
        self.text_visible = find(self.widget, QPlainTextEdit, "textVisible")
        self.text_available = find(self.widget, QPlainTextEdit, "textAvailable")
        self.text_complete_effect = find(self.widget, QPlainTextEdit, "textCompleteEffect")
        
        # 翻訳先ファイル
        self.edit_category_loc_file = find(self.widget, QLineEdit, "editCategoryLocFile")
        self.edit_decision_loc_file = find(self.widget, QLineEdit, "editDecisionLocFile")
        self.edit_category_desc_localisation = find(self.widget, QPlainTextEdit, "editCategoryDescLocalisation")
        self.edit_category_desc_loc_file = find(self.widget, QLineEdit, "editCategoryDescLocFile")
        self.text_decision_desc_localisation = find(self.widget, QPlainTextEdit, "plainTextEdit_2")
        self.edit_decision_desc_loc_file = find(self.widget, QLineEdit, "editDecisionDescLocFile")
        
        # カスタムコスト
        self.edit_custom_cost_key = find(self.widget, QLineEdit, "customCostKeyEdit")
        self.text_custom_cost_localisation = find(self.widget, QPlainTextEdit, "customCostTextEdit")
        self.edit_custom_cost_loc_file = find(self.widget, QLineEdit, "customCostLocFileEdit")
        self.btn_select_category_loc_file = find(self.widget, QPushButton, "btnSelectCategoryLocFile")
        self.btn_select_category_desc_loc_file = find(self.widget, QPushButton, "btnSelectCategoryDescLocFile")
        self.btn_select_decision_loc_file = find(self.widget, QPushButton, "nameLocFileBrowseButton")
        self.btn_select_decision_desc_loc_file = find(self.widget, QPushButton, "descLocFileBrowseButton")
        self.btn_select_custom_cost_loc_file = find(self.widget, QPushButton, "customCostLocFileBrowseButton")
        
        # ボタン
        self.btn_add_category = find(self.widget, QPushButton, "btnAddCategory")
        self.btn_add_decision = find(self.widget, QPushButton, "btnAddDecision")
        self.btn_duplicate = find(self.widget, QPushButton, "btnDuplicateItem")
        self.btn_delete = find(self.widget, QPushButton, "btnDeleteItem")
        
        # コスト切替
        self.radio_pp_cost = find(self.widget, QRadioButton, "radioPPCost")
        self.radio_custom_cost = find(self.widget, QRadioButton, "radioCustomCost")
        self.stacked_cost = find(self.widget, QStackedWidget, "stackedCost")
        self.pp_page = find(self.widget, QWidget, "ppPage")
        self.custom_cost_page = find(self.widget, QWidget, "CostomCostPage")
        self.spin_cost = find(self.widget, QSpinBox, "spinCost")
        
        # モード切替
        self.btn_standard_mode = find(self.widget, QToolButton, "decisionStandardModeButton")
        self.btn_detail_mode = find(self.widget, QToolButton, "decisionDetailModeButton")
        self.preview_graphics = find(self.widget, QGraphicsView, "previewGraphicsView")

        if self.preview_graphics:
            self.preview_scene = QGraphicsScene()
            self.preview_graphics.setScene(self.preview_scene)
            self.preview_graphics.setBackgroundBrush(QBrush(QColor("#151815")))
            self.preview_graphics.setRenderHint(QPainter.RenderHint.Antialiasing)

        # イベント接続
        if self.tree_decisions:
            self.tree_decisions.currentItemChanged.connect(self.on_tree_selection_changed)
            self.tree_decisions.setHeaderLabels(["ID / Name"])
            
        if self.btn_standard_mode:
            self.btn_standard_mode.clicked.connect(lambda: self.set_detailed_mode(False))
        if self.btn_detail_mode:
            self.btn_detail_mode.clicked.connect(lambda: self.set_detailed_mode(True))

        # コスト切替
        if self.radio_pp_cost:
            self.radio_pp_cost.toggled.connect(self.on_cost_type_changed)
        if self.radio_custom_cost:
            self.radio_custom_cost.toggled.connect(self.on_cost_type_changed)
        if self.spin_cost:
            self.spin_cost.valueChanged.connect(lambda _value: self.update_preview())
        if self.edit_decision_localisation:
            self.edit_decision_localisation.textChanged.connect(lambda _text: self.update_preview())
        if self.text_decision_desc_localisation:
            self.text_decision_desc_localisation.textChanged.connect(self.update_preview)
        if self.edit_decision_icon:
            self.edit_decision_icon.textChanged.connect(lambda _text: self.update_preview())
        if self.edit_category_localisation:
            self.edit_category_localisation.textChanged.connect(lambda _text: self.update_preview())
        if self.edit_category_desc_localisation:
            self.edit_category_desc_localisation.textChanged.connect(self.update_preview)

        # ボタン接続
        if self.btn_add_category: self.btn_add_category.clicked.connect(self.add_category)
        if self.btn_add_decision: self.btn_add_decision.clicked.connect(self.add_decision)
        if self.btn_duplicate: self.btn_duplicate.clicked.connect(self.duplicate_item)
        if self.btn_delete: self.btn_delete.clicked.connect(self.delete_item)
        if self.btn_select_category_loc_file: self.btn_select_category_loc_file.clicked.connect(lambda: self.browse_loc_file(self.edit_category_loc_file))
        if self.btn_select_category_desc_loc_file: self.btn_select_category_desc_loc_file.clicked.connect(lambda: self.browse_loc_file(self.edit_category_desc_loc_file))
        if self.btn_select_decision_loc_file: self.btn_select_decision_loc_file.clicked.connect(lambda: self.browse_loc_file(self.edit_decision_loc_file))
        if self.btn_select_decision_desc_loc_file: self.btn_select_decision_desc_loc_file.clicked.connect(lambda: self.browse_loc_file(self.edit_decision_desc_loc_file))
        if self.btn_select_custom_cost_loc_file: self.btn_select_custom_cost_loc_file.clicked.connect(lambda: self.browse_loc_file(self.edit_custom_cost_loc_file))

        # IDの接続
        self.connect_scalar(self.edit_category_id, "category_id")
        self.connect_scalar(self.edit_decision_id, "decision_id")
        
        # カテゴリプロパティの接続
        self.connect_scalar(self.edit_category_name_key, "name")
        self.connect_scalar(self.edit_category_icon, "icon")
        self.connect_scalar(self.edit_category_highlight_color_before, "highlight_color_before_active")
        self.connect_scalar(self.edit_category_highlight_color_while, "highlight_color_while_active")
        
        # ディシジョンプロパティの接続
        self.connect_scalar(self.edit_decision_icon, "icon")
        self.connect_spin(self.spin_cost, "cost")
        self.connect_spin(self.spin_days_remove, "days_remove")
        self.connect_spin(self.spin_days_re_enable, "days_re_enable")
        self.connect_bool(self.check_fire_only_once, "fire_only_once")
        self.connect_bool(self.check_cancel_if_not_visible, "cancel_if_not_visible")
        self.connect_bool(self.check_fixed_random_seed, "fixed_random_seed")
        self.connect_scalar(self.edit_custom_cost_key, "custom_cost_text")

        # カテゴリ追加分の接続
        self.connect_text(self.text_category_priority, "priority")
        self.connect_bool(self.check_category_visible_when_empty, "visible_when_empty")
        self.connect_scalar(self.edit_category_scripted_gui, "scripted_gui")
        self.connect_scalar(self.edit_category_on_map_area, "on_map_area")
        self.connect_scalar(self.edit_category_map_area, "map_area")
        self.connect_scalar(self.edit_category_picture, "picture")

        # テキストエリアの接続
        self.connect_text(self.text_category_allowed, "allowed")
        self.connect_text(self.text_category_visible, "visible")
        self.connect_text(self.text_category_highlight_states, "highlight_states")
        self.connect_text(self.text_category_highlight_provinces, "highlight_provinces")
        self.connect_text(self.text_visible, "visible")
        self.connect_text(self.text_available, "available")
        self.connect_text(self.text_complete_effect, "complete_effect")

        # システム項目の定義（詳細モードでのみ表示）
        self.system_widgets = [
            find(self.widget, QWidget, "labelCategoryId"), self.edit_category_id,
            find(self.widget, QWidget, "labelDecisionId"), self.edit_decision_id,
            find(self.widget, QWidget, "labelCategoryNameKey"), self.edit_category_name_key,
            
            # 翻訳先ファイル関連
            find(self.widget, QWidget, "labelCategoryLocFile"), find(self.widget, QWidget, "editCategoryLocFile"), find(self.widget, QWidget, "btnSelectCategoryLocFile"),
            find(self.widget, QWidget, "labelCategoryDescLocFile"), find(self.widget, QWidget, "editCategoryDescLocFile"), find(self.widget, QWidget, "btnSelectCategoryDescLocFile"),
            find(self.widget, QWidget, "labelDecisionLocFile"), find(self.widget, QWidget, "editDecisionLocFile"), find(self.widget, QWidget, "nameLocFileBrowseButton"),
            find(self.widget, QWidget, "labelDecisionDescLocFile"), find(self.widget, QWidget, "editDecisionDescLocFile"), find(self.widget, QWidget, "descLocFileBrowseButton"),
            find(self.widget, QWidget, "labelCustomCostKey"), find(self.widget, QWidget, "customCostKeyEdit"),
            find(self.widget, QWidget, "labelCustomCostLocFile"), find(self.widget, QWidget, "customCostLocFileEdit"), find(self.widget, QWidget, "customCostLocFileBrowseButton"),
        ]
        self.system_widgets = [w for w in self.system_widgets if w]

        self.refresh()
        self.set_detailed_mode(False)

    def set_content(self, content):
        self.widget.content = content
        self.refresh()

    def apply_format(self, fmt, **kwargs):
        try:
            return fmt.format(**kwargs)
        except Exception:
            result = fmt
            for key, value in kwargs.items():
                result = result.replace(f"{{{key}}}", str(value))
            return result

    def format_values(self, category=None, decision_id="", number=1, lang=None):
        if lang is None:
            lang = self.get_plugin_settings().get("display_language", "l_japanese")
        category_id = category.id if category else ""
        file_stem = os.path.splitext(os.path.basename(self.file_path))[0]
        fallback_id = f"{category_id}_{number}" if category_id else f"decision_{number}"
        
        # アルファベット連番 {a-z} の生成
        letter = chr(ord('a') + (number - 1) % 26)
        if number > 26:
            # 27番目以降は a2, b2... のように処理
            letter += str((number - 1) // 26 + 1)

        # l_japanese -> japanese のようにプレフィックスを除去
        display_lang = lang or ""
        if display_lang.startswith("l_"):
            display_lang = display_lang[2:]

        return {
            "category": category_id,
            "file": file_stem,
            "number": number,
            "a-z": letter,
            "lang": display_lang,
            "id": decision_id or fallback_id,
        }

    def generate_unique_decision_id(self, category):
        settings = self.get_plugin_settings()
        fmt = settings.get("decision_id_format", "{category}_{number}") or "{category}_{number}"
        existing_ids = {decision.id for cat in self.categories for decision in cat.decisions}
        uses_number = "{number}" in fmt

        counter = 1
        while counter <= 9999:
            candidate = self.apply_format(fmt, **self.format_values(category=category, number=counter)).strip()
            if not candidate:
                candidate = "sample_decision"
            if not uses_number and counter > 1:
                candidate = f"{candidate}_{counter}"
            candidate = "_".join(candidate.split())
            if candidate not in existing_ids:
                return candidate
            counter += 1

        return f"sample_decision_{len(existing_ids) + 1}"

    def generate_unique_category_id(self):
        settings = self.get_plugin_settings()
        fmt = settings.get("decision_category_id_format", "{category}_{number}") or "{category}_{number}"
        existing_ids = {cat.id for cat in self.categories}
        uses_number = "{number}" in fmt
        
        # {category} が含まれているが、新規作成時は未確定なので暫定的に "category" を使う
        # もしフォーマットに {category} がなければそのまま、あれば sample に置換
        
        counter = 1
        while counter <= 9999:
            vals = self.format_values(number=counter)
            if not vals["category"]:
                vals["category"] = "sample"
            
            candidate = self.apply_format(fmt, **vals).strip()
            if not candidate:
                candidate = "sample_category"
            if not uses_number and counter > 1:
                candidate = f"{candidate}_{counter}"
            candidate = "_".join(candidate.split())
            if candidate not in existing_ids:
                return candidate
            counter += 1

        return f"sample_category_{len(existing_ids) + 1}"

    def refresh(self):
        self.updating = True
        try:
            # プロジェクト全体のディシジョンを取得 (マージ済み)
            project_path = core.api.get_project_path()
            if not project_path:
                doc = self.parser.parse_document(self.file_path, self.widget.content)
                self.categories = doc.categories
            else:
                # 全データを読み込み
                all_categories = self.parser.parse_project(project_path)

                # 現在のファイルのカテゴリプロパティを優先する。
                # このエディタはカテゴリとディシジョンを同じ画面で編集するため、
                # project全体側のカテゴリに差し替えると visible_when_empty などが消える。
                local_doc = self.parser.parse_document(self.file_path, self.widget.content)
                project_by_id = {cat.id: cat for cat in all_categories}

                self.categories = []
                for local_cat in local_doc.categories:
                    project_cat = project_by_id.get(local_cat.id)
                    if project_cat:
                        local_cat.decisions = self.merge_decisions(local_cat.decisions, project_cat.decisions)
                    self.categories.append(local_cat)
            
            # 各ファイルの最新の内容をキャッシュ（自ファイルは widget.content を使用）
            self.file_contents = { self.file_path: self.widget.content }
            
            # ローカライズレジストリを取得
            plugin = self.get_hoi4_plugin()
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
            
            if self.tree_decisions:
                was_blocked = self.tree_decisions.blockSignals(True)
                self.tree_decisions.setUpdatesEnabled(False)
                try:
                    # 選択状態を保持
                    selected_item_data = self.get_current_data()
                    
                    self.tree_decisions.clear()
                    for cat in self.categories:
                        # registry.get ではなく search_key_status を使用
                        status, entry = registry.search_key_status(cat.id) if registry else ("not_found", None)
                        cat_name = entry.get("value") if entry else None
                        cat_label = cat_name if cat_name else cat.id
                        
                        cat_item = QTreeWidgetItem(self.tree_decisions)
                        cat_item.setText(0, cat_label)
                        cat_item.setData(0, Qt.ItemDataRole.UserRole, cat)
                        
                        for dec in cat.decisions:
                            # registry.get ではなく search_key_status を使用
                            status, entry = registry.search_key_status(dec.id) if registry else ("not_found", None)
                            dec_name = entry.get("value") if entry else None
                            dec_label = dec_name if dec_name else dec.id
                            
                            dec_item = QTreeWidgetItem(cat_item)
                            dec_item.setText(0, dec_label)
                            dec_item.setData(0, Qt.ItemDataRole.UserRole, dec)
                    
                    self.tree_decisions.expandAll()
                    
                    # 選択を復元
                    if selected_item_data:
                        self.restore_selection(selected_item_data)
                finally:
                    self.tree_decisions.setUpdatesEnabled(True)
                    self.tree_decisions.blockSignals(was_blocked)
            
            self.load_selected_item()
        finally:
            self.updating = False
            self.update_preview()

    def merge_decisions(self, primary: list[ParsedDecision], secondary: list[ParsedDecision]) -> list[ParsedDecision]:
        merged = list(primary)
        seen = {self.decision_identity(dec) for dec in merged}
        for dec in secondary:
            key = self.decision_identity(dec)
            if key not in seen:
                merged.append(dec)
                seen.add(key)
        return merged

    def decision_identity(self, decision: ParsedDecision):
        return (decision.id, os.path.normcase(os.path.abspath(decision.source_path or "")))

    def restore_selection(self, data):
        for i in range(self.tree_decisions.topLevelItemCount()):
            item = self.tree_decisions.topLevelItem(i)
            item_data = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, ParsedDecisionCategory) and isinstance(item_data, ParsedDecisionCategory) and item_data.id == data.id:
                self.tree_decisions.setCurrentItem(item)
                return
            
            for j in range(item.childCount()):
                child = item.child(j)
                child_data = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, ParsedDecision) and isinstance(child_data, ParsedDecision) and child_data.id == data.id:
                    self.tree_decisions.setCurrentItem(child)
                    return

    def on_tree_selection_changed(self, current, previous):
        if self.updating: return
        self.load_selected_item()
        self.update_preview()

    def load_selected_item(self):
        if not self.tree_decisions: return
        data = self.get_current_data()
        if not data:
            if self.stacked_editor:
                self.stacked_editor.setCurrentWidget(self.page_placeholder)
                self.stacked_editor.setVisible(True)
            if self.label_editor_title: self.label_editor_title.setText("編集")
            return
        
        self.stacked_editor.setVisible(True)
        
        # アイテムが定義されているファイルのコンテンツを取得
        source_path = data.source_path or self.file_path
        content = self.get_item_content(source_path)
        
        # ローカライズレジストリを取得
        plugin = self.get_hoi4_plugin()
        registry = getattr(plugin, "localisation_registry", None) if plugin else None
        
        if isinstance(data, ParsedDecisionCategory):
            if self.stacked_editor: self.stacked_editor.setCurrentWidget(self.page_category)
            if self.label_editor_title: self.label_editor_title.setText("カテゴリ編集")
            
            set_line(self.edit_category_id, data.id)
            set_line(self.edit_category_icon, prop_text(data, "icon"))
            set_line(self.edit_category_picture, prop_text(data, "picture"))
            set_plain(self.text_category_priority, block_text(content, data.node, "priority"))
            set_checked(self.check_category_visible_when_empty, prop_bool(data, "visible_when_empty"))
            set_line(self.edit_category_scripted_gui, prop_text(data, "scripted_gui"))
            set_line(self.edit_category_on_map_area, prop_text(data, "on_map_area"))
            set_line(self.edit_category_map_area, prop_text(data, "map_area"))
            set_line(self.edit_category_highlight_color_before, prop_text(data, "highlight_color_before_active"))
            set_line(self.edit_category_highlight_color_while, prop_text(data, "highlight_color_while_active"))
            
            # ローカライズ表示名 (カテゴリも原則 ID がキー)
            name_key = data.id
            status, entry = registry.search_key_status(name_key) if registry else ("not_found", None)
            set_line(self.edit_category_localisation, entry.get("value") if entry else "")
            
            # 翻訳元ファイルを表示
            if entry and self.edit_category_loc_file:
                source_file = entry.get("file", "")
                self.edit_category_loc_file.setText(os.path.basename(source_file))
                self.edit_category_loc_file.setToolTip(source_file)
            
            # 説明のローカライズ表示 (常に ID_desc)
            desc_key = data.id + "_desc"
            status, entry = registry.search_key_status(desc_key) if registry else ("not_found", None)
            set_plain(self.edit_category_desc_localisation, entry.get("value") if entry else "")
            if entry and self.edit_category_desc_loc_file:
                source_file = entry.get("file", "")
                self.edit_category_desc_loc_file.setText(os.path.basename(source_file))
                self.edit_category_desc_loc_file.setToolTip(source_file)
            
            set_plain(self.text_category_allowed, block_text(content, data.node, "allowed"))
            set_plain(self.text_category_visible, block_text(content, data.node, "visible"))
            set_plain(self.text_category_highlight_states, block_text(content, data.node, "highlight_states"))
            set_plain(self.text_category_highlight_provinces, block_text(content, data.node, "highlight_provinces"))
            
        elif isinstance(data, ParsedDecision):
            if self.stacked_editor: self.stacked_editor.setCurrentWidget(self.page_decision)
            if self.label_editor_title: self.label_editor_title.setText("ディシジョン編集")
            
            set_line(self.edit_decision_id, data.id)
            set_line(self.edit_decision_icon, prop_text(data, "icon"))
            
            # ローカライズ表示名 (ディシジョンは常に ID がキー)
            name_key = data.id
            status, entry = registry.search_key_status(name_key) if registry else ("not_found", None)
            set_line(self.edit_decision_localisation, entry.get("value") if entry else "")
            
            # 翻訳元ファイルを表示
            if entry and self.edit_decision_loc_file:
                source_file = entry.get("file", "")
                self.edit_decision_loc_file.setText(os.path.basename(source_file))
                self.edit_decision_loc_file.setToolTip(source_file)
            
            # 説明のローカライズ表示 (ディシジョンは常に ID_desc)
            desc_key = data.id + "_desc"
            status, entry = registry.search_key_status(desc_key) if registry else ("not_found", None)
            set_plain(self.text_decision_desc_localisation, entry.get("value") if entry else "")
            if entry and self.edit_decision_desc_loc_file:
                source_file = entry.get("file", "")
                self.edit_decision_desc_loc_file.setText(os.path.basename(source_file))
                self.edit_decision_desc_loc_file.setToolTip(source_file)
            
            # カスタムコストのローカライズ表示
            cc_key = prop_text(data, "custom_cost_text")
            set_line(self.edit_custom_cost_key, cc_key)
            if cc_key:
                status, entry = registry.search_key_status(cc_key) if registry else ("not_found", None)
                set_plain(self.text_custom_cost_localisation, entry.get("value") if entry else "")
                if entry and self.edit_custom_cost_loc_file:
                    source_file = entry.get("file", "")
                    self.edit_custom_cost_loc_file.setText(os.path.basename(source_file))
                    self.edit_custom_cost_loc_file.setToolTip(source_file)
            else:
                set_plain(self.text_custom_cost_localisation, "")
                set_line(self.edit_custom_cost_loc_file, "")
            
            set_spin(self.spin_cost, prop_text(data, "cost"))
            set_spin(self.spin_days_remove, prop_text(data, "days_remove"))
            set_spin(self.spin_days_re_enable, prop_text(data, "days_re_enable"))
            set_checked(self.check_fire_only_once, prop_bool(data, "fire_only_once"))
            set_checked(self.check_cancel_if_not_visible, prop_bool(data, "cancel_if_not_visible"))
            set_checked(self.check_fixed_random_seed, prop_bool(data, "fixed_random_seed"))
            
            set_plain(self.text_visible, block_text(content, data.node, "visible"))
            set_plain(self.text_available, block_text(content, data.node, "available"))
            set_plain(self.text_complete_effect, block_text(content, data.node, "complete_effect"))
            
            # コストの表示切替
            has_custom = data.first("custom_cost_trigger") is not None
            if has_custom:
                if self.radio_custom_cost: self.radio_custom_cost.setChecked(True)
                if self.stacked_cost: self.stacked_cost.setCurrentWidget(self.custom_cost_page)
            else:
                if self.radio_pp_cost: self.radio_pp_cost.setChecked(True)
                if self.stacked_cost: self.stacked_cost.setCurrentWidget(self.pp_page)

    def asset_path(self, *parts):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "asset", "icons", *parts))

    def current_preview_category(self):
        data = self.get_current_data()
        if isinstance(data, ParsedDecisionCategory):
            return data

        if isinstance(data, ParsedDecision) and self.tree_decisions:
            item = self.tree_decisions.currentItem()
            if item and item.parent():
                parent_data = item.parent().data(0, Qt.ItemDataRole.UserRole)
                if isinstance(parent_data, ParsedDecisionCategory):
                    return parent_data

            for category in self.categories:
                if any(dec.id == data.id for dec in category.decisions):
                    return category

        return self.categories[0] if self.categories else None

    def current_preview_decision_id(self):
        data = self.get_current_data()
        return data.id if isinstance(data, ParsedDecision) else ""

    def localised_text(self, key, fallback=""):
        if not key:
            return fallback
        plugin = self.get_hoi4_plugin()
        registry = getattr(plugin, "localisation_registry", None) if plugin else None
        if registry:
            status, entry = registry.search_key_status(key)
            if entry and entry.get("value"):
                return entry["value"]
        return fallback or key

    def category_title_for_preview(self, category):
        data = self.get_current_data()
        if isinstance(data, ParsedDecisionCategory) and data.id == category.id:
            text = self._get_loc_text(self.edit_category_localisation).strip()
            if text:
                return text
        return self.localised_text(category.id, category.id)

    def category_desc_for_preview(self, category):
        data = self.get_current_data()
        if isinstance(data, ParsedDecisionCategory) and data.id == category.id:
            text = self._get_loc_text(self.edit_category_desc_localisation).strip()
            if text:
                return text
        desc_key = f"{category.id}_desc"
        return self.localised_text(desc_key, desc_key)

    def decision_title_for_preview(self, decision):
        data = self.get_current_data()
        if isinstance(data, ParsedDecision) and data.id == decision.id:
            text = self._get_loc_text(self.edit_decision_localisation).strip()
            if text:
                return text
        return self.localised_text(decision.id, decision.id)

    def decision_cost_for_preview(self, decision):
        data = self.get_current_data()
        is_current = isinstance(data, ParsedDecision) and data.id == decision.id
        if is_current and self.spin_cost:
            return str(self.spin_cost.value())
        return prop_text(decision, "cost") or "0"

    def decision_uses_custom_cost(self, decision):
        data = self.get_current_data()
        if isinstance(data, ParsedDecision) and data.id == decision.id and self.radio_custom_cost:
            return self.radio_custom_cost.isChecked()
        return decision.first("custom_cost_trigger") is not None

    def add_preview_text(self, parent, text, x, y, width, size=9, color="#f2f2e8", bold=False, align=None):
        item = QGraphicsTextItem(text, parent)
        item.setTextWidth(width)
        font = QFont("Segoe UI", size)
        font.setBold(bold)
        item.setFont(font)
        item.setDefaultTextColor(QColor(color))
        if align is not None:
            option = QTextOption(item.document().defaultTextOption())
            option.setAlignment(align)
            item.document().setDefaultTextOption(option)
        item.setPos(x, y)
        self.preview_items.append(item)
        return item

    def add_centered_preview_text(self, parent, text, center_x, y, max_width, size=9, color="#f2f2e8", bold=False):
        item = QGraphicsTextItem(text, parent)
        font = QFont("Segoe UI", size)
        font.setBold(bold)
        item.setFont(font)
        item.setDefaultTextColor(QColor(color))

        natural_width = item.boundingRect().width()
        if natural_width > max_width:
            item.setTextWidth(max_width)
            option = QTextOption(item.document().defaultTextOption())
            option.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item.document().setDefaultTextOption(option)
            item.setPos(center_x - max_width / 2, y)
        else:
            item.setPos(center_x - natural_width / 2, y)

        self.preview_items.append(item)
        return item

    def add_preview_pixmap(self, parent, path, x, y, width, height):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        pixmap = pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        item = QGraphicsPixmapItem(pixmap, parent)
        item.setPos(x + (width - pixmap.width()) / 2, y + (height - pixmap.height()) / 2)
        self.preview_items.append(item)
        return item

    def draw_preview_placeholder(self):
        width = 520
        height = 320
        frame = QGraphicsRectItem(0, 0, width, height)
        frame.setBrush(QBrush(QColor("#111412")))
        frame.setPen(QPen(QColor("#3b3830"), 2))
        self.preview_scene.addItem(frame)
        self.preview_items.append(frame)

        pixmap = QPixmap(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "placeholder.png")))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(width, height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            image = QGraphicsPixmapItem(pixmap, frame)
            image.setOpacity(0.35)
            image.setPos((width - pixmap.width()) / 2, (height - pixmap.height()) / 2)
            self.preview_items.append(image)

        overlay = QGraphicsRectItem(0, 0, width - 72, 58, frame)
        overlay.setPos(36, 130)
        overlay.setBrush(QBrush(QColor(0, 0, 0, 160)))
        overlay.setPen(QPen(QColor("#5f5646"), 1))
        self.preview_items.append(overlay)
        self.add_preview_text(frame, "ディシジョン新規作成か、既存のディシジョンを選択してください。", 54, 145, width - 108, 12, "#f0e9d8", True)
        self.preview_scene.setSceneRect(0, 0, width, height)

    def draw_decision_row(self, parent, decision, y, selected=False):
        row_height = 39
        row = QGraphicsRectItem(0, 0, 500, row_height, parent)
        row.setPos(10, y)
        row.setBrush(QBrush(QColor("#213f22" if not selected else "#284d29")))
        row.setPen(QPen(QColor("#5f7f51" if selected else "#1b291b"), 1))
        self.preview_items.append(row)

        icon_path = self.asset_path("generic_decision.png")
        self.add_preview_pixmap(row, icon_path, 10, 4, 31, 31)

        title = self.decision_title_for_preview(decision)
        self.add_preview_text(row, title, 60, 5, 300, 9, "#f5f3e8", True)

        if self.decision_uses_custom_cost(decision):
            custom = prop_text(decision, "custom_cost_text") or "custom"
            self.add_preview_text(row, self.localised_text(custom, custom), 394, 6, 74, 8, "#efc84a", True)
        else:
            self.add_preview_pixmap(row, self.asset_path("pp_icon.png"), 387, 8, 20, 20)
            self.add_preview_text(row, self.decision_cost_for_preview(decision), 413, 5, 42, 9, "#ffcf25", True)

        self.add_preview_pixmap(row, self.asset_path("mail_checkmark.png"), 462, 4, 34, 30)

    def update_preview(self):
        if self.updating:
            return
        if not hasattr(self, "preview_scene"):
            return
        self.preview_scene.clear()
        self.preview_items = []

        category = self.current_preview_category()
        if not category:
            self.draw_preview_placeholder()
            return

        width = 520
        row_height = 39
        row_count = max(1, len(category.decisions))
        height = 154 + row_count * row_height + 14

        frame = QGraphicsRectItem(0, 0, width, height)
        frame.setBrush(QBrush(QColor("#101412")))
        frame.setPen(QPen(QColor("#4a4539"), 2))
        self.preview_scene.addItem(frame)
        self.preview_items.append(frame)

        top_bar = QGraphicsRectItem(0, 0, width - 16, 42, frame)
        top_bar.setPos(8, 8)
        top_bar.setBrush(QBrush(QColor("#211c17")))
        top_bar.setPen(QPen(QColor("#62513d"), 1))
        self.preview_items.append(top_bar)
        self.add_preview_pixmap(top_bar, self.asset_path("generic_decision.png"), 8, 2, 54, 38)

        title_box = QGraphicsRectItem(0, 0, 350, 22, frame)
        title_box.setPos(96, 16)
        title_box.setBrush(QBrush(QColor("#12100d")))
        title_box.setPen(QPen(QColor("#352b22"), 1))
        self.preview_items.append(title_box)
        title = self.category_title_for_preview(category)
        self.add_centered_preview_text(frame, title, 271, 12, 350, 8, "#ffffff", True)

        fold_button = QGraphicsRectItem(0, 0, 22, 22, frame)
        fold_button.setPos(480, 15)
        fold_button.setBrush(QBrush(QColor("#7c6040")))
        fold_button.setPen(QPen(QColor("#b89b66"), 1))
        self.preview_items.append(fold_button)
        self.add_preview_text(frame, "^", 482, 12, 18, 11, "#f7e7bd", True, Qt.AlignmentFlag.AlignCenter)

        desc_panel = QGraphicsRectItem(0, 0, width - 20, 98, frame)
        desc_panel.setPos(10, 54)
        desc_panel.setBrush(QBrush(QColor("#171717")))
        desc_panel.setPen(QPen(QColor("#323232"), 1))
        self.preview_items.append(desc_panel)
        desc = self.category_desc_for_preview(category)
        self.add_preview_text(frame, desc, 28, 62, width - 58, 9, "#ffffff", True)

        selected_decision_id = self.current_preview_decision_id()
        if category.decisions:
            for index, decision in enumerate(category.decisions):
                self.draw_decision_row(frame, decision, 156 + index * row_height, decision.id == selected_decision_id)
        else:
            empty = QGraphicsRectItem(0, 0, 500, row_height, frame)
            empty.setPos(10, 156)
            empty.setBrush(QBrush(QColor("#1c2421")))
            empty.setPen(QPen(QColor("#303833"), 1))
            self.preview_items.append(empty)
            self.add_preview_text(empty, "このカテゴリにディシジョンはありません", 60, 6, 340, 9, "#b8b8ad", True)

        self.preview_scene.setSceneRect(0, 0, width, height)

    def on_cost_type_changed(self):
        if self.updating: return
        if not self.stacked_cost: return
        
        if self.radio_pp_cost and self.radio_pp_cost.isChecked():
            self.stacked_cost.setCurrentWidget(self.pp_page)
        elif self.radio_custom_cost and self.radio_custom_cost.isChecked():
            self.stacked_cost.setCurrentWidget(self.custom_cost_page)
        self.update_preview()

    def add_category(self):
        text = self.widget.content
        new_id = self.generate_unique_category_id()
            
        new_cat = f"\n{new_id} = {{\n\tallowed = {{\n\t\talways = yes\n\t}}\n}}\n"
        self.widget.content = text.rstrip() + "\n" + new_cat
        self.refresh()

    def add_decision(self):
        data = self.get_current_data()
        if not data: return
        
        cat = data if isinstance(data, ParsedDecisionCategory) else None
        if not cat:
            item = self.tree_decisions.currentItem()
            if item and item.parent():
                cat = item.parent().data(0, Qt.ItemDataRole.UserRole)
        
        if not cat: return
        
        text = self.widget.content
        insertion_offset = cat.node.range.end_offset - 1
        new_id = self.generate_unique_decision_id(cat)
            
        new_dec = f"\n\t{new_id} = {{\n\t\ticon = generic_political_discourse\n\t\tcomplete_effect = {{\n\t\t}}\n\t}}\n"
        self.widget.content = text[:insertion_offset] + new_dec + text[insertion_offset:]
        self.refresh()

    def duplicate_item(self):
        data = self.get_current_data()
        if not data: return
        
        text = self.widget.content
        start = data.node.range.start_offset
        end = data.node.range.end_offset
        item_text = text[start:end]
        
        old_id = data.id
        new_id = old_id + "_copy"
        item_text = item_text.replace(old_id, new_id, 1)
        
        if isinstance(data, ParsedDecisionCategory):
            self.widget.content = text.rstrip() + "\n\n" + item_text
        else:
            item = self.tree_decisions.currentItem()
            if item and item.parent():
                cat_node = item.parent().data(0, Qt.ItemDataRole.UserRole).node
                insertion_offset = cat_node.range.end_offset - 1
                self.widget.content = text[:insertion_offset] + "\n" + item_text + text[insertion_offset:]
            else:
                self.widget.content = text.rstrip() + "\n\n" + item_text
        
        self.refresh()

    def delete_item(self):
        data = self.get_current_data()
        if not data: return
        
        res = QMessageBox.question(self.widget, "確認", f"{data.id} を削除しますか？")
        if res != QMessageBox.StandardButton.Yes: return
        
        text = self.widget.content
        start = data.node.range.start_offset
        end = data.node.range.end_offset
        
        while start > 0 and text[start-1] in " \t": start -= 1
        if start > 0 and text[start-1] == "\n": start -= 1
        
        self.widget.content = text[:start] + text[end:]
        self.refresh()
            
    def browse_loc_file(self, target_edit):
        if not target_edit: return
        project_path = core.api.get_project_path()
        if not project_path: return
        
        loc_dir = os.path.join(project_path, "localisation")
        if not os.path.exists(loc_dir): return
        
        # ymlファイルを再帰的に検索
        loc_files = []
        for root, dirs, files in os.walk(loc_dir):
            for f in files:
                if f.endswith(".yml"):
                    # 相対パスを取得
                    rel = os.path.relpath(os.path.join(root, f), loc_dir)
                    loc_files.append(rel)
        
        if not loc_files:
            QMessageBox.information(self.widget, "情報", "ローカライズファイルが見つかりません。")
            return
            
        from PySide6.QtWidgets import QInputDialog
        file, ok = QInputDialog.getItem(self.widget, "ファイル選択", "翻訳先ファイルを選択してください:", loc_files, 0, False)
        if ok and file:
            target_edit.setText(file)
            # 必要に応じてここで保存ロジック（registryへの登録等）を呼ぶ

    def get_mod_root(self):
        return core.api.get_project_path() or os.path.dirname(self.file_path)

    def default_loc_filename(self):
        settings = self.get_plugin_settings()
        lang = settings.get("display_language", "l_japanese")
        fmt = settings.get("decision_loc_file_format", "decisions_{lang}.yml") or "decisions_{lang}.yml"
        data = self.get_current_data()
        category = data if isinstance(data, ParsedDecisionCategory) else None
        decision_id = data.id if isinstance(data, ParsedDecision) else ""
        if category is None and isinstance(data, ParsedDecision) and getattr(self, "tree_decisions", None):
            item = self.tree_decisions.currentItem()
            if item and item.parent():
                parent_data = item.parent().data(0, Qt.ItemDataRole.UserRole)
                if isinstance(parent_data, ParsedDecisionCategory):
                    category = parent_data
        filename = self.apply_format(
            fmt,
            **self.format_values(category=category, decision_id=decision_id, number=1, lang=lang),
        )
        return filename

    def selected_loc_filename(self, widget):
        filename = widget.text().strip() if widget and hasattr(widget, "text") else ""
        if not filename or not filename.lower().endswith(".yml"):
            filename = self.default_loc_filename()
        return filename

    def _get_loc_text(self, widget):
        if not widget:
            return ""
        if hasattr(widget, "toPlainText"):
            return widget.toPlainText()
        if hasattr(widget, "text"):
            return widget.text()
        return ""

    def save_localisation(self, key, text, loc_file_widget=None):
        if not key:
            return

        plugin = self.get_hoi4_plugin()
        if not plugin or not hasattr(plugin, "localisation_registry"):
            return

        registry = plugin.localisation_registry
        status, entry = registry.search_key_status(key)
        if status == "exists_in_hoi4":
            print(f"Skipping save for HOI4 internal key: {key}")
            return

        settings = self.get_plugin_settings()
        lang = settings.get("display_language", "l_japanese")

        if status in ("exists_in_mod", "duplicate") and entry:
            save_path = entry["file"]
            if os.path.exists(save_path):
                registry.update_file(save_path, "mod")
                status, entry = registry.search_key_status(key)
                if status == "exists_in_hoi4":
                    print(f"Skipping save for HOI4 internal key after refresh: {key}")
                    return
                if status in ("exists_in_mod", "duplicate") and entry:
                    save_path = entry["file"]
            else:
                registry.remove_file_entries(save_path)
                save_path = os.path.join(self.get_mod_root(), "localisation", self.selected_loc_filename(loc_file_widget))
        else:
            save_path = os.path.join(self.get_mod_root(), "localisation", self.selected_loc_filename(loc_file_widget))

        save_empty_loc = settings.get("save_empty_localisation", False)
        self._write_to_loc_file(save_path, key, text, lang, save_empty_loc)

        try:
            registry.update_file(save_path, "mod")
            registry.set_ignore_path(save_path, True)
        finally:
            QTimer.singleShot(500, lambda: registry.set_ignore_path(save_path, False))

    def _write_to_loc_file(self, path, key, text, lang, save_empty_loc=False):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        header = f"{lang}:"
        escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')
        new_line = f' {key}: "{escaped_text}"'

        lines = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()

        found_key_idx = -1
        has_header = False
        for i, line in enumerate(lines):
            if line.strip().startswith(header):
                has_header = True
            stripped = line.strip()
            if ":" in stripped and stripped.split(":", 1)[0] == key:
                found_key_idx = i

        if found_key_idx >= 0:
            if not text.strip() and not save_empty_loc:
                del lines[found_key_idx]
            else:
                lines[found_key_idx] = new_line + "\n"
        else:
            if not text.strip() and not save_empty_loc:
                return
            if not lines or not has_header:
                if not lines:
                    lines.append(header + "\n")
                else:
                    lines.insert(0, header + "\n")
            lines.append(new_line + "\n")

        with open(path, "w", encoding="utf-8-sig") as f:
            f.writelines(lines)

    def on_save_triggered(self):
        data = self.get_current_data()
        if isinstance(data, ParsedDecisionCategory):
            self.save_localisation(data.id, self._get_loc_text(self.edit_category_localisation), self.edit_category_loc_file)
            self.save_localisation(f"{data.id}_desc", self._get_loc_text(self.edit_category_desc_localisation), self.edit_category_desc_loc_file)
        elif isinstance(data, ParsedDecision):
            self.save_localisation(data.id, self._get_loc_text(self.edit_decision_localisation), self.edit_decision_loc_file)
            self.save_localisation(f"{data.id}_desc", self._get_loc_text(self.text_decision_desc_localisation), self.edit_decision_desc_loc_file)
            custom_cost_key = self._get_loc_text(self.edit_custom_cost_key).strip()
            if custom_cost_key:
                self.save_localisation(custom_cost_key, self._get_loc_text(self.text_custom_cost_localisation), self.edit_custom_cost_loc_file)
            
    def set_detailed_mode(self, enabled):
        self.is_detailed_mode = enabled
        for w in self.system_widgets:
            w.setVisible(enabled)
        
        if self.btn_standard_mode: self.btn_standard_mode.setChecked(not enabled)
        if self.btn_detail_mode: self.btn_detail_mode.setChecked(enabled)

    def on_text_focus_out(self, key, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.replace_property(key, edit.toPlainText())

    def connect_scalar(self, control, property_name):
        if not control: return
        if property_name in ("category_id", "decision_id"):
            control.editingFinished.connect(lambda: self.replace_item_id(control.text()))
        else:
            control.editingFinished.connect(lambda: self.replace_property(property_name, control.text()))

    def connect_text(self, control, property_name):
        if control:
            control.focusOutEvent = lambda e: self.on_text_focus_out(property_name, control, e)

    def connect_spin(self, control, property_name):
        if control:
            control.valueChanged.connect(lambda val: self.replace_property(property_name, str(val) if val > 0 else ""))

    def connect_bool(self, control, property_name):
        if control:
            def on_toggled(checked, name=property_name):
                if self.updating:
                    return
                settings = self.get_plugin_settings()
                val = "yes" if checked else ("no" if settings.get("explicit_no_export", False) else "")
                self.replace_property(name, val)
            control.toggled.connect(on_toggled)

    def replace_item_id(self, new_id):
        if self.updating or not new_id: return
        item = self.get_current_data()
        if not item: return
        
        text = self.widget.content
        node = item.node
        
        # key_range を使用して ID 部分を正確に置換
        if hasattr(node, "key_range"):
            key_start = node.key_range.start_offset
            key_end = node.key_range.end_offset
        else:
            # フォールバック
            key_start = node.range.start_offset
            key_end = key_start + len(item.id)
        
        self.widget.content = text[:key_start] + new_id + text[key_end:]
        self.refresh()

    def replace_property(self, property_name, replacement):
        if self.updating: return
        item = self.get_current_data()
        if not item: return
        
        path = item.source_path or self.file_path
        text = self.get_item_content(path)
        assignment = item.first(property_name)

        if not replacement:
            if assignment:
                start = assignment.range.start_offset
                end = assignment.range.end_offset
                while start > 0 and text[start-1] in " \t": start -= 1
                if start > 0 and text[start-1] == "\n": start -= 1
                new_text = text[:start] + text[end:]
                if path == self.file_path:
                    self.widget.content = new_text
                else:
                    self.file_contents[path] = new_text
                self.refresh()
            return

        is_object = self.is_object_property(property_name, item)
        indent_level = 1 if isinstance(item, ParsedDecisionCategory) else 2
        tabs = "\t" * indent_level
        inner_tabs = "\t" * (indent_level + 1)

        if is_object:
            # 内部の行にインデントを付与
            lines = [inner_tabs + line.strip() if line.strip() else "" for line in replacement.splitlines()]
            indented = "\n".join(lines)
            formatted_val = f"{{\n{indented}\n{tabs}}}"
        else:
            formatted_val = replacement

        if assignment:
            val_range = assignment.value.range
            new_text = text[:val_range.start_offset] + formatted_val + text[val_range.end_offset:]
        else:
            insertion_offset = item.node.range.end_offset - 1
            new_prop = f"\n{tabs}{property_name} = {formatted_val}\n"
            new_text = text[:insertion_offset] + new_prop + text[insertion_offset:]
            
        if path == self.file_path:
            self.widget.content = new_text
        else:
            self.file_contents[path] = new_text
            
        # 整形を強制するために、一度バッファを更新してから再描画
        self.reformat_item(item.id, path)

    def is_object_property(self, prop_name, item):
        # 基本的なフォールバック
        defaults = {"allowed", "visible", "available", "complete_effect", "modifier", 
                    "highlight_states", "highlight_provinces", "custom_cost_trigger",
                    "on_map_area", "map_area"}
        if prop_name in defaults:
            return True
            
        # スキーマをチェック
        schema = getattr(self.parser, "schema", {})
        schemas = schema.get("schemas", {})
        
        type_name = "category" if isinstance(item, ParsedDecisionCategory) else "decision"
        props = schemas.get(type_name, {}).get("properties", {})
        
        if prop_name in props:
            return props[prop_name].get("type") == "object"
            
        return False

    def reformat_item(self, item_id, path):
        # メモリ上のデータから再度パースして最新の状態を取得
        text = self.get_item_content(path)
        doc = self.parser.parse_document(path, text)
        
        # 対象のアイテムを探す
        target = None
        for cat in doc.categories:
            if cat.id == item_id:
                target = cat
                break
            for dec in cat.decisions:
                if dec.id == item_id:
                    target = dec
                    break
        
        if not target: return
        
        type_name = "category" if isinstance(target, ParsedDecisionCategory) else "decision"
        
        # インデントレベルの決定
        indent_level = 1 if isinstance(target, ParsedDecisionCategory) else 2
        tabs = "\t" * indent_level
        
        # ブロックの中身を再構築
        config = self.format_config.get(type_name, {})
        key_order = config.get("key_order", [])
        
        # 既存のノードを辞書に整理
        nodes = {}
        if isinstance(target.node.value, ObjectNode):
            for item in target.node.value.items:
                if isinstance(item, AssignmentNode):
                    nodes[item.key] = item
        
        lines = []
        used_keys = set()
        
        # 定義された順序に従って追加（空行対応）
        for key in key_order:
            if key == "": # 空行（スペーサー）
                if lines and lines[-1] != "": # 連続する空行を避ける
                    lines.append("")
                continue
                
            if key in nodes:
                formatted = self.format_ast_node(nodes[key], indent_level)
                if formatted:
                    lines.append(f"{tabs}{formatted}")
                used_keys.add(key)
        
        # 定義にないキーを末尾に追加
        for key, node in nodes.items():
            if key not in used_keys:
                formatted = self.format_ast_node(node, indent_level)
                if formatted:
                    if lines and lines[-1] != "": # 未知のキーの前に空行を挟む（任意）
                         # lines.append("") # 好みに応じて
                         pass
                    lines.append(f"{tabs}{formatted}")
        
        # 末尾の空行を削除
        while lines and lines[-1] == "":
            lines.pop()
        
        inner_text = "\n".join(lines)
        node_range = target.node.value.range
        new_text = text[:node_range.start_offset + 1] + "\n" + inner_text + "\n" + ("\t" * (indent_level-1)) + text[node_range.end_offset - 1:]
        
        if path == self.file_path:
            self.widget.content = new_text
        else:
            self.file_contents[path] = new_text
        self.refresh()

    def format_ast_node(self, node, indent_level):
        if isinstance(node, AssignmentNode):
            val = self.format_ast_node(node.value, indent_level)
            return f"{node.key} = {val}" if val else ""
        if isinstance(node, ScalarNode):
            return node.raw
        if isinstance(node, ObjectNode):
            tabs = "\t" * (indent_level + 1)
            inner_lines = []
            for item in node.items:
                if isinstance(item, AssignmentNode):
                    val = self.format_ast_node(item.value, indent_level + 1)
                    inner_lines.append(f"{tabs}{item.key} = {val}")
            
            close_tabs = "\t" * indent_level
            return "{\n" + "\n".join(inner_lines) + f"\n{close_tabs}}}"
        return ""

    def get_current_data(self) -> Optional[Any]:
        if not self.tree_decisions: return None
        item = self.tree_decisions.currentItem()
        if not item: return None
        return item.data(0, Qt.ItemDataRole.UserRole)

# ユーティリティ関数

def find(widget, cls, name):
    return widget.findChild(cls, name)

def set_line(control, value):
    if control:
        was_blocked = control.blockSignals(True)
        control.setText(value or "")
        control.blockSignals(was_blocked)

def set_plain(control, value):
    if control:
        was_blocked = control.blockSignals(True)
        control.setPlainText(value or "")
        control.blockSignals(was_blocked)

def set_spin(control, value):
    if control:
        was_blocked = control.blockSignals(True)
        try:
            control.setValue(int(value or 0))
        except Exception:
            control.setValue(0)
        control.blockSignals(was_blocked)

def set_checked(control, value):
    if control:
        was_blocked = control.blockSignals(True)
        control.setChecked(bool(value))
        control.blockSignals(was_blocked)

def prop_text(item: Any, name: str) -> str:
    return scalar_text(item.first(name)) if item else ""

def prop_bool(item: Any, name: str) -> bool:
    assignment = item.first(name) if item else None
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return False
    if assignment.value.value_type == "bool":
        return bool(assignment.value.value)
    return str(assignment.value.raw).lower() in {"yes", "true"}

def scalar_text(assignment: Optional[AssignmentNode]) -> str:
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return ""
    return str(assignment.value.value)

def block_text(content: str, node: Optional[AssignmentNode], name: str) -> str:
    if not node or not isinstance(node.value, ObjectNode): return ""
    
    target = None
    for item in node.value.items:
        if isinstance(item, AssignmentNode) and item.key == name:
            target = item
            break
    
    if not target: return ""
    
    val = target.value
    if isinstance(val, ObjectNode):
        inner = content[val.range.start_offset + 1 : val.range.end_offset - 1]
        return inner.strip("\r\n\t ")
    
    return content[val.range.start_offset : val.range.end_offset]
