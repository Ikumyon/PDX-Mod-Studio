from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, field

import core.api
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPen, QPixmap, QTextOption
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QLineEdit,
    QListWidget,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
)

from plugins.hoi4.script_parser import (
    AssignmentNode,
    ObjectNode,
    ScalarNode,
)
from plugins.hoi4.base_editor import (
    BaseDocument,
    BaseEditorController,
    BaseParsedEntity,
    BaseParser,
)

class ParsedAchievement(BaseParsedEntity):
    pass

@dataclass
class AchievementDocument(BaseDocument):
    achievements: list[ParsedAchievement] = field(default_factory=list)

class AchievementPreviewClickItem(QGraphicsRectItem):
    def __init__(self, controller, achievement_index: int, width: int, height: int, parent=None):
        super().__init__(0, 0, width, height, parent)
        self.controller = controller
        self.achievement_index = achievement_index
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(100)

    def mousePressEvent(self, event):
        self.controller.set_current_achievement_index(self.achievement_index)
        self.controller.update_preview()
        event.accept()

class AchievementParser(BaseParser):
    document_class = AchievementDocument
    entity_class = ParsedAchievement
    collection_attr = "achievements"
    project_subdir = os.path.join("common", "achievements")
    progress_label = "Parsing achievements"
    cache_key = "achievements"

    def __init__(self):
        base_dir = os.path.dirname(__file__)
        schema_path = os.path.join(base_dir, "achievement_schema.json")
        super().__init__(schema_path)

    def extract_document_properties(self, doc: AchievementDocument, ast, path: str) -> None:
        # ファイルレベルのプロパティの抽出
        for item in getattr(ast, "items", []):
            if isinstance(item, AssignmentNode):
                if item.key == "unique_id" and isinstance(item.value, ScalarNode):
                    doc.properties["unique_id"] = str(item.value.value)
                    doc.properties["unique_id_node"] = item
                elif item.key == "group_name" and isinstance(item.value, ScalarNode):
                    doc.properties["group_name"] = str(item.value.value)
                    doc.properties["group_name_node"] = item
                elif item.key == "loc_path" and isinstance(item.value, ScalarNode):
                    doc.properties["loc_path"] = str(item.value.value)
                    doc.properties["loc_path_node"] = item
    def parse_project(self, project_path: str) -> list[ParsedAchievement]:
        return super().parse_project(project_path)

    def serialize_project_items(self, items: list[ParsedAchievement]) -> list[dict]:
        return self.serialize_achievements(items)

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

