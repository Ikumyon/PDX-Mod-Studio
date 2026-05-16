from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import core.api
from PySide6.QtCore import QFile, Qt, QEvent, QObject
from PySide6.QtGui import QColor, QAction
from PySide6.QtWidgets import (
    QColorDialog,
    QGroupBox,
    QLineEdit,
    QListWidget,
    QMenu,
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

    def parse_project(self, project_path: str) -> list[ParsedAchievement]:
        achievements = []
        scan_dir = os.path.join(project_path, "common", "achievements")
        if not os.path.exists(scan_dir):
            return []

        all_files = []
        for root, _, files in os.walk(scan_dir):
            for file in files:
                if file.endswith(".txt"):
                    all_files.append(os.path.join(root, file))

        total_files = len(all_files)
        for i, path in enumerate(all_files):
            progress = int((i / total_files) * 100)
            core.api.set_progress(progress, f"Parsing achievements: {os.path.basename(path)}")
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    doc = self.parse_document(path, f.read())
                    achievements.extend(doc.achievements)
            except Exception:
                continue
        
        core.api.set_progress(100, "")
        
        # キャッシュへの保存
        plugin = core.api.get_active_plugin()
        if plugin:
            if not hasattr(plugin, "project_cache"):
                plugin.project_cache = {}
            plugin.project_cache["achievements"] = self.serialize_achievements(achievements)
            
        return achievements

    def serialize_achievements(self, achievements: list[ParsedAchievement]) -> list[dict]:
        return [{"id": ach.id, "source_path": ach.source_path} for ach in achievements]

    def deserialize_achievements(self, data: list[dict]) -> list[ParsedAchievement]:
        from plugins.hoi4.script_parser import ParsedEntity
        achievements = []
        for ach_data in data:
            entity = ParsedEntity(
                schema_name="hoi4_achievement",
                id=ach_data["id"],
                parent_id=None,
                source_path=ach_data["source_path"]
            )
            achievements.append(ParsedAchievement(entity))
        return achievements

def setup(widget, file_path, content):
    controller = AchievementEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    # core側から呼ばれるインターフェース
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    widget.setParams = controller.set_params
    
    # 初期解析とバインド
    controller.bind()
    
    # 変更検知の接続
    controller.connect_change_signals()
    
    # 保存トリガーの紐付け
    widget.on_save_triggered = controller.on_save_triggered
    
    # エディタの準備が完了したことを本体に通知
    # これにより、本体側から widget.setParams() が呼び出される
    core.api.notify_editor_ready(widget)

class AchievementEditorController(QObject):
    def __init__(self, widget, file_path, content):
        super().__init__()
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

        self.not_eligible_icon = self.widget.findChild(QLineEdit, "notEligibleIconPathEdit")

        # リボン表示切り替えメニューの設定
        self.ribbon_group = self.widget.findChild(QGroupBox, "ribbonGroup")
        
        self.btn_toggle_advanced = self.widget.findChild(QPushButton, "btnToggleAdvancedAchievement")
        if self.btn_toggle_advanced and self.ribbon_group:
            self.advanced_menu = QMenu(self.widget)
            self.action_show_ribbon = QAction("リボンを表示", self.advanced_menu)
            self.action_show_ribbon.setCheckable(True)
            self.action_show_ribbon.setChecked(False)
            self.ribbon_group.setVisible(False)
            self.action_show_ribbon.triggered.connect(lambda checked: self.ribbon_group.setVisible(checked))
            self.advanced_menu.addAction(self.action_show_ribbon)
            self.btn_toggle_advanced.setMenu(self.advanced_menu)
            self.advanced_menu.installEventFilter(self)

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

    def get_mod_root(self) -> str:
        """プロジェクトのルートパスを取得する"""
        path = core.api.get_project_path()
        if path:
            return path
        return os.path.dirname(self.file_path)

    def get_plugin_settings(self):
        """設定を取得する（暫定的に空辞書）"""
        return {}

    def on_save_triggered(self):
        """保存実行時に呼ばれる。スクリプトとローカリゼーションを保存する"""
        ach = self.current_achievement()
        if not ach:
            return False

        # 1. スクリプト（.txt）の更新
        self.update_script_content()

        # 2. ローカリゼーションの保存
        # タイトル: ID_NAME
        title_text = self.achievement_title.text() if self.achievement_title else ""
        self.save_localisation(f"{ach.id}_NAME", title_text, self.title_loc_path)
        
        # 説明: ID_DESC
        desc_text = self.achievement_desc.toPlainText() if self.achievement_desc else ""
        self.save_localisation(f"{ach.id}_DESC", desc_text, self.desc_loc_path)

        self.widget.is_dirty = False
        print(f"Achievement saved: {ach.id}")
        return True

    def connect_change_signals(self):
        """フォームの変更を検知して is_dirty をセットする"""
        fields = [
            self.achievement_id, self.achievement_title, 
            self.possible_cond, self.happened_cond,
            self.frame_x, self.frame_y, self.frame_style
        ]
        for field in fields:
            if not field: continue
            if hasattr(field, "textChanged"):
                field.textChanged.connect(self.on_form_changed)
            elif hasattr(field, "valueChanged"):
                field.valueChanged.connect(self.on_form_changed)
        
        if self.achievement_desc:
            self.achievement_desc.textChanged.connect(self.on_form_changed)
            
        for cw in self.color_widgets:
            cw["r"].valueChanged.connect(self.on_form_changed)
            cw["g"].valueChanged.connect(self.on_form_changed)
            cw["b"].valueChanged.connect(self.on_form_changed)

    def on_form_changed(self):
        if self.updating: return
        self.widget.is_dirty = True

    def update_script_content(self):
        """現在のフォーム入力内容からスクリプト文字列を再構成し、widget.content を更新する"""
        ach = self.current_achievement()
        if not ach or not ach.node:
            return

        new_id = self.achievement_id.text()
        possible = self.possible_cond.toPlainText()
        happened = self.happened_cond.toPlainText()
        
        # 実績ブロックの構築
        lines = []
        lines.append(f"{new_id} = {{")
        
        if possible.strip():
            lines.append("\tpossible = {")
            for line in possible.splitlines():
                lines.append(f"\t\t{line}")
            lines.append("\t}")
        
        if happened.strip():
            lines.append("\thappened = {")
            for line in happened.splitlines():
                lines.append(f"\t\t{line}")
            lines.append("\t}")

        # リボンの再構成
        if self.ribbon_group and self.ribbon_group.isVisible():
            lines.append("\tribbon = {")
            lines.append("\t\tframe = {")
            lines.append(f"\t\t\t{self.frame_x.value()} {self.frame_y.value()} {self.frame_style.value()}")
            lines.append("\t\t}")
            lines.append("\t\tcolors = {")
            for cw in self.color_widgets:
                lines.append(f"\t\t\t{{ {cw['r'].value()} {cw['g'].value()} {cw['b'].value()} }}")
            lines.append("\t\t}")
            lines.append("\t}")
            
        lines.append("}")
        new_block = "\n".join(lines)

        # 元のテキストの該当範囲を置換
        content = self.widget.content
        start = ach.node.range.start_offset
        end = ach.node.range.end_offset
        
        new_content = content[:start] + new_block + content[end:]
        
        # 反映（これにより再解析が走る）
        self.set_content(new_content)

    def current_achievement(self):
        """現在選択されている実績オブジェクトを返す"""
        if not self.achievement_list or not self.achievements:
            return None
        idx = self.achievement_list.currentRow()
        if 0 <= idx < len(self.achievements):
            return self.achievements[idx]
        return None

    def save_localisation(self, key, text, loc_file_widget=None):
        """ローカライズ情報を適切なファイルに保存する"""
        if not key: return
        
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
        
        # 保存先パスの決定
        if (status == "exists_in_mod" or status == "duplicate") and entry:
            save_path = entry["file"]
        else:
            # 新規キーの場合は指定されたファイル名またはデフォルトに保存
            filename = loc_file_widget.text() if loc_file_widget and loc_file_widget.text() else ""
            if not filename.lower().endswith(".yml"):
                filename = "achievements_l_japanese.yml"
            
            project_path = core.api.get_project_path()
            if not project_path: return
            save_path = os.path.join(project_path, "localisation", "japanese", filename)

        self._write_to_loc_file(save_path, key, text, lang)
        
        # レジストリを即時更新
        registry.update_file(save_path, "mod")

    def _write_to_loc_file(self, path, key, text, lang):
        """YAMLファイルへの書き込み実処理"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        header = f"{lang}:"
        # エスケープ処理
        escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')
        new_line = f' {key}: "{escaped_text}"'
        
        lines = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8-sig') as f:
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
            lines[found_key_idx] = new_line + "\n"
        else:
            # 新規キーの追記
            if not lines or not has_header:
                if not lines: lines.append(header + "\n")
                else: lines.insert(0, header + "\n")
            lines.append(new_line + "\n")

        with open(path, 'w', encoding='utf-8-sig') as f:
            f.writelines(lines)

    def set_content(self, content):
        self.widget.content = content
        self.refresh()
        self.widget.is_dirty = False

    def set_params(self, params):
        """外部から渡されたパラメータ（target_id等）を処理する"""
        if not params:
            return
        
        target_id = params.get("target_id")
        if target_id and self.achievement_list:
            # リスト内を検索して選択を切り替える
            # 注意: refresh() が完了して self.achievements が構築されている必要がある
            for i in range(len(self.achievements)):
                if self.achievements[i].id == target_id:
                    self.achievement_list.setCurrentRow(i)
                    break

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
                    # ID_NAME を優先、なければ ID で検索
                    entry = None
                    if registry:
                        _, entry = registry.search_key_status(f"{ach.id}_NAME")
                        if not entry:
                            _, entry = registry.search_key_status(ach.id)
                    
                    label = entry.get("value") if entry else ach.id
                    self.achievement_list.addItem(label)
                
                if self.achievement_list.count() > 0:
                    self.achievement_list.setCurrentRow(0)
        finally:
            self.updating = False
        
        # 初期選択やリフレッシュ後の項目表示を確実にするため、明示的にロードを走らせる
        if self.achievement_list and self.achievement_list.currentRow() >= 0:
            self.on_selection_changed(self.achievement_list.currentRow())

    def on_selection_changed(self, index):
        if self.updating or index < 0 or index >= len(self.achievements):
            return
        self.load_achievement(self.achievements[index])

    def load_achievement(self, ach: ParsedAchievement):
        self.updating = True
        try:
            # ローカライズレジストリの取得
            plugin = self.get_hoi4_plugin()
            registry = getattr(plugin, "localisation_registry", None) if plugin else None

            # 基本情報
            if self.achievement_id:
                self.achievement_id.setText(ach.id)
            
            if registry:
                project_path = core.api.get_project_path()
                loc_root = os.path.normpath(os.path.join(project_path, "localisation")) if project_path else ""

                # タイトル: ID_NAME を優先
                _, title_entry = registry.search_key_status(f"{ach.id}_NAME")
                if not title_entry:
                    _, title_entry = registry.search_key_status(ach.id)
                
                if self.achievement_title:
                    self.achievement_title.setText(title_entry.get("value") if title_entry else "")
                
                if self.title_loc_path:
                    abs_path = title_entry.get("file") if title_entry else ""
                    if abs_path and loc_root:
                        try:
                            rel_path = os.path.relpath(abs_path, loc_root).replace("\\", "/")
                            self.title_loc_path.setText(rel_path)
                        except ValueError:
                            self.title_loc_path.setText(abs_path)
                    else:
                        self.title_loc_path.setText(abs_path)
                
                # 説明: ID_DESC を優先
                _, desc_entry = registry.search_key_status(f"{ach.id}_DESC")
                if not desc_entry:
                    _, desc_entry = registry.search_key_status(f"{ach.id}_desc")
                
                if self.achievement_desc:
                    self.achievement_desc.setPlainText(desc_entry.get("value") if desc_entry else "")
                
                if self.desc_loc_path:
                    abs_path = desc_entry.get("file") if desc_entry else ""
                    if abs_path and loc_root:
                        try:
                            rel_path = os.path.relpath(abs_path, loc_root).replace("\\", "/")
                            self.desc_loc_path.setText(rel_path)
                        except ValueError:
                            self.desc_loc_path.setText(abs_path)
                    else:
                        self.desc_loc_path.setText(abs_path)

            # 条件
            if self.possible_cond:
                self.possible_cond.setPlainText(self.get_block_content(ach, "possible"))
            if self.happened_cond:
                self.happened_cond.setPlainText(self.get_block_content(ach, "happened"))
            
            # リボン (Frame)
            ribbon_node = ach.first("ribbon")
            has_ribbon = ribbon_node is not None and isinstance(ribbon_node.value, ObjectNode)
            
            # データがある場合のみ表示、ない場合は非表示（メニューの状態も更新）
            if hasattr(self, "action_show_ribbon") and self.action_show_ribbon:
                self.action_show_ribbon.setChecked(has_ribbon)
            if self.ribbon_group:
                self.ribbon_group.setVisible(has_ribbon)

            if has_ribbon:
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

    def eventFilter(self, obj, event):
        # メニューのアイテムをクリックしたときに閉じないようにする処理
        if (isinstance(obj, QMenu) and event.type() == QEvent.Type.MouseButtonRelease):
            action = obj.actionAt(event.pos())
            if action and action.isCheckable():
                action.trigger()
                return True
        return super().eventFilter(obj, event)
