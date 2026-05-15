from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import core.api
from PySide6.QtCore import QFile, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
)

from plugins.hoi4.script_parser import (
    AssignmentNode,
    ObjectNode,
    ParsedEntity,
    Parser,
    ScalarNode,
    SchemaEvaluator,
)

class ParsedEvent:
    def __init__(self, entity: ParsedEntity):
        self.entity = entity
        self.id = entity.id
        self.node = entity.node
        self.source_path = entity.source_path
        
        self.event_id = self.id
        self.key = "country_event"
        self.options: list[AssignmentNode] = []

    def first(self, key: str):
        return self.entity.first(key)

@dataclass
class Document:
    events: list[ParsedEvent] = field(default_factory=list)
    properties: dict = field(default_factory=dict)
    ast: Any = None

class EventParser:
    def __init__(self, plugin=None):
        self.plugin = plugin
        base_dir = os.path.dirname(__file__)
        with open(os.path.join(base_dir, "event_schema.json"), "r", encoding="utf-8") as f:
            self.schema_data = json.load(f)
        self.evaluator = SchemaEvaluator(self.schema_data)
        self.schema = self.schema_data

    def parse_document(self, path: str, content: str) -> Document:
        parser = Parser(content)
        ast, _, _ = parser.parse()
        
        doc = Document()
        doc.ast = ast
        
        for item in getattr(ast, "items", []):
            if isinstance(item, AssignmentNode) and item.key == "add_namespace":
                if isinstance(item.value, ScalarNode):
                    doc.properties["add_namespace"] = str(item.value.value)
        
        entities = self.evaluator.evaluate(ast, path)
        for e in entities:
            pe = ParsedEvent(e)
            if isinstance(e.node, AssignmentNode):
                pe.key = e.node.key
            for opt_node in e.properties.get("option", []):
                pe.options.append(opt_node)
            doc.events.append(pe)
            
        return doc


MODE_NAME = "イベントエディタ"
EDITOR_ID = "event_editor"

class DeleteOptionButtonItem(QGraphicsEllipseItem):
    def __init__(self, option_index, controller, parent=None):
        super().__init__(parent)
        self.option_index = option_index
        self.controller = controller
        
        size = 18
        self.setRect(0, 0, size, size)
        self.setBrush(QBrush(QColor("#cc3333")))
        self.setPen(QPen(Qt.GlobalColor.transparent))
        
        # SVGアイコンの読み込み
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../assets/icons/close.svg"))
        self.svg_item = QGraphicsSvgItem(icon_path, self)
        
        # アイコンのサイズ調整（元のSVGサイズを size にフィットさせる）
        s_rect = self.svg_item.boundingRect()
        if s_rect.width() > 0:
            scale = (size - 6) / s_rect.width()
            self.svg_item.setScale(scale)
            # 中央配置
            self.svg_item.setPos(3, 3)
            
        self.setAcceptHoverEvents(True)
        self.setVisible(False)
        
    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("#ff4444")))
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor("#cc3333")))
        super().hoverLeaveEvent(event)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.controller.remove_option(self.option_index))
        else:
            super().mousePressEvent(event)

class OptionButtonItem(QGraphicsRectItem):
    def __init__(self, option_index, text, controller, parent=None):
        super().__init__(parent)
        self.option_index = option_index
        self.controller = controller
        
        self.setRect(0, 0, 300, 38)
        self.setBrush(QBrush(QColor("#1a1a1a")))
        self.setPen(QPen(QColor("#333333"), 1))
        
        self.text_item = EditableTextItem(text, "option_name", controller, self, option_index)
        self.text_item.setDefaultTextColor(QColor("#ffffff"))
        self.text_item.setFont(QFont("sans-serif", 9))
        
        # テキストのセンタリング
        rect = self.text_item.boundingRect()
        self.text_item.setPos(150 - rect.width() / 2, 19 - rect.height() / 2)
        self.setAcceptHoverEvents(True)
        
        # 削除ボタンを追加
        self.delete_btn = DeleteOptionButtonItem(option_index, controller, self)
        self.delete_btn.setPos(300 - 25, (38 - 20) / 2)
        
    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("#333333")))
        self.delete_btn.setVisible(True)
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor("#1a1a1a")))
        self.delete_btn.setVisible(False)
        super().hoverLeaveEvent(event)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.controller.focus_option(self.option_index)
        super().mousePressEvent(event)

class AddOptionButtonItem(QGraphicsRectItem):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        
        self.setRect(0, 0, 300, 38)
        self.setBrush(QBrush(QColor("#222222")))
        self.setPen(QPen(QColor("#555555"), 1, Qt.PenStyle.DashLine))
        
        self.text_item = QGraphicsTextItem("+", self)
        self.text_item.setDefaultTextColor(QColor("#aaaaaa"))
        self.text_item.setFont(QFont("sans-serif", 14, QFont.Weight.Bold))
        
        rect = self.text_item.boundingRect()
        self.text_item.setPos(150 - rect.width() / 2, 19 - rect.height() / 2)
        self.setAcceptHoverEvents(True)
        self.setOpacity(0.5)
        
    def hoverEnterEvent(self, event):
        self.setBrush(QBrush(QColor("#333333")))
        self.setOpacity(0.8)
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.setBrush(QBrush(QColor("#222222")))
        self.setOpacity(0.5)
        super().hoverLeaveEvent(event)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            event.accept()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self.controller.add_new_option)
        else:
            super().mousePressEvent(event)

class EditableTextItem(QGraphicsTextItem):
    def __init__(self, text, prop_name, controller, parent=None, option_index=None):
        super().__init__()
        if parent:
            self.setParentItem(parent)
        self.setPlainText(text)
        self.prop_name = prop_name
        self.controller = controller
        self.option_index = option_index
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        self.is_editing_key = False
        
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.controller.on_preview_text_changed(self.prop_name, self.toPlainText(), self.is_editing_key, self.option_index)


def setup(widget, file_path, content):
    controller = EventEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    controller.bind()