class AchievementEditorController(BaseEditorController):
    ELEMENT_ID = "achievement"
    DEFAULT_FORMAT_FILE = "achievement_format.json"

    def __init__(self, widget, file_path, content):
        super().__init__(widget, file_path, content)
        self.achievements: list[ParsedAchievement] = []
        self.parser = AchievementParser()
        self.preview_items = []

    def bind(self):
        # UIウィジェットの取得
        self.achievement_list = self.find(QListWidget, "achievementList")
        self.achievement_tree = self.find(QTreeWidget, "achievementTree")
        self.preview_graphics = self.find(QGraphicsView, "previewGraphicsView")

        if self.preview_graphics:
            self.preview_scene = QGraphicsScene()
            self.preview_graphics.setScene(self.preview_scene)
            self.preview_graphics.setBackgroundBrush(QBrush(QColor("#111410")))
            self.preview_graphics.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.preview_graphics.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            self.preview_graphics.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        
        # ファイル設定
        self.stacked_editor = self.find(QStackedWidget, "stackedEditor")
        self.file_unique_id = self.widget.findChild(QLineEdit, "fileUniqueIdEdit")
        self.file_group_name = self.widget.findChild(QLineEdit, "fileGroupNameEdit")
        self.file_loc_path = self.widget.findChild(QLineEdit, "fileLocPathEdit")
        self.file_loc_path_browse_button = self.widget.findChild(QPushButton, "fileLocPathBrowseButton")
        
        if self.file_loc_path_browse_button:
            self.file_loc_path_browse_button.clicked.connect(self.browse_loc_file)
        
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

        self.completed_icon = self.widget.findChild(QLineEdit, "completedIconPathEdit")
        self.possible_icon = self.widget.findChild(QLineEdit, "possibleIconPathEdit")
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
        if self.achievement_tree:
            self.achievement_tree.setHeaderHidden(True)
            self.achievement_tree.currentItemChanged.connect(self.on_tree_selection_changed)

        # 初期リフレッシュ
        self.refresh()
        
        # ローカリゼーション更新の監視
        core.api.register_loc_changed_handler(self.refresh)

    def browse_loc_file(self):
        if not self.file_loc_path:
            return
        project_path = core.api.get_project_path()
        loc_dir = os.path.join(project_path, "localisation") if project_path else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self.widget,
            "ローカリゼーションファイルの選択",
            loc_dir,
            "YAML Files (*.yml)"
        )
        if file_path:
            if loc_dir:
                try:
                    rel_path = os.path.relpath(file_path, loc_dir).replace("\\", "/")
                    self.file_loc_path.setText(rel_path)
                except ValueError:
                    self.file_loc_path.setText(file_path)
            else:
                self.file_loc_path.setText(file_path)

    def load_file_settings(self):
        self.updating = True
        try:
            if self.stacked_editor:
                self.stacked_editor.setCurrentIndex(0)
            
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            
            # 生の unique_id
            unique_id = doc.properties.get("unique_id", "")
            if self.file_unique_id:
                self.file_unique_id.setText(unique_id)
            
            # ローカリゼーション (実績グループ名 と 保存先)
            plugin = self.get_hoi4_plugin()
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
            
            group_name = ""
            loc_path = ""
            if registry and unique_id:
                _, entry = registry.search_key_status(unique_id)
                if entry:
                    group_name = entry.get("value") or ""
                    abs_path = entry.get("file") or ""
                    project_path = core.api.get_project_path()
                    loc_root = os.path.normpath(os.path.join(project_path, "localisation")) if project_path else ""
                    if abs_path and loc_root:
                        try:
                            loc_path = os.path.relpath(abs_path, loc_root).replace("\\", "/")
                        except ValueError:
                            loc_path = abs_path
                    else:
                        loc_path = abs_path
            
            if self.file_group_name:
                self.file_group_name.setText(group_name)
            if self.file_loc_path:
                self.file_loc_path.setText(loc_path)
        finally:
            self.updating = False

    def on_save_triggered(self):
        """保存実行時に呼ばれる。スクリプトとローカリゼーションを保存する"""
        idx = self.current_achievement_index()
        if idx == -2:
            # 1. ファイル設定の保存
            self.update_file_settings_content()
            
            unique_id = self.file_unique_id.text().strip() if self.file_unique_id else ""
            group_name = self.file_group_name.text().strip() if self.file_group_name else ""
            
            if unique_id and group_name:
                self.save_localisation(unique_id, group_name, self.file_loc_path)
                
            self.widget.is_dirty = False
            print("File settings saved")
            self.refresh()
            self.set_current_achievement_index(-2)
            return True
            
        elif idx >= 0:
            ach = self.achievements[idx]
            # 1. スクリプト（.txt）の更新
            self.update_script_content()

            # 2. ローカリゼーションの保存
            # タイトル: ID_NAME
            localisation_id = self.achievement_id.text().strip() if self.achievement_id else ach.id
            title_text = self.achievement_title.text() if self.achievement_title else ""
            self.save_localisation(f"{localisation_id}_NAME", title_text, self.title_loc_path)
            
            # 説明: ID_DESC
            desc_text = self.achievement_desc.toPlainText() if self.achievement_desc else ""
            self.save_localisation(f"{localisation_id}_DESC", desc_text, self.desc_loc_path)

            self.widget.is_dirty = False
            print(f"Achievement saved: {localisation_id}")
            self.refresh()
            self.set_current_achievement_index(idx)
            return True
            
        return False

    def connect_change_signals(self):
        """フォームの変更を検知して is_dirty をセットする"""
        fields = [
            self.achievement_id, self.achievement_title, 
            self.possible_cond, self.happened_cond,
            self.frame_x, self.frame_y, self.frame_style,
            self.file_unique_id, self.file_group_name, self.file_loc_path,
            self.completed_icon, self.possible_icon, self.not_eligible_icon,
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
        self.update_preview_delayed()

    def update_script_content(self):
        """現在のフォーム入力内容からスクリプト文字列を再構成し、widget.content を更新する"""
        ach = self.current_achievement()
        if not ach or not ach.node:
            return

        new_id = self.achievement_id.text().strip()
        possible = self.possible_cond.toPlainText().strip()
        happened = self.happened_cond.toPlainText().strip()
        
        # フォーマット設定の取得
        config = self.format_config.get("achievement", {})
        key_order = config.get("key_order", ["possible", "happened", "ribbon"])
        
        ribbon_config = self.format_config.get("ribbon", {})
        ribbon_key_order = ribbon_config.get("key_order", ["frame", "colors"])

        # 各ブロックのテキスト表現を用意
        blocks = {}
        
        if possible:
            indented_possible = "\n".join([f"\t\t{line}" if line.strip() else line for line in possible.splitlines()])
            blocks["possible"] = f"possible = {{\n{indented_possible}\n\t}}"
            
        if happened:
            indented_happened = "\n".join([f"\t\t{line}" if line.strip() else line for line in happened.splitlines()])
            blocks["happened"] = f"happened = {{\n{indented_happened}\n\t}}"
            
        if self.ribbon_group and self.ribbon_group.isVisible():
            ribbon_lines = []
            
            # ribbon内の要素を並び替え
            for r_key in ribbon_key_order:
                if r_key == "frame":
                    ribbon_lines.append(f"\t\tframe = {{\n\t\t\t{self.frame_x.value()} {self.frame_y.value()} {self.frame_style.value()}\n\t\t}}")
                elif r_key == "colors":
                    colors_lines = []
                    colors_lines.append("\t\tcolors = {")
                    for cw in self.color_widgets:
                        colors_lines.append(f"\t\t\t{{ {cw['r'].value()} {cw['g'].value()} {cw['b'].value()} }}")
                    colors_lines.append("\t\t}")
                    ribbon_lines.append("\n".join(colors_lines))
            
            blocks["ribbon"] = f"ribbon = {{\n" + "\n".join(ribbon_lines) + "\n\t}"

        # キーオーダーに従って実績ブロックを組み立て
        lines = []
        lines.append(f"{new_id} = {{")
        
        for key in key_order:
            if key == "":
                # 空文字列は空行を意味する
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            if key in blocks:
                lines.append(f"\t{blocks[key]}")
        
        # key_orderに含まれていなかったが値があるものを最後に追加
        for key, block_val in blocks.items():
            if key not in key_order:
                lines.append(f"\t{block_val}")

        # 末尾の空行を削除
        while lines and lines[-1] == "":
            lines.pop()

        lines.append("}")
        new_block = "\n".join(lines)

        # 元のテキストの該当範囲を置換
        content = self.widget.content
        start = ach.node.range.start_offset
        end = ach.node.range.end_offset
        
        new_content = content[:start] + new_block + content[end:]
        
        # 反映（これにより再解析が走る）
        self.set_content(new_content)

    def update_file_settings_content(self):
        """ファイル設定の入力値（unique_id, group_name, loc_path）をファイルに更新する"""
        new_unique_id = self.file_unique_id.text().strip() if self.file_unique_id else ""
        new_group_name = self.file_group_name.text().strip() if self.file_group_name else ""
        new_loc_path = self.file_loc_path.text().strip() if self.file_loc_path else ""
        
        # 最新のASTからノードの位置情報を取得する
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        content = self.widget.content
        
        properties = [
            ("unique_id", new_unique_id),
            ("group_name", new_group_name),
            ("loc_path", new_loc_path)
        ]
        
        for key, val in properties:
            doc = self.parser.parse_document(self.file_path, content)
            node = doc.properties.get(f"{key}_node")
            
            if node:
                start = node.range.start_offset
                end = node.range.end_offset
                new_block = f"{key} = {val}"
                content = content[:start] + new_block + content[end:]
            else:
                if val:
                    new_block = f"{key} = {val}\n"
                    content = new_block + content
                    
        self.set_content(content)

    def current_achievement(self):
        """現在選択されている実績オブジェクトを返す"""
        if not self.achievements:
            return None
        idx = self.current_achievement_index()
        if idx >= 0 and idx < len(self.achievements):
            return self.achievements[idx]
        return None

    def current_achievement_index(self):
        if self.achievement_tree:
            item = self.achievement_tree.currentItem()
            if item:
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if data == "file_settings":
                    return -2
                if data is not None:
                    return int(data)
        if self.achievement_list:
            row = self.achievement_list.currentRow()
            if row == 0:
                return -2
            elif row > 0:
                return row - 1
        return -1

    def set_current_achievement_index(self, index: int):
        if self.achievement_tree:
            if index == -2:
                item = self.achievement_tree.topLevelItem(0)
            else:
                root_item = self.achievement_tree.topLevelItem(0)
                if root_item:
                    item = root_item.child(index)
                else:
                    item = None
            if item:
                self.achievement_tree.setCurrentItem(item)
        if self.achievement_list:
            if index == -2:
                self.achievement_list.setCurrentRow(0)
            else:
                self.achievement_list.setCurrentRow(index + 1)

    def selected_loc_path(self, loc_file_widget=None):
        filename = loc_file_widget.text().strip() if loc_file_widget and loc_file_widget.text() else ""
        if not filename.lower().endswith(".yml"):
            filename = "japanese/achievements_l_japanese.yml"

        if os.path.isabs(filename):
            return filename

        project_path = core.api.get_project_path()
        if not project_path:
            return ""

        normalised = filename.replace("\\", "/")
        if "/" not in normalised:
            normalised = f"japanese/{normalised}"
        return os.path.join(project_path, "localisation", *normalised.split("/"))

    def set_params(self, params):
        """外部から渡されたパラメータ（target_id等）を処理する"""
        if not params:
            return
        
        target_id = params.get("target_id")
        if target_id == "file_settings":
            self.set_current_achievement_index(-2)
        elif target_id:
            # リスト内を検索して選択を切り替える
            # 注意: refresh() が完了して self.achievements が構築されている必要がある
            for i in range(len(self.achievements)):
                if self.achievements[i].id == target_id:
                    self.set_current_achievement_index(i)
                    break

    def refresh(self):
        self.updating = True
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            self.achievements = doc.achievements
            
            # ローカライズレジストリの取得
            plugin = self.get_hoi4_plugin()
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
            
            labels = []
            for ach in self.achievements:
                entry = None
                if registry:
                    _, entry = registry.search_key_status(f"{ach.id}_NAME")
                    if not entry:
                        _, entry = registry.search_key_status(ach.id)
                labels.append(entry.get("value") if entry else ach.id)

            # ファイル設定（親ノード）のラベル決定
            unique_id = doc.properties.get("unique_id", "")
            root_label = unique_id
            if registry and unique_id:
                _, root_entry = registry.search_key_status(unique_id)
                if root_entry and root_entry.get("value"):
                    root_label = root_entry.get("value")
            
            if not root_label:
                root_label = os.path.basename(self.file_path)

            if self.achievement_list:
                self.achievement_list.clear()
                self.achievement_list.addItem(root_label)
                for label in labels:
                    self.achievement_list.addItem(label)

            if self.achievement_tree:
                self.achievement_tree.clear()
                root_item = QTreeWidgetItem([root_label])
                root_item.setData(0, Qt.ItemDataRole.UserRole, "file_settings")
                self.achievement_tree.addTopLevelItem(root_item)
                
                for i, label in enumerate(labels):
                    item = QTreeWidgetItem([label])
                    item.setData(0, Qt.ItemDataRole.UserRole, i)
                    root_item.addChild(item)
                
                root_item.setExpanded(True)

            self.set_current_achievement_index(-2)
        finally:
            self.updating = False
        
        current_index = self.current_achievement_index()
        self.on_selection_changed(current_index)

    def on_selection_changed(self, index):
        if self.updating:
            return
        if index == -2:
            self.load_file_settings()
        elif 0 <= index < len(self.achievements):
            self.load_achievement(self.achievements[index])
        self.update_preview()

    def on_tree_selection_changed(self, current, previous):
        if not current:
            return
        self.on_selection_changed(self.current_achievement_index())

    def load_achievement(self, ach: ParsedAchievement):
        self.updating = True
        try:
            if self.stacked_editor:
                self.stacked_editor.setCurrentIndex(1)
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

    def update_preview_delayed(self):
        if not hasattr(self, "preview_timer"):
            self.preview_timer = QTimer()
            self.preview_timer.setSingleShot(True)
            self.preview_timer.timeout.connect(self.update_preview)
        self.preview_timer.start(150)

    def update_preview(self):
        if self.updating or not hasattr(self, "preview_scene"):
            return

        self.preview_scene.clear()
        self.preview_items = []

        if not self.achievements:
            self.draw_preview_empty()
            return

        width = 900
        margin = 22
        header_height = 82
        card_w = 198
        card_h = 148
        gap = 12
        columns = 4
        visible_achievements = self.achievements
        rows = max(1, (len(visible_achievements) + columns - 1) // columns)
        height = header_height + rows * (card_h + gap) + margin

        frame = QGraphicsRectItem(0, 0, width, height)
        frame.setBrush(QBrush(QColor("#181916")))
        frame.setPen(QPen(QColor("#3d382d"), 2))
        self.preview_scene.addItem(frame)
        self.preview_items.append(frame)

        self.draw_preview_tabs(frame, width)
        title = self.group_title_for_preview()
        self.add_preview_text(frame, self.hoi4_preview_html(title), margin + 6, 52, width - margin * 2, 18, "#f7f3e8", True, html_text=True)

        selected_index = self.current_achievement_index()
        for index, achievement in enumerate(visible_achievements):
            col = index % columns
            row = index // columns
            x = margin + col * (card_w + gap)
            y = header_height + row * (card_h + gap)
            self.draw_achievement_card(frame, achievement, index, x, y, card_w, card_h, selected_index == index)

        self.preview_scene.setSceneRect(0, 0, width, height)

    def draw_preview_tabs(self, parent, width):
        top = QGraphicsRectItem(0, 0, width, 36, parent)
        top.setBrush(QBrush(QColor("#20201d")))
        top.setPen(QPen(QColor("#2e2b25"), 1))
        self.preview_items.append(top)

        self.add_centered_preview_text(parent, "Playthrough Overview", 122, 9, 210, 8, "#ece7da", True)
        self.add_centered_preview_text(parent, "Awards", 298, 9, 120, 8, "#ece7da", True)

        active = QGraphicsRectItem(0, 0, 150, 3, parent)
        active.setPos(236, 34)
        active.setBrush(QBrush(QColor("#b99d63")))
        active.setPen(QPen(QColor("#8b754b"), 1))
        self.preview_items.append(active)

        close_box = QGraphicsRectItem(0, 0, 28, 28, parent)
        close_box.setPos(width - 37, 4)
        close_box.setBrush(QBrush(QColor("#2a2924")))
        close_box.setPen(QPen(QColor("#3a332a"), 1))
        self.preview_items.append(close_box)
        self.add_centered_preview_text(parent, "x", width - 23, 4, 20, 16, "#d8bd8f", True)

    def draw_preview_empty(self):
        width = 520
        height = 260
        frame = QGraphicsRectItem(0, 0, width, height)
        frame.setBrush(QBrush(QColor("#181916")))
        frame.setPen(QPen(QColor("#3d382d"), 2))
        self.preview_scene.addItem(frame)
        self.preview_items.append(frame)

        self.add_centered_preview_text(frame, "Achievement Preview", width / 2, 72, 320, 16, "#f7f3e8", True)
        self.add_centered_preview_text(frame, "Select or add an achievement to preview it here.", width / 2, 126, 360, 10, "#bdb7a7")
        self.preview_scene.setSceneRect(0, 0, width, height)

    def draw_achievement_card(self, parent, achievement, index, x, y, width, height, selected=False):
        card = QGraphicsRectItem(0, 0, width, height, parent)
        card.setPos(x, y)
        card.setBrush(QBrush(QColor("#20241e" if not selected else "#293125")))
        card.setPen(QPen(QColor("#3a3a31" if not selected else "#b99d63"), 2 if selected else 1))
        self.preview_items.append(card)

        title = self.achievement_title_for_preview(achievement, index)
        desc = self.achievement_desc_for_preview(achievement, index)
        self.add_centered_preview_text(card, title, width / 2, 12, width - 18, 8, "#f4f1e8", True)

        icon_path = self.icon_path_for_preview(index)
        self.add_preview_pixmap(card, icon_path, width / 2 - 24, 36, 48, 48)

        self.add_preview_text(
            card,
            self.hoi4_preview_html(desc),
            16,
            92,
            width - 32,
            8,
            "#f2f0e8",
            False,
            Qt.AlignmentFlag.AlignCenter,
            html_text=True,
        )
        click_area = AchievementPreviewClickItem(self, index, width, height, card)
        self.preview_items.append(click_area)

    def add_preview_text(self, parent, text, x, y, max_width, size=9, color="#f2f2e8", bold=False, align=None, html_text=False):
        item = QGraphicsTextItem("", parent)
        font = QFont("Segoe UI", size)
        font.setBold(bold)
        item.setFont(font)
        item.setTextWidth(max_width)
        if html_text:
            weight = "700" if bold else "400"
            item.setHtml(f"<div style='font-family: Segoe UI; font-size: {size}pt; font-weight: {weight}; color: {color};'>{text}</div>")
        else:
            item.setPlainText(text)
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
            pixmap = self.generated_fallback_icon(width, height)
        else:
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

    def generated_fallback_icon(self, width, height):
        pixmap = QPixmap(width, height)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#2c2f2d")))
        painter.setPen(QPen(QColor("#686a64"), 2))
        painter.drawEllipse(3, 3, width - 6, height - 6)
        painter.setBrush(QBrush(QColor("#b7b9ae")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(width * 0.28), int(height * 0.28), int(width * 0.44), int(height * 0.44))
        painter.end()
        return pixmap

    def group_title_for_preview(self):
        current_index = self.current_achievement_index()
        if current_index == -2 and self.file_group_name and self.file_group_name.text().strip():
            return self.file_group_name.text().strip()

        doc = self.parser.parse_document(self.file_path, self.widget.content)
        unique_id = doc.properties.get("unique_id", "")
        title = self.localised_text(unique_id, unique_id)
        return title or os.path.basename(self.file_path)

    def achievement_title_for_preview(self, achievement, index):
        if self.current_achievement_index() == index and self.achievement_title:
            text = self.achievement_title.text().strip()
            if text:
                return text
        return self.localised_text(f"{achievement.id}_NAME", self.localised_text(achievement.id, achievement.id))

    def achievement_desc_for_preview(self, achievement, index):
        if self.current_achievement_index() == index and self.achievement_desc:
            text = self.achievement_desc.toPlainText().strip()
            if text:
                return text
        return self.localised_text(f"{achievement.id}_DESC", self.localised_text(f"{achievement.id}_desc", ""))

    def localised_text(self, key, fallback=""):
        if not key:
            return fallback
        plugin = self.get_hoi4_plugin()
        registry = getattr(plugin, "localisation_registry", None) if plugin else None
        if registry:
            _, entry = registry.search_key_status(key)
            if entry and entry.get("value"):
                return entry.get("value")
        return fallback

    def icon_path_for_preview(self, index):
        for widget in (self.completed_icon, self.possible_icon, self.not_eligible_icon):
            path = self.resolve_preview_path(widget.text().strip() if widget else "")
            if path and os.path.exists(path):
                return path

        icon_index = index % 12 + 1
        return os.path.join(os.path.dirname(__file__), "preview_icons", f"achievement_placeholder_{icon_index:02d}.png")

    def resolve_preview_path(self, path):
        if not path:
            return ""
        if os.path.isabs(path):
            return path

        project_path = core.api.get_project_path()
        candidates = []
        if project_path:
            candidates.append(os.path.join(project_path, path.replace("/", os.sep)))
        candidates.append(os.path.join(os.path.dirname(__file__), path.replace("/", os.sep)))
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return ""

    def hoi4_preview_html(self, text):
        text = html.escape(text or "")
        text = re.sub(r"\$([^$]+)\$", r"\1", text)
        text = re.sub(r"@([A-Z0-9_]{2,})", r"\1", text)
        text = re.sub(r"£[^£\s]+£", "", text)

        color_map = {
            "§Y": "#d6b846",
            "§G": "#74bd5b",
            "§R": "#d66d5f",
            "§B": "#68a6d7",
            "§W": "#ffffff",
        }
        for marker, color in color_map.items():
            text = text.replace(marker, f"<span style='color: {color}; font-weight: 700;'>")
        text = text.replace("§!", "</span>")
        text = re.sub(r"§.", "", text)
        return text

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