class EventEditorController:
    def __init__(self, widget, file_path, content):
        self.widget = widget
        self.file_path = file_path
        self.widget.content = content
        self.events: list[ParsedEvent] = []
        self.selected_event_id = ""
        self.updating = False
        self.localization_updates = {} # ローカライズの更新内容を保持
        self.parser = EventParser(self.get_hoi4_plugin() or object())
        self.loc_timer = QTimer()
        self.loc_timer.setSingleShot(True)
        self.loc_timer.timeout.connect(self.update_localisation_ui)
        core.api.register_loc_changed_handler(self.update_localisation_ui)
        
        self.is_detailed_mode = False
        self.system_widgets = []
        self.format_config = {}
        self.load_format_config()

    def load_format_config(self):
        path = os.path.join(os.path.dirname(__file__), "event_format.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.format_config = json.load(f)
            except Exception:
                self.format_config = {}
        else:
            self.format_config = {}

    def get_plugin_settings(self):
        """plugins/hoi4/settings.json を読み込む"""
        # このファイルの場所は plugins/hoi4/events/event_editor.py なので 2階層上が plugins/hoi4/
        settings_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "settings.json")
        try:
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def get_mod_root(self) -> str:
        """本体のAPIから現在開いているプロジェクトのパスを取得する"""
        path = core.api.get_project_path()
        if path:
            return path
        # フォールバック（プロジェクトが開かれていない場合など）
        return os.path.dirname(self.file_path)

    def get_current_namespace(self):
        """現在のファイル内で定義されているネームスペースを取得する"""
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            return doc.properties.get("add_namespace", "")
        except Exception:
            return ""

    def apply_format(self, fmt, **kwargs):
        """フォーマット文字列に値を適用する"""
        try:
            return fmt.format(**kwargs)
        except Exception:
            # フォールバック: 単純置換
            res = fmt
            for k, v in kwargs.items():
                res = res.replace(f"{{{k}}}", str(v))
            return res

    def format_values(self, namespace=None, event_id="", number=1, option_index=0, lang=None):
        namespace = namespace if namespace is not None else (self.get_current_namespace() or "custom_events")
        if lang is None:
            lang = self.get_plugin_settings().get("display_language", "l_japanese")
        fallback_id = f"{namespace}.{number}"
        file_stem = os.path.splitext(os.path.basename(self.file_path))[0]
        # l_japanese -> japanese のようにプレフィックスを除去
        display_lang = lang or ""
        if display_lang.startswith("l_"):
            display_lang = display_lang[2:]

        values = {
            "namespace": namespace,
            "file": file_stem,
            "number": number,
            "lang": display_lang,
            "id": event_id or fallback_id,
        }
        values.update(self.option_format_values(option_index))
        return values

    def current_event_number(self):
        event = self.current_event()
        if not event:
            return 1
        try:
            return self.events.index(event) + 1
        except ValueError:
            return 1

    def option_format_values(self, option_index):
        number = option_index + 1
        letter = chr(ord('a') + option_index) if option_index < 26 else str(number)
        return {
            "a-z": letter,
        }

    def bind(self):
        self.event_list = find(self.widget, QTreeWidget, "eventTreeWidget")
        self.event_id = find(self.widget, QLineEdit, "eventIdEdit")
        self.event_type = find(self.widget, QComboBox, "eventTypeCombo")
        self.title_key = find(self.widget, QLineEdit, "titleKeyEdit")
        self.desc_key = find(self.widget, QLineEdit, "descKeyEdit")
        if self.title_key:
            self.title_key.textChanged.connect(lambda: self.loc_timer.start(300))
        if self.desc_key:
            self.desc_key.textChanged.connect(lambda: self.loc_timer.start(300))
        self.picture = find(self.widget, QLineEdit, "pictureEdit")
        self.fire_only_once = find(self.widget, QCheckBox, "fireOnlyOnceCheck")
        self.hidden = find(self.widget, QCheckBox, "hiddenCheck")
        self.major = find(self.widget, QCheckBox, "majorCheck")
        self.fire_for_sender = find(self.widget, QCheckBox, "fireForSenderCheck")
        self.timeout_days = find(self.widget, QSpinBox, "timeoutSpin")
        self.title_loc_file = find(self.widget, QLineEdit, "titleLocFileEdit")
        self.desc_loc_file = find(self.widget, QLineEdit, "descLocFileEdit")
        if self.title_loc_file:
            self.title_loc_file.setReadOnly(True)
        if self.desc_loc_file:
            self.desc_loc_file.setReadOnly(True)
        self.triggered_only = find(self.widget, QRadioButton, "isTriggeredOnlyRadio")
        self.standard_trigger = find(self.widget, QRadioButton, "isStandardTriggerRadio")
        self.trigger = find(self.widget, QPlainTextEdit, "triggerEdit")
        self.mtth = find(self.widget, QPlainTextEdit, "mtthEdit")
        self.immediate = find(self.widget, QPlainTextEdit, "immediateEdit")
        self.after = find(self.widget, QPlainTextEdit, "afterEdit")
        self.doc_prop_widgets = {}

        # 選択肢関連
        self.options_layout = self.widget.findChild(object, "optionsLayout")
        self.add_option_btn = find(self.widget, QPushButton, "addOptionButton")
        if self.add_option_btn:
            self.add_option_btn.clicked.connect(self.add_new_option)
            
        # プレビュー関連
        self.title_text = find(self.widget, QLineEdit, "titleTextEdit")
        self.desc_text = find(self.widget, QPlainTextEdit, "descEdit")
        self.preview_panel = find(self.widget, QGraphicsView, "previewPanel")
        self.main_splitter = find(self.widget, QSplitter, "mainSplitter")
        self.editor_scroll_area = find(self.widget, QScrollArea, "editorScrollArea")
        
        # プレースホルダの作成
        if self.main_splitter:
            from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
            self.placeholder_widget = QWidget()
            self.placeholder_widget.setObjectName("nsPlaceholder")
            placeholder_layout = QVBoxLayout(self.placeholder_widget)
            
            self.placeholder_label = QLabel("ネームスペースを入力して編集を開始してください")
            self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.placeholder_label.setStyleSheet("font-size: 16px; color: #888; font-weight: bold;")
            placeholder_layout.addWidget(self.placeholder_label)
            
            # スプリッターに追加
            self.main_splitter.addWidget(self.placeholder_widget)
            
        if self.preview_panel:
            self.scene = QGraphicsScene()
            self.preview_panel.setScene(self.scene)
            self.preview_panel.setBackgroundBrush(QBrush(QColor("#1e1e1e")))
            self.preview_panel.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.title_text: self.title_text.editingFinished.connect(self.update_preview)
        if self.desc_text: self.desc_text.textChanged.connect(self.update_preview)

        # ドキュメントプロパティのバインド
        for prop_key, prop_def in self.parser.schema.get("document_properties", {}).items():
            widget_name = prop_def.get("ui_widget")
            if widget_name:
                widget = find(self.widget, QLineEdit, widget_name)
                if widget:
                    self.doc_prop_widgets[prop_key] = widget
                    if prop_key == "add_namespace":
                        widget.textChanged.connect(lambda _, k=prop_key: self.on_doc_prop_edited(k))
                    else:
                        widget.editingFinished.connect(lambda k=prop_key: self.on_doc_prop_edited(k))

        if self.event_list:
            self.event_list.currentItemChanged.connect(self.on_event_selected)

        # イベント操作ボタンの接続
        self.new_event_btn = find(self.widget, QPushButton, "newEventButton")
        if self.new_event_btn:
            self.new_event_btn.clicked.connect(self.add_new_event)
        
        self.duplicate_event_btn = find(self.widget, QPushButton, "duplicateEventButton")
        if self.duplicate_event_btn:
            self.duplicate_event_btn.clicked.connect(self.duplicate_selected_event)
            
        self.delete_event_btn = find(self.widget, QPushButton, "deleteEventButton")
        if self.delete_event_btn:
            self.delete_event_btn.clicked.connect(self.delete_selected_event)
            
        self.search_edit = find(self.widget, QLineEdit, "eventSearchEdit")
        if self.search_edit:
            self.search_edit.textChanged.connect(self.on_search_text_changed)

        self.connect_scalar(self.event_id, "id")
        self.connect_scalar(self.title_key, "title")
        self.connect_scalar(self.desc_key, "desc")
        self.connect_scalar(self.picture, "picture")
        self.connect_bool(self.fire_only_once, "fire_only_once")
        self.connect_bool(self.hidden, "hidden")
        self.connect_bool(self.major, "major")
        self.connect_bool(self.fire_for_sender, "fire_for_sender")
        if self.timeout_days:
            self.timeout_days.valueChanged.connect(lambda val: self.replace_property("timeout_days", str(val) if val > 0 else ""))
        
        if self.triggered_only:
            self.triggered_only.toggled.connect(self.on_trigger_type_changed)
        if self.standard_trigger:
            self.standard_trigger.toggled.connect(self.on_trigger_type_changed)
        
        # トップレベルのテキストエディタの接続
        if self.trigger:
            self.trigger.focusOutEvent = lambda event: self.on_top_text_focus_out("trigger", self.trigger, event)
        if self.mtth:
            self.mtth.focusOutEvent = lambda event: self.on_top_text_focus_out("mean_time_to_happen", self.mtth, event)
        if self.immediate:
            self.immediate.focusOutEvent = lambda event: self.on_top_text_focus_out("immediate", self.immediate, event)
        if self.after:
            self.after.focusOutEvent = lambda event: self.on_top_text_focus_out("after", self.after, event)

        # モード切替ボタンの接続
        self.standard_mode_btn = find(self.widget, object, "standardModeButton")
        self.detailed_mode_btn = find(self.widget, object, "customModeButton") # UI上は詳細
        
        if self.standard_mode_btn:
            self.standard_mode_btn.clicked.connect(lambda: self.set_detailed_mode(False))
        if self.detailed_mode_btn:
            self.detailed_mode_btn.clicked.connect(lambda: self.set_detailed_mode(True))

        # システム項目の収集
        self.system_widgets = [
            find(self.widget, object, "eventIdLabel"), self.event_id,
            find(self.widget, object, "titleKeyLabel"), self.title_key,
            find(self.widget, object, "titleLocFileLabel"), self.title_loc_file,
            find(self.widget, object, "titleLocFileBrowseButton"),
            find(self.widget, object, "descKeyLabel"), self.desc_key,
            find(self.widget, object, "descLocFileLabel"), self.desc_loc_file,
            find(self.widget, object, "descLocFileBrowseButton"),
        ]
        # Noneを除外
        self.system_widgets = [w for w in self.system_widgets if w is not None]

        self.refresh()
        self.set_detailed_mode(False) # 初期状態は標準

    def set_detailed_mode(self, enabled):
        self.is_detailed_mode = enabled
        for w in self.system_widgets:
            w.setVisible(enabled)
            
        # ボタンの状態を更新
        if self.standard_mode_btn: self.standard_mode_btn.setChecked(not enabled)
        if self.detailed_mode_btn: self.detailed_mode_btn.setChecked(enabled)
        
        # 既存のオプションの表示を更新
        if self.options_layout:
            for i in range(self.options_layout.count() - 1):
                opt_widget = self.options_layout.itemAt(i).widget()
                if opt_widget:
                    self._apply_mode_to_option_widget(opt_widget)

    def on_top_text_focus_out(self, key, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.replace_property(key, edit.toPlainText())

    def set_content(self, content):
        self.widget.content = content
        self.refresh()

    def refresh(self):
        # EventParser に解析を依頼
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        self.events = getattr(doc, "events", [])
        
        selected = self.selected_event_id
        self.updating = True
        try:
            if self.event_list:
                was_blocked = self.event_list.blockSignals(True)
                self.event_list.setUpdatesEnabled(False)
                try:
                    self.event_list.clear()
                    target_item = None
                    for event in self.events:
                        label = event.event_id or f"{event.key}@{event.node.range.start.line}"
                        item = QTreeWidgetItem(self.event_list)
                        item.setText(0, label)
                        item.setData(0, Qt.ItemDataRole.UserRole, event)
                        if event.event_id == selected:
                            target_item = item
                    
                    if target_item:
                        self.event_list.setCurrentItem(target_item)
                    elif self.event_list.topLevelItemCount() > 0:
                        self.event_list.setCurrentItem(self.event_list.topLevelItem(0))
                        
                    self.load_event(self.current_event())
                finally:
                    self.event_list.setUpdatesEnabled(True)
                    self.event_list.blockSignals(was_blocked)
            
            for prop_key, widget in self.doc_prop_widgets.items():
                val = getattr(doc, "properties", {}).get(prop_key, "")
                if widget.text() != val:
                    widget.setText(val)
            
            # ネームスペースがない場合は新規イベント作成を抑制
            namespace = getattr(doc, "properties", {}).get("add_namespace", "")
            if self.new_event_btn:
                self.new_event_btn.setEnabled(bool(namespace))
                self.new_event_btn.setToolTip("" if namespace else "イベントを追加するにはネームスペースを定義してください")
            
            has_event = bool(self.current_event())
            if self.duplicate_event_btn:
                self.duplicate_event_btn.setEnabled(bool(namespace) and has_event)
                if not namespace:
                    self.duplicate_event_btn.setToolTip("複製するにはネームスペースを定義してください")
                elif not has_event:
                    self.duplicate_event_btn.setToolTip("複製するイベントを選択してください")
                else:
                    self.duplicate_event_btn.setToolTip("")
                    
            if self.delete_event_btn:
                self.delete_event_btn.setEnabled(has_event)
                self.delete_event_btn.setToolTip("" if has_event else "削除するイベントを選択してください")
            # ネームスペース未入力時のハイライト
            ns_widget = self.doc_prop_widgets.get("add_namespace")
            if ns_widget:
                if not namespace:
                    ns_widget.setStyleSheet("border: 1px solid #f44336; background-color: rgba(244, 67, 54, 0.1); border-radius: 4px;")
                else:
                    ns_widget.setStyleSheet("")
            
            # フォームとプレビューの表示制御
            has_namespace = bool(namespace)
            has_event = bool(self.current_event())
            
            should_show_editor = has_namespace and has_event
            
            if self.editor_scroll_area:
                self.editor_scroll_area.setVisible(should_show_editor)
            if self.preview_panel:
                self.preview_panel.setVisible(should_show_editor)
            
            if hasattr(self, 'placeholder_widget'):
                self.placeholder_widget.setVisible(not should_show_editor)
                if not has_namespace:
                    self.placeholder_label.setText("ネームスペースを入力して編集を開始してください")
                elif not has_event:
                    self.placeholder_label.setText("イベントを追加するか、リストから選択してください")
                
        finally:
            self.updating = False

    def on_event_selected(self, current, previous):
        if self.updating:
            return
        self.updating = True
        try:
            self.load_event(self.current_event())
        finally:
            self.updating = False

    def current_event(self) -> Optional[ParsedEvent]:
        if not self.event_list:
            return self.events[0] if self.events else None
        item = self.event_list.currentItem()
        if not item:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def load_event(self, event: Optional[ParsedEvent]):
        self.selected_event_id = event.event_id if event else ""
        set_line(self.event_id, prop_text(event, "id"))
        set_combo(self.event_type, event.key if event else "")
        set_line(self.title_key, prop_text(event, "title"))
        set_line(self.desc_key, prop_text(event, "desc"))
        
        pic_val = prop_text(event, "picture")
        set_line(self.picture, "" if pic_val == "none" else pic_val)
        
        set_checked(self.fire_only_once, prop_bool(event, "fire_only_once"))
        set_checked(self.hidden, prop_bool(event, "hidden"))
        set_checked(self.major, prop_bool(event, "major"))
        set_checked(self.fire_for_sender, prop_bool(event, "fire_for_sender"))
        set_spin(self.timeout_days, prop_text(event, "timeout_days"))
        triggered = prop_bool(event, "is_triggered_only")
        set_checked(self.triggered_only, triggered)
        set_checked(self.standard_trigger, not triggered)
        set_plain(self.trigger, block_text(self.widget.content, event.node if event else None, "trigger"))
        set_plain(self.mtth, block_text(self.widget.content, event.node if event else None, "mean_time_to_happen"))
        set_plain(self.immediate, block_text(self.widget.content, event.node if event else None, "immediate"))
        set_plain(self.after, block_text(self.widget.content, event.node if event else None, "after"))

        self.update_trigger_ui()
        self.refresh_options(event)
        self.update_localisation_ui()
        self.update_preview()

    def update_preview(self):
        if self.updating: return
        if not hasattr(self, 'scene'): return
        self.scene.clear()
        
        event = self.current_event()
        if not event: return
        
        title_key = prop_text(event, "title")
        title_val = self.title_text.text() if self.title_text and self.title_text.text() else title_key
        is_title_key = not (self.title_text and self.title_text.text())
        
        desc_key = prop_text(event, "desc")
        desc_val = self.desc_text.toPlainText() if self.desc_text and self.desc_text.toPlainText() else desc_key
        is_desc_key = not (self.desc_text and self.desc_text.toPlainText())
        
        # 背景枠（羊皮紙風）
        canvas_width = 500
        frame = QGraphicsRectItem(0, 0, canvas_width, 400)
        frame.setBrush(QBrush(QColor("#e3d1b1"))) # 羊皮紙色
        frame.setPen(QPen(QColor("#5a4a3a"), 2))
        self.scene.addItem(frame)
        
        # 表示内容の決定：翻訳欄が空ならキーを出す
        display_title = title_val if title_val else (title_key if title_key else "Untitled Event")
        
        # タイトル
        title_item = EditableTextItem(display_title, "title", self, frame)
        title_item.setDefaultTextColor(QColor("black"))
        font_title = QFont()
        font_title.setBold(True)
        font_title.setPointSize(14)
        title_item.setFont(font_title)
        
        # title_item.setTextWidth(canvas_width - 40) # 固定幅を外すことで文字幅ベースのセンタリングを可能にする
        
        title_rect = title_item.boundingRect()
        title_item.setPos((canvas_width - title_rect.width()) / 2, 25)
        title_item.is_editing_key = is_title_key
        
        # 説明文
        display_desc = desc_val if desc_val else (desc_key if desc_key else "No description available.")
        
        desc_item = EditableTextItem(display_desc, "desc", self, frame)
        desc_item.setDefaultTextColor(QColor("black"))
        font_desc = QFont()
        font_desc.setPointSize(11)
        desc_item.setFont(font_desc)
        
        desc_item.setTextWidth(canvas_width - 40)
        
        desc_rect = desc_item.boundingRect()
        desc_y = 25 + title_rect.height() + 15
        desc_item.setPos(20, desc_y)
        desc_item.is_editing_key = is_desc_key
        
        # 下部要素の配置
        bottom_area_y = desc_y + desc_rect.height() + 20
        
        # 画像（左下）
        pic_width = 160
        pic_height = 160
        
        # プレースホルダ画像のロード (プロファイルフォルダ内の画像を参照)
        pic_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../placeholder.png"))
        pixmap = QPixmap(pic_path)
        
        if pixmap.isNull():
            pic = QGraphicsRectItem(20, bottom_area_y, pic_width, pic_height, frame)
            pic.setBrush(QBrush(QColor("#c5b595")))
            pic.setPen(QPen(QColor("#8a7a5a"), 1))
            
            pic_name = prop_text(event, "picture")
            if not pic_name or pic_name == "none":
                pic_display_text = "(No Picture)"
            else:
                pic_display_text = pic_name
                
            pic_label = QGraphicsTextItem(pic_display_text, pic)
            pic_label.setDefaultTextColor(QColor("#5a4a3a"))
            pic_label.setFont(QFont("sans-serif", 8))
            pl_rect = pic_label.boundingRect()
            pic_label.setPos((pic_width - pl_rect.width()) / 2, (pic_height - pl_rect.height()) / 2)
        else:
            pixmap = pixmap.scaled(pic_width, pic_height, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            pic = QGraphicsPixmapItem(pixmap, frame)
            pic.setPos(20, bottom_area_y)
            # 画像の枠線
            border = QGraphicsRectItem(0, 0, pic_width, pic_height, pic)
            border.setPen(QPen(QColor("#5a4a3a"), 2))
            
            # 元々のテキスト情報のオーバーレイ表示 (任意)
            pic_name = prop_text(event, "picture")
            pic_display_text = pic_name if pic_name and pic_name != "none" else "none"
            
            pic_label = QGraphicsTextItem(pic_display_text, pic)
            pic_label.setDefaultTextColor(QColor("white"))
            pic_label.setFont(QFont("sans-serif", 8))
            pic_label.setPos(5, pic_height - 20)
        
        # 選択肢（画像の右側）
        opt_x = 20 + pic_width + 10
        opt_y = bottom_area_y
        for i, opt in enumerate(event.options):
            name_key = ""
            if isinstance(opt.value, ObjectNode):
                name_assign = first([item for item in opt.value.items if isinstance(item, AssignmentNode) and item.key == "name"])
                name_key = scalar_text(name_assign)
            
            name_val = name_key
            if self.options_layout and i < self.options_layout.count() - 1:
                opt_widget = self.options_layout.itemAt(i).widget()
                if opt_widget:
                    name_text_edit = find(opt_widget, QLineEdit, "nameTextEdit")
                    if name_text_edit and name_text_edit.text():
                        name_val = name_text_edit.text()
            
            btn = OptionButtonItem(i, name_val, self, frame)
            btn.setPos(opt_x, opt_y)
            opt_y += 42 # 38px(高さ) + 4px(余白)
            
        # 選択肢追加ボタン (+)
        add_btn = AddOptionButtonItem(self, frame)
        add_btn.setPos(opt_x, opt_y)
        opt_y += 42 # 38px(高さ) + 4px(余白)
            
        final_height = bottom_area_y + pic_height + 20
        frame.setRect(0, 0, canvas_width, final_height)
        
        # 背景枠の高さに関わらず、全ての選択肢が含まれるようにシーンの領域を設定する
        self.scene.setSceneRect(0, 0, canvas_width, max(final_height, opt_y + 10))

    def on_preview_text_changed(self, prop_name, new_text, is_editing_key, option_index=None):
        if is_editing_key:
            # キーを編集した場合はスクリプトのプロパティを更新
            if prop_name == "title" and self.title_key:
                self.title_key.setText(new_text)
                self.replace_property("title", new_text)
            elif prop_name == "desc" and self.desc_key:
                self.desc_key.setText(new_text)
                self.replace_property("desc", new_text)
            elif prop_name == "option_name" and option_index is not None:
                event = self.current_event()
                if event and option_index < len(event.options):
                    self.update_option_property(option_index, "name", new_text)
        else:
            # 値を編集した場合はローカライズ更新辞書に保存し、UIの入力欄を更新
            event = self.current_event()
            if event:
                if prop_name == "option_name" and option_index is not None:
                    if option_index < len(event.options):
                        opt = event.options[option_index]
                        name_key = ""
                        if isinstance(opt.value, ObjectNode):
                            name_assign = first([item for item in opt.value.items if isinstance(item, AssignmentNode) and item.key == "name"])
                            name_key = scalar_text(name_assign)
                        if name_key:
                            self.localization_updates[name_key] = new_text
                else:
                    key = prop_text(event, prop_name)
                    if key:
                        self.localization_updates[key] = new_text
                    
            if prop_name == "title" and self.title_text:
                self.title_text.setText(new_text)
            elif prop_name == "desc" and self.desc_text:
                self.desc_text.setPlainText(new_text)
            elif prop_name == "option_name" and option_index is not None:
                # 該当するオプションウィジェットを更新
                if self.options_layout and option_index < self.options_layout.count() - 1:
                    opt_widget = self.options_layout.itemAt(option_index).widget()
                    if opt_widget:
                        name_text_edit = find(opt_widget, QLineEdit, "nameTextEdit")
                        if name_text_edit:
                            name_text_edit.setText(new_text)

    def focus_option(self, index):
        if not self.options_layout or not self.editor_scroll_area: return
        if index >= self.options_layout.count() - 1: return
        
        opt_widget = self.options_layout.itemAt(index).widget()
        if opt_widget:
            self.editor_scroll_area.ensureWidgetVisible(opt_widget)
            name_edit = find(opt_widget, QLineEdit, "nameKeyEdit")
            if name_edit:
                name_edit.setFocus()
                name_edit.selectAll()

    def refresh_options(self, event: Optional[ParsedEvent]):
        if not self.options_layout:
            return

        # 既存のウィジェットを削除 (addOptionButton以外)
        while self.options_layout.count() > 1:
            item = self.options_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not event:
            return

        loader = QUiLoader()
        ui_path = os.path.join(os.path.dirname(__file__), "event_option_node.ui")
        
        # AI選択確率の集計
        option_factors = []
        for opt in event.options:
            factor = 1
            properties = {}
            if isinstance(opt.value, ObjectNode):
                for item in opt.value.items:
                    if isinstance(item, AssignmentNode):
                        properties.setdefault(item.key, []).append(item)
            
            ai_chance_node = first(properties.get("ai_chance", []))
            if ai_chance_node and isinstance(ai_chance_node.value, ObjectNode):
                factor_node = first([item for item in ai_chance_node.value.items if isinstance(item, AssignmentNode) and item.key == "factor"])
                if factor_node and isinstance(factor_node.value, ScalarNode):
                    try:
                        factor = float(factor_node.value.value)
                    except Exception:
                        pass
            option_factors.append(factor)
        
        total_factor = sum(option_factors)

        for i, option in enumerate(event.options):
            ui_file = QFile(ui_path)
            if not ui_file.open(QFile.ReadOnly):
                continue
            
            option_widget = loader.load(ui_file)
            ui_file.close()
            
            if not option_widget:
                continue

            # タイトルの設定
            title_label = find(option_widget, object, "optionTitle")
            if title_label:
                prob = (option_factors[i] / total_factor * 100) if total_factor > 0 else 0
                title_label.setText(f"選択肢 {i+1} (AI確率: {prob:.1f}%)")

            # データのパース
            properties = {}
            if isinstance(option.value, ObjectNode):
                for item in option.value.items:
                    if isinstance(item, AssignmentNode):
                        properties.setdefault(item.key, []).append(item)

            # 各フィールドへの値セット
            name_edit = find(option_widget, QLineEdit, "nameKeyEdit")
            set_line(name_edit, scalar_text(first(properties.get("name", []))))
            if name_edit:
                name_edit.editingFinished.connect(lambda idx=i, edit=name_edit: self.update_option_property(idx, "name", edit.text()))
                
            name_text_edit = find(option_widget, QLineEdit, "nameTextEdit")
            if name_text_edit:
                name_text_edit.editingFinished.connect(self.update_preview)

            ai_spin = find(option_widget, QSpinBox, "aiSpin")
            ai_chance_node = first(properties.get("ai_chance", []))
            ai_val = -1
            if ai_chance_node and isinstance(ai_chance_node.value, ObjectNode):
                factor_node = first([item for item in ai_chance_node.value.items if isinstance(item, AssignmentNode) and item.key == "factor"])
                if factor_node and isinstance(factor_node.value, ScalarNode):
                    ai_val = int(factor_node.value.value)
            if ai_spin:
                ai_spin.setValue(ai_val)
                ai_spin.valueChanged.connect(lambda val, idx=i: self.update_option_ai_chance(idx, val))

            effect_edit = find(option_widget, QPlainTextEdit, "effectEdit")
            trigger_edit = find(option_widget, QPlainTextEdit, "triggerEdit")
            hidden_effect_edit = find(option_widget, QPlainTextEdit, "hiddenEffectEdit")

            set_plain(trigger_edit, block_text(self.widget.content, option, "trigger"))
            set_plain(hidden_effect_edit, block_text(self.widget.content, option, "hidden_effect"))

            if effect_edit and isinstance(option.value, ObjectNode):
                items = [item for item in option.value.items if isinstance(item, AssignmentNode) and item.key not in {"name", "ai_chance", "trigger", "hidden_effect", "original_sender", "picture", "tooltip", "show_sound"}]
                effect_texts = [self.widget.content[item.range.start_offset:item.range.end_offset] for item in items]
                set_plain(effect_edit, "\n".join(effect_texts))

            # 変更時の保存処理の接続 (簡易化のため lambda でラップ)
            if trigger_edit:
                trigger_edit.focusInEvent = lambda event, idx=i, edit=trigger_edit: QPlainTextEdit.focusInEvent(edit, event)
                trigger_edit.focusOutEvent = lambda event, idx=i, edit=trigger_edit: self.on_option_text_focus_out(idx, "trigger", edit, event)
            if hidden_effect_edit:
                hidden_effect_edit.focusOutEvent = lambda event, idx=i, edit=hidden_effect_edit: self.on_option_text_focus_out(idx, "hidden_effect", edit, event)
            if effect_edit:
                effect_edit.focusOutEvent = lambda event, idx=i, edit=effect_edit: self.on_option_effects_focus_out(idx, edit, event)

            remove_btn = find(option_widget, object, "removeButton")
            if remove_btn:
                remove_btn.clicked.connect(lambda idx=i: self.remove_option(idx))

            # レイアウトに追加 (addOptionButton の上に挿入)
            self.options_layout.insertWidget(self.options_layout.count() - 1, option_widget)
            self._apply_mode_to_option_widget(option_widget)

    def _apply_mode_to_option_widget(self, widget):
        # 詳細モードのみ表示する項目
        targets = [
            find(widget, object, "nameKeyLabel"),
            find(widget, object, "nameKeyEdit"),
            find(widget, object, "optionLocFileLabel"),
            find(widget, object, "optionLocFileEdit"),
            find(widget, object, "optionLocFileBrowseButton"),
        ]
        for t in targets:
            if t: t.setVisible(self.is_detailed_mode)

    def on_option_text_focus_out(self, idx, key, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.update_option_property(idx, key, edit.toPlainText())

    def on_option_effects_focus_out(self, idx, edit, event):
        QPlainTextEdit.focusOutEvent(edit, event)
        self.update_option_effects(idx, edit.toPlainText())

    def update_option_effects(self, option_index, new_effects_text):
        if self.updating: return
        event = self.current_event()
        if not event or option_index >= len(event.options): return
        option = event.options[option_index]
        text = self.widget.content
        
        items = []
        if isinstance(option.value, ObjectNode):
            items = [item for item in option.value.items if isinstance(item, AssignmentNode) and item.key not in {"name", "ai_chance", "trigger", "hidden_effect", "original_sender", "picture", "tooltip", "show_sound"}]
        
        if items:
            start = items[0].range.start_offset
            end = items[-1].range.end_offset
            self.widget.content = text[:start] + new_effects_text + text[end:]
        else:
            # trigger の後付近に挿入
            self.update_option_property(option_index, "_effects", new_effects_text)
            return # update_option_property が refresh を呼ぶ
        self.refresh()

    def add_new_option(self):
        event = self.current_event()
        if not event:
            return
        
        settings = self.get_plugin_settings()
        opt_fmt = settings.get("event_option_key_format", "{id}.{a-z}")
        
        existing_options = len(event.options)
        opt_key = self.apply_format(
            opt_fmt,
            **self.format_values(
                namespace=self.get_current_namespace(),
                event_id=event.event_id,
                number=existing_options + 1,
                option_index=existing_options,
            ),
        )
        
        text = self.widget.content
        close_brace_offset = event.node.range.end_offset - 1
        
        new_option_text = f'\n\toption = {{\n\t\tname = {opt_key}\n\t}}'
        self.widget.content = text[:close_brace_offset] + new_option_text + text[close_brace_offset:]
        self.refresh()

    def remove_option(self, index):
        event = self.current_event()
        if not event or index >= len(event.options):
            return
        
        option = event.options[index]
        text = self.widget.content
        self.widget.content = text[:option.range.start_offset] + text[option.range.end_offset:]
        self.refresh()

    def add_new_event(self):
        text = self.widget.content
        settings = self.get_plugin_settings()
        namespace = self.get_current_namespace()
        
        # 設定値の取得（デフォルト値付き）
        id_fmt = settings.get("event_id_format", "{namespace}.{number}")
        title_fmt = settings.get("event_title_key_format", "{id}.t")
        desc_fmt = settings.get("event_desc_key_format", "{id}.d")
        opt_fmt = settings.get("event_option_key_format", "{id}.{a-z}")
        # ID生成
        counter = 1
        new_id = ""
        while True:
            new_id = self.apply_format(
                id_fmt,
                **self.format_values(namespace=namespace, number=counter, option_index=counter-1),
            )
            if not any(e.event_id == new_id for e in self.events):
                break
            counter += 1
            if counter > 9999: break
            
        # キー生成
        values = self.format_values(namespace=namespace, event_id=new_id, number=counter, option_index=0)
        title_key = self.apply_format(title_fmt, **values)
        desc_key = self.apply_format(desc_fmt, **values)
        opt_key = self.apply_format(opt_fmt, **values)
        
        # テンプレート
        template = f"\n\ncountry_event = {{\n\tid = {new_id}\n\ttitle = {title_key}\n\tdesc = {desc_key}\n\tpicture = none\n\n\tis_triggered_only = yes\n\n\toption = {{\n\t\tname = {opt_key}\n\t}}\n}}"
        self.widget.content = text.rstrip() + template
        self.selected_event_id = new_id
        
        self.refresh()

    def duplicate_selected_event(self):
        event = self.current_event()
        if not event: return
        
        text = self.widget.content
        event_text = text[event.node.range.start_offset:event.node.range.end_offset]
        
        # IDを書き換える
        old_id = event.event_id
        new_id = old_id + "_copy"
        event_text = event_text.replace(f"id = {old_id}", f"id = {new_id}")
        
        self.widget.content = text.rstrip() + "\n\n" + event_text
        self.selected_event_id = new_id
        self.refresh()

    def delete_selected_event(self):
        event = self.current_event()
        if not event: return
        
        from PySide6.QtWidgets import QMessageBox
        res = QMessageBox.question(self.widget, "確認", f"イベント {event.event_id} を削除しますか？")
        if res != QMessageBox.StandardButton.Yes:
            return
            
        text = self.widget.content
        start = event.node.range.start_offset
        end = event.node.range.end_offset
        
        # 前後の空行も削除
        while start > 0 and text[start-1] in " \t\r\n": start -= 1
        
        self.widget.content = text[:start] + text[end:]
        self.selected_event_id = ""
        self.refresh()

    def on_search_text_changed(self, text):
        if not self.event_list: return
        search_term = text.lower()
        for i in range(self.event_list.topLevelItemCount()):
            item = self.event_list.topLevelItem(i)
            item.setHidden(search_term not in item.text(0).lower())

    def update_option_property(self, option_index, key, value):
        if self.updating:
            return
        event = self.current_event()
        if not event or option_index >= len(event.options):
            return
        
        option = event.options[option_index]
        text = self.widget.content

        # 既存のプロパティを検索
        target = None
        if isinstance(option.value, ObjectNode):
            for item in option.value.items:
                if isinstance(item, AssignmentNode) and item.key == key:
                    target = item
                    break
        
        if not value or (key == "ai_chance" and value == "-1"):
            if target:
                start = target.range.start_offset
                end = target.range.end_offset
                if start > 0 and text[start-1] == "\n": start -= 1
                self.widget.content = text[:start] + text[end:]
                self.refresh()
            return

        is_object = key in {"trigger", "hidden_effect", "ai_chance"}
        if key == "ai_chance":
            formatted_value = f"{{\n\t\t\tfactor = {value}\n\t\t}}"
        elif is_object:
            # 各行にインデントを追加
            indented = "\n".join(["\t\t\t" + line if line.strip() else line for line in value.splitlines()])
            formatted_value = f"{{\n{indented}\n\t\t}}"
        else:
            formatted_value = f'"{value}"'

        if target:
            val_range = target.value.range
            self.widget.content = text[:val_range.start_offset] + formatted_value + text[val_range.end_offset:]
        else:
            # 順序に従って挿入場所を特定
            order = ["name", "ai_chance", "trigger", "hidden_effect"]
            try:
                target_idx = order.index(key)
            except ValueError:
                target_idx = 2.5 # trigger と hidden_effect の間（一般エフェクト）

            insertion_offset = option.range.end_offset - 1
            insert_before_node = None
            if isinstance(option.value, ObjectNode):
                for item in option.value.items:
                    if isinstance(item, AssignmentNode):
                        try:
                            idx = order.index(item.key)
                        except ValueError:
                            idx = 2.5
                        if idx > target_idx:
                            if insert_before_node is None or item.range.start_offset < insertion_offset:
                                insertion_offset = item.range.start_offset
                                insert_before_node = item
            
            if insert_before_node:
                new_prop = f"{key} = {formatted_value}\n\t\t"
            else:
                new_prop = f"\n\t\t{key} = {formatted_value}\n\t"
            
            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]
            
        self.refresh()

    def update_option_ai_chance(self, option_index, value):
        self.update_option_property(option_index, "ai_chance", str(value))

    def on_trigger_type_changed(self, checked):
        if self.updating or not checked:
            return
        
        is_triggered_only = self.triggered_only.isChecked()
        
        if is_triggered_only:
            # 自然発生しない場合、is_triggered_only = yes を設定し、他を削除
            self.replace_property("is_triggered_only", "yes")
            self.replace_property("trigger", "")
            self.replace_property("mean_time_to_happen", "")
        else:
            # 通常発生の場合、is_triggered_only を削除
            self.replace_property("is_triggered_only", "")
            
        self.reformat_event(self.selected_event_id)
        self.update_trigger_ui()

    def update_trigger_ui(self):
        is_triggered_only = self.triggered_only.isChecked()
        if self.trigger:
            self.trigger.setEnabled(not is_triggered_only)
        if self.mtth:
            self.mtth.setEnabled(not is_triggered_only)

    def on_doc_prop_edited(self, prop_key):
        if self.updating: return
        widget = self.doc_prop_widgets.get(prop_key)
        if widget:
            self.replace_top_level_property(prop_key, widget.text())


    def replace_top_level_property(self, property_name, replacement):
        if self.updating: return
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        text = self.widget.content
        
        target = None
        for item in doc.ast.items:
            if isinstance(item, AssignmentNode) and item.key == property_name:
                target = item
                break
        
        if not replacement:
            if target:
                start = target.range.start_offset
                end = target.range.end_offset
                if start > 0 and text[start-1] == "\n": start -= 1
                self.widget.content = text[:start] + text[end:]
                self.refresh()
            return

        if target:
            val_range = target.value.range
            self.widget.content = text[:val_range.start_offset] + replacement + text[val_range.end_offset:]
        else:
            new_prop = f"{property_name} = {replacement}\n\n"
            self.widget.content = new_prop + text
            
        self.refresh()

    def connect_scalar(self, control, property_name):
        if control:
            control.editingFinished.connect(lambda name=property_name, edit=control: self.replace_property(name, edit.text()))

    def connect_bool(self, control, property_name):
        if control:
            def on_toggled(checked, name=property_name):
                settings = self.get_plugin_settings()
                val = "yes" if checked else ("no" if settings.get("explicit_no_export", False) else "")
                self.replace_property(name, val)
            control.toggled.connect(on_toggled)

    def replace_property(self, property_name, replacement):
        if self.updating:
            return
        event = self.current_event()
        if not event:
            return
            
        assignment = event.first(property_name)
        text = self.widget.content

        if not replacement:
            if property_name == "picture":
                replacement = "none"
            else:
                # 削除
                if assignment:
                    start = assignment.range.start_offset
                    end = assignment.range.end_offset
                    if start > 0 and text[start-1] == "\n": start -= 1
                    self.widget.content = text[:start] + text[end:]
                    self.refresh()
                return

        # 更新または追加
        is_object = property_name in {"trigger", "mean_time_to_happen", "immediate", "after"}
        if is_object:
            # 各行にインデントを追加
            indented = "\n".join(["\t\t" + line if line.strip() else line for line in replacement.splitlines()])
            formatted_val = f"{{\n{indented}\n\t}}"
        else:
            formatted_val = replacement

        if assignment:
            # 更新
            value_range = assignment.value.range
            self.widget.content = text[:value_range.start_offset] + formatted_val + text[value_range.end_offset:]
        else:
            # プロパティの論理的な順序定義
            order = [
                "id", "title", "desc", "picture",
                "fire_only_once", "hidden", "major", "fire_for_sender", "timeout_days",
                "is_triggered_only", "trigger", "mean_time_to_happen", "immediate",
                "option", "after"
            ]
            
            try:
                target_idx = order.index(property_name)
            except ValueError:
                target_idx = len(order) - 1 # optionの手前付近

            # 挿入場所を特定
            insertion_offset = event.node.range.end_offset - 1
            insert_before_node = None
            
            if isinstance(event.node.value, ObjectNode):
                for item in event.node.value.items:
                    if isinstance(item, AssignmentNode):
                        try:
                            idx = order.index(item.key)
                        except ValueError:
                            idx = len(order) - 1
                        
                        if idx > target_idx:
                            if insert_before_node is None or item.range.start_offset < insertion_offset:
                                insertion_offset = item.range.start_offset
                                insert_before_node = item
            
            if insert_before_node:
                # 他の項目の前に挿入
                new_prop = f"{property_name} = {formatted_val}\n\t"
            else:
                # 末尾（閉じ括弧の前）に挿入
                new_prop = f"\n\t{property_name} = {formatted_val}\n"

            self.widget.content = text[:insertion_offset] + new_prop + text[insertion_offset:]

        if property_name == "id":
            self.selected_event_id = replacement
            
        self.reformat_event(self.selected_event_id)

    def reformat_event(self, event_id):
        if not event_id: return
        # メモリ上のデータから再度パースして最新の状態を取得
        text = self.widget.content
        events = self.parser.parse_document(self.file_path, text).events

        target = None
        for ev in events:
            if ev.event_id == event_id:
                target = ev
                break
        
        if not target: return
        
        # インデントレベルの決定 (イベントは1段)
        indent_level = 1
        tabs = "\t" * indent_level
        
        # ブロックの中身を再構築
        config = self.format_config.get("event", {})
        key_order = config.get("key_order", [])
        
        # 既存のノードを辞書に整理
        nodes = {}
        if isinstance(target.node.value, ObjectNode):
            for item in target.node.value.items:
                if isinstance(item, AssignmentNode):
                    # 同一キーが複数ある場合（optionなど）はリストで保持
                    if item.key not in nodes:
                        nodes[item.key] = []
                    nodes[item.key].append(item)
        
        lines = []
        used_keys = set()
        
        # 定義された順序に従って追加（空行対応）
        for key in key_order:
            if key == "": # 空行（スペーサー）
                if lines and lines[-1] != "":
                    lines.append("")
                continue
                
            if key in nodes:
                for node in nodes[key]:
                    formatted = self.format_ast_node(node, indent_level)
                    if formatted:
                        lines.append(f"{tabs}{formatted}")
                used_keys.add(key)
        
        # 定義にないキーを追加
        for key, node_list in nodes.items():
            if key not in used_keys:
                for node in node_list:
                    formatted = self.format_ast_node(node, indent_level)
                    if formatted:
                        lines.append(f"{tabs}{formatted}")
        
        # 末尾の空行を削除
        while lines and lines[-1] == "":
            lines.pop()
        
        inner_text = "\n".join(lines)
        node_range = target.node.value.range
        new_text = text[:node_range.start_offset + 1] + "\n" + inner_text + "\n" + text[node_range.end_offset - 1:]
        
        self.widget.content = new_text
        self.refresh()

    def format_ast_node(self, node, indent_level):
        from plugins.hoi4.script_parser import ScalarNode, ObjectNode, AssignmentNode
        if isinstance(node, AssignmentNode):
            val = self.format_ast_node(node.value, indent_level)
            return f"{node.key} = {val}"
        if isinstance(node, ScalarNode):
            return node.raw
        if isinstance(node, ObjectNode):
            tabs = "\t" * (indent_level + 1)
            inner_lines = []
            for item in node.items:
                formatted = self.format_ast_node(item, indent_level + 1)
                if formatted:
                    inner_lines.append(f"{tabs}{formatted}")
            
            close_tabs = "\t" * indent_level
            return "{\n" + "\n".join(inner_lines) + f"\n{close_tabs}}}"
        return ""

    def index_for_event_id(self, event_id):
        if not event_id:
            return -1
        for index, event in enumerate(self.events):
            if event.event_id == event_id:
                return index
        return -1

    def update_localisation_ui(self):
        """現在の入力キーに基づいてUI（本文の編集可否や保存先）を更新する"""
        plugin = self.get_hoi4_plugin()
        if not plugin or not hasattr(plugin, "localisation_registry"):
            return
            
        registry = plugin.localisation_registry
        
        # タイトルキーの判定
        title_key = self.widget.findChild(QLineEdit, "titleKeyEdit").text()
        status, entry = registry.search_key_status(title_key)
        self._apply_loc_status("title", status, entry)
        
        # 説明キーの判定
        desc_key = self.widget.findChild(QLineEdit, "descKeyEdit").text()
        status, entry = registry.search_key_status(desc_key)
        self._apply_loc_status("desc", status, entry)

    def _apply_loc_status(self, prefix, status, entry):
        """ステータスに応じたUI表示の切り替え"""
        text_edit = self.title_text if prefix == "title" else self.desc_text
        path_label = self.title_loc_file if prefix == "title" else self.desc_loc_file
        
        if not text_edit or not path_label: return
        
        # ファイル自体のエラーを取得
        errors = []
        if entry:
            plugin = self.get_hoi4_plugin()
            if plugin and hasattr(plugin, "localisation_registry"):
                registry = plugin.localisation_registry
                errors = registry.get_file_errors(entry["file"])
        
        error_msg = ""
        if errors:
            error_msg = f" [! ERROR: {errors[0].get('reason') if isinstance(errors[0], dict) else errors[0]}]"

        if status == "exists_in_mod" or status == "duplicate":
            text_edit.setReadOnly(False)
            if entry: self._set_loc_text(text_edit, entry["value"])
            path_label.setReadOnly(True)
            path_label.setText(f"{os.path.basename(entry['file'])}{error_msg}")
            if entry and entry.get("candidates"):
                path_label.setToolTip("\n".join(candidate["file"] for candidate in entry["candidates"]))
            path_label.setStyleSheet("color: #4caf50;" if not errors else "color: #f44336;") # エラー時は赤
        elif status == "exists_in_hoi4":
            text_edit.setReadOnly(True)
            if entry: self._set_loc_text(text_edit, entry["value"])
            path_label.setReadOnly(True)
            path_label.setText(f"{os.path.basename(entry['file'])}{error_msg}")
            if entry and entry.get("candidates"):
                path_label.setToolTip("\n".join(candidate["file"] for candidate in entry["candidates"]))
            path_label.setStyleSheet("color: #ff9800;") # オレンジ系
        else: # not_found
            text_edit.setReadOnly(False)
            was_readonly = path_label.isReadOnly()
            path_label.setReadOnly(False)
            if was_readonly or not path_label.text().strip() or not path_label.text().strip().lower().endswith(".yml"):
                path_label.setText(self.default_loc_filename())
            path_label.setToolTip("未登録キーの保存先ファイル名")
            path_label.setStyleSheet("color: #2196f3;") # 青系

    def _set_loc_text(self, widget, text):
        if hasattr(widget, "setPlainText"):
            set_plain(widget, text)
        elif hasattr(widget, "setText"):
            set_line(widget, text)

    def _get_loc_text(self, widget):
        if not widget:
            return ""
        if hasattr(widget, "toPlainText"):
            return widget.toPlainText()
        if hasattr(widget, "text"):
            return widget.text()
        return ""

    def default_loc_filename(self):
        settings = self.get_plugin_settings()
        fmt = settings.get("event_loc_file_format", "{namespace}_{lang}.yml")
        event = self.current_event()
        event_id = event.event_id if event else ""
        return self.apply_format(
            fmt,
            **self.format_values(
                namespace=self.get_current_namespace(),
                event_id=event_id,
                number=self.current_event_number(),
                option_index=0,
            ),
        )

    def selected_loc_filename(self, widget):
        filename = widget.text().strip() if widget and hasattr(widget, "text") else ""
        if not filename or not filename.lower().endswith(".yml"):
            filename = self.default_loc_filename()
        return filename

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
        
        # 保存先ファイルの決定
        if status == "exists_in_mod" or status == "duplicate":
            save_path = entry["file"]
            
            # 衝突チェック: 保存前にファイルの最終更新日時を確認
            if os.path.exists(save_path):
                registry.update_file(save_path, "mod")
                status, entry = registry.search_key_status(key)
                if status == "exists_in_hoi4":
                    print(f"Skipping save for HOI4 internal key after refresh: {key}")
                    return
                if status == "exists_in_mod" or status == "duplicate":
                    save_path = entry["file"]
            else:
                registry.remove_file_entries(save_path)
                status, entry = registry.search_key_status(key)
                if status == "exists_in_hoi4":
                    print(f"Skipping save for HOI4 internal key after file deletion: {key}")
                    return
                mod_root = self.get_mod_root()
                filename = self.selected_loc_filename(loc_file_widget)
                save_path = os.path.join(mod_root, "localisation", filename)
        else:
            # 新規作成: 既定のファイル名を使用
            mod_root = self.get_mod_root()
            filename = self.selected_loc_filename(loc_file_widget)
            save_path = os.path.join(mod_root, "localisation", filename)

        # 最終確認メッセージ（必要に応じて）
        # core.api.set_progress(f"Saving localisation: {key}...", 50)

        save_empty_loc = settings.get("save_empty_localisation", False)
        self._write_to_loc_file(save_path, key, text, lang, save_empty_loc)
        
        # 監視イベントによる二重更新を防ぎつつ、レジストリを即時更新
        try:
            registry.update_file(save_path, "mod")
            registry.set_ignore_path(save_path, True)
        finally:
            # 少し遅らせて解除（OSのファイル書き込み完了待ち）
            QTimer.singleShot(500, lambda: registry.set_ignore_path(save_path, False))
        
        # UIを再更新
        self.update_localisation_ui()

    def _write_to_loc_file(self, path, key, text, lang, save_empty_loc=False):
        """ファイルへの書き込み実処理"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        header = f"{lang}:"
        escaped_text = text.replace("\\", "\\\\").replace('"', '\\"')
        new_line = f' {key}: "{escaped_text}"'
        
        lines = []
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8-sig') as f:
                lines = f.readlines()
        
        # ヘッダーチェックと更新
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
                # 設定により削除
                del lines[found_key_idx]
            else:
                # 既存キーの置換
                lines[found_key_idx] = new_line + "\n"
        else:
            if not text.strip() and not save_empty_loc:
                # そもそも書かない
                return
                
            # 追記
            if not lines or not has_header:
                if not lines: lines.append(header + "\n")
                else: lines.insert(0, header + "\n")
            lines.append(new_line + "\n")

        with open(path, 'w', encoding='utf-8-sig') as f:
            f.writelines(lines)

    def get_hoi4_plugin(self):
        """本体からHOI4プラグインのインスタンスを探す"""
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

    def on_save_triggered(self):
        """本体からの保存要求時に呼ばれることを想定"""
        title_key = self.title_key.text() if self.title_key else ""
        title_text = self._get_loc_text(self.title_text)
        self.save_localisation(title_key, title_text, self.title_loc_file)
        
        desc_key = self.desc_key.text() if self.desc_key else ""
        desc_text = self._get_loc_text(self.desc_text)
        self.save_localisation(desc_key, desc_text, self.desc_loc_file)


def first(values):
    return values[0] if values else None


def find(widget, cls, name):
    return widget.findChild(cls, name)


def scalar_text(assignment: Optional[AssignmentNode]) -> str:
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return ""
    return str(assignment.value.value)


def prop_text(event: Optional[ParsedEvent], name: str) -> str:
    return scalar_text(event.first(name)) if event else ""


def prop_bool(event: Optional[ParsedEvent], name: str) -> bool:
    assignment = event.first(name) if event else None
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return False
    return bool(assignment.value.value)


def block_text(content: str, node: Optional[AssignmentNode], name: str) -> str:
    if not node:
        return ""
    
    target_node = node
    if name:
        # 子要素から検索
        target_node = None
        if isinstance(node.value, ObjectNode):
            for item in node.value.items:
                if isinstance(item, AssignmentNode) and item.key == name:
                    target_node = item
                    break
    
    if not target_node:
        return ""

    val = target_node.value if hasattr(target_node, "value") else target_node
    if isinstance(val, ObjectNode):
        # {} の中身だけを返す
        inner = content[val.range.start_offset + 1 : val.range.end_offset - 1]
        lines = inner.strip("\r\n").splitlines()
        if not lines: return ""
        
        # 共通の最小インデント（タブまたはスペース）を削除
        import re
        margin = None
        for line in lines:
            if not line.strip(): continue
            match = re.match(r"^(\s*)", line)
            indent = match.group(1)
            if margin is None or len(indent) < len(margin):
                margin = indent
        
        if margin:
            lines = [line[len(margin):] if line.startswith(margin) else line for line in lines]
        
        return "\n".join(lines).strip("\r\n\t ")
    
    return content[val.range.start_offset : val.range.end_offset]


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


def set_combo(control, value):
    if not control:
        return
    was_blocked = control.blockSignals(True)
    index = control.findText(value, Qt.MatchFlag.MatchExactly)
    if index >= 0:
        control.setCurrentIndex(index)
    control.blockSignals(was_blocked)
