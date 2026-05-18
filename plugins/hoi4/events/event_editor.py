from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import core.api
from PySide6.QtCore import QFile, Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QPainterPath, QPolygonF, QFontMetrics
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
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsItem,
)

from plugins.hoi4.script_parser import (
    AssignmentNode,
    ObjectNode,
    ParsedEntity,
    ScalarNode,
)
from plugins.hoi4.base_editor import (
    BaseDocument,
    BaseEditorController,
    BaseParsedEntity,
    BaseParser,
    block_text,
    find,
    prop_bool,
    prop_text,
    scalar_text,
    set_checked,
    set_combo,
    set_line,
    set_plain,
    set_spin,
)

class ParsedEvent(BaseParsedEntity):
    def __init__(self, entity: ParsedEntity):
        super().__init__(entity)
        self.event_id = self.id
        self.key = "country_event"
        self.options: list[AssignmentNode] = []
        self.namespace = ""

@dataclass
class Document(BaseDocument):
    events: list[ParsedEvent] = field(default_factory=list)

class EventParser(BaseParser):
    document_class = Document
    entity_class = ParsedEvent
    collection_attr = "events"
    project_subdir = "events"
    progress_label = "Parsing events"

    def __init__(self, plugin=None):
        self.plugin = plugin
        base_dir = os.path.dirname(__file__)
        super().__init__(os.path.join(base_dir, "event_schema.json"))

    def extract_document_properties(self, doc: Document, ast, path: str) -> None:
        for item in getattr(ast, "items", []):
            if isinstance(item, AssignmentNode) and item.key == "add_namespace":
                if isinstance(item.value, ScalarNode):
                    doc.properties["add_namespace"] = str(item.value.value)

    def parse_document(self, path: str, content: str) -> Document:
        doc = super().parse_document(path, content)
        
        current_ns = ""
        ns_list = []
        
        for item in getattr(doc.ast, "items", []):
            if isinstance(item, AssignmentNode):
                if item.key == "add_namespace" and isinstance(item.value, ScalarNode):
                    current_ns = str(item.value.value)
                    if current_ns not in ns_list:
                        ns_list.append(current_ns)
                elif item.key in {"country_event", "news_event"} and isinstance(item.value, ObjectNode):
                    for ev in doc.events:
                        if ev.node == item:
                            ev.namespace = current_ns
                            break
                            
        doc.properties["namespaces"] = ns_list
        if ns_list:
            doc.properties["add_namespace"] = ns_list[0]
            
        return doc


    def wrap_entity(self, entity: ParsedEntity) -> ParsedEvent:
        event = ParsedEvent(entity)
        if isinstance(entity.node, AssignmentNode):
            event.key = entity.node.key
        event.options.extend(entity.properties.get("option", []))
        return event

    def parse_project(self, project_path: str) -> list[ParsedEvent]:
        return super().parse_project(project_path)

    def serialize_events(self, events: list[ParsedEvent]) -> list[dict]:
        return [{"id": e.event_id, "source_path": e.source_path, "key": getattr(e, "key", "country_event")} for e in events]

    def deserialize_events(self, data: list[dict]) -> list[ParsedEvent]:
        events = []
        for item in data:
            entity = ParsedEntity(
                schema_name="hoi4_event",
                id=item["id"],
                parent_id=None,
                source_path=item["source_path"]
            )
            pe = ParsedEvent(entity)
            pe.key = item.get("key", "country_event")
            events.append(pe)
        return events

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


class EventNodeItem(QGraphicsObject):
    def __init__(self, event_id: str, title: str, is_current: bool, is_external: bool, controller, parent=None, chain_root_id: str = "", chain_node_key: str = "", is_hidden_event: bool = False):
        super().__init__(parent)
        self.event_id = event_id
        self.title = title
        self.is_current = is_current
        self.is_external = is_external
        self.is_hidden_event = is_hidden_event
        self.controller = controller
        self.chain_root_id = chain_root_id
        self.chain_node_key = chain_node_key or event_id
        self.connections = []
        
        self.width = 200 if is_current else 180
        self.height = 60 if is_current else 50
        
        self.setAcceptHoverEvents(True)
        self.hovered = False
        self.setZValue(10)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        
    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)
        
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if self.is_current:
            bg_color = QColor("#2d5a27")
            border_color = QColor("#4caf50")
            text_color = QColor("#ffffff")
        elif self.is_external:
            bg_color = QColor("#2a2a2a")
            border_color = QColor("#555555")
            text_color = QColor("#888888")
        else:
            bg_color = QColor("#1e3d59")
            border_color = QColor("#17b978")
            text_color = QColor("#ffffff")
            
        if self.hovered and not self.is_current and not self.is_external:
            bg_color = bg_color.lighter(130)
            border_color = border_color.lighter(130)
            
        rect = self.boundingRect()
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        
        painter.fillPath(path, QBrush(bg_color))
        
        pen = QPen(border_color, 2 if self.is_current else 1)
        if self.is_external or self.is_hidden_event:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPath(path)
        
        # ID
        font_id = QFont("sans-serif", 9, QFont.Weight.Bold if self.is_current else QFont.Weight.Normal)
        painter.setFont(font_id)
        painter.setPen(text_color)
        id_rect = QRectF(10, 5, self.width - 20, 20)
        painter.drawText(id_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.event_id)
        
        # Title
        font_title = QFont("sans-serif", 8)
        painter.setFont(font_title)
        painter.setPen(text_color.darker(110) if not self.is_external else text_color)
        title_rect = QRectF(10, 25 if self.is_current else 22, self.width - 20, 25 if self.is_current else 22)
        display_title = self.title if self.title else "(ローカライズなし)"
        if self.is_external:
            display_title = "(外部のイベント)"
            
        metrics = QFontMetrics(font_title)
        elided = metrics.elidedText(display_title, Qt.TextElideMode.ElideRight, int(self.width - 20))
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)
        
    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)
        
    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for connection in self.connections:
                connection.update_path()
            if not getattr(self.controller, "_updating_chain_layout", False):
                self.controller.remember_chain_node_position(self)
        return super().itemChange(change, value)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)
            
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.is_current and not self.is_external:
            event.accept()
            self.controller.open_chain_event(self.event_id)
        else:
            super().mouseDoubleClickEvent(event)


class ChainConnectionItem(QGraphicsPathItem):
    def __init__(self, start_node: EventNodeItem, end_node: EventNodeItem, label: str):
        super().__init__()
        self.start_node = start_node
        self.end_node = end_node
        self.label = label

        self.setPen(QPen(QColor("#778899"), 1.5, Qt.PenStyle.SolidLine))
        self.setZValue(1)

        self.arrow_item = QGraphicsPolygonItem(self)
        self.arrow_item.setBrush(QBrush(QColor("#778899")))
        self.arrow_item.setPen(QPen(Qt.GlobalColor.transparent))
        self.arrow_item.setZValue(2)

        self.label_bg_item = QGraphicsRectItem(self)
        self.label_bg_item.setBrush(QBrush(QColor("#151515")))
        self.label_bg_item.setPen(QPen(QColor("#2f3a42"), 1))
        self.label_bg_item.setZValue(8)

        self.label_text_item = QGraphicsTextItem(label, self)
        self.label_text_item.setDefaultTextColor(QColor("#b0c4de"))
        self.label_text_item.setFont(QFont("sans-serif", 7))
        self.label_text_item.setZValue(9)

        start_node.connections.append(self)
        end_node.connections.append(self)
        self.update_path()

    def update_path(self):
        start_center_x = self.start_node.pos().x() + self.start_node.width / 2
        end_center_x = self.end_node.pos().x() + self.end_node.width / 2
        if end_center_x >= start_center_x:
            start_x = self.start_node.pos().x() + self.start_node.width
            end_x = self.end_node.pos().x()
        else:
            start_x = self.start_node.pos().x()
            end_x = self.end_node.pos().x() + self.end_node.width

        start = QPointF(start_x, self.start_node.pos().y() + self.start_node.height / 2)
        end = QPointF(end_x, self.end_node.pos().y() + self.end_node.height / 2)

        path = QPainterPath()
        path.moveTo(start)
        ctrl_dist = abs(end.x() - start.x()) * 0.4
        ctrl1 = QPointF(start.x() + ctrl_dist, start.y())
        ctrl2 = QPointF(end.x() - ctrl_dist, end.y())
        path.cubicTo(ctrl1, ctrl2, end)
        self.setPath(path)

        arrow_size = 6
        dx = end.x() - ctrl2.x()
        dy = end.y() - ctrl2.y()
        length = (dx * dx + dy * dy) ** 0.5
        arrow_head = QPolygonF()
        if length > 0:
            ux = dx / length
            uy = dy / length
            arrow_head.append(end)
            arrow_head.append(QPointF(end.x() - arrow_size * ux + (arrow_size / 2) * uy, end.y() - arrow_size * uy - (arrow_size / 2) * ux))
            arrow_head.append(QPointF(end.x() - arrow_size * ux - (arrow_size / 2) * uy, end.y() - arrow_size * uy + (arrow_size / 2) * ux))
        self.arrow_item.setPolygon(arrow_head)

        if not self.label:
            self.label_bg_item.hide()
            self.label_text_item.hide()
            return

        mid_x = (start.x() + end.x()) / 2
        mid_y = (start.y() + end.y()) / 2
        self.label_text_item.setTextWidth(max(84, min(150, abs(end.x() - start.x()) - 18)))
        txt_rect = self.label_text_item.boundingRect()
        label_padding_x = 6
        label_padding_y = 2

        self.label_bg_item.setRect(
            mid_x - txt_rect.width() / 2 - label_padding_x,
            mid_y - txt_rect.height() / 2 - label_padding_y,
            txt_rect.width() + label_padding_x * 2,
            txt_rect.height() + label_padding_y * 2,
        )
        self.label_text_item.setPos(mid_x - txt_rect.width() / 2, mid_y - txt_rect.height() / 2)
        self.label_bg_item.show()
        self.label_text_item.show()


def setup(widget, file_path, content):
    controller = EventEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    widget.set_params = controller.set_params
    widget.setParams = controller.set_params
    controller.bind()
    
    # エディタの準備が完了したことを本体に通知
    core.api.notify_editor_ready(widget)


class EventEditorController(BaseEditorController):
    ELEMENT_ID = "events"
    DEFAULT_FORMAT_FILE = "event_format.json"

    def __init__(self, widget, file_path, content):
        super().__init__(widget, file_path, content)
        self.events: list[ParsedEvent] = []
        self.selected_event_id = ""
        self.localization_updates = {} # ローカライズの更新内容を保持
        self.parser = EventParser(self.get_hoi4_plugin() or object())
        self.loc_timer = QTimer()
        self.loc_timer.setSingleShot(True)
        self.loc_timer.timeout.connect(self.update_localisation_ui)
        core.api.register_loc_changed_handler(self.refresh)
        self.chain_node_positions = {}
        self._updating_chain_layout = False
        self._chain_project_signature = None
        self._chain_project_events: list[ParsedEvent] = []
        
        self.is_detailed_mode = False
        self.system_widgets = []

    def get_current_namespace(self):
        """現在のファイル内で定義されているネームスペースを取得する"""
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            return doc.properties.get("add_namespace", "")
        except Exception:
            return ""

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
        if self.event_list:
            self.event_list.setDragEnabled(True)
            self.event_list.setAcceptDrops(True)
            self.event_list.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
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

        self.chain_panel = find(self.widget, QGraphicsView, "chainPanel")
        if self.chain_panel:
            self.chain_scene = QGraphicsScene()
            self.chain_panel.setScene(self.chain_scene)
            self.chain_panel.setBackgroundBrush(QBrush(QColor("#111111")))
            self.chain_panel.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.chain_panel.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self.title_text:
            self.title_text.editingFinished.connect(self.update_preview)
            self.title_text.textChanged.connect(self.on_title_text_changed)
        if self.event_id:
            self.event_id.editingFinished.connect(self.on_title_text_changed)
        if self.title_key:
            self.title_key.editingFinished.connect(self.on_title_text_changed)
        if self.desc_text: self.desc_text.textChanged.connect(self.update_preview)

        # ドキュメントプロパティのバインド
        for prop_key, prop_def in self.parser.schema.get("document_properties", {}).items():
            widget_name = prop_def.get("ui_widget")
            if widget_name:
                widget = find(self.widget, QLineEdit, widget_name)
                if widget:
                    self.doc_prop_widgets[prop_key] = widget
                    if prop_key == "add_namespace":
                        widget.editingFinished.connect(lambda k=prop_key: self.on_doc_prop_edited(k))
                        self.btn_add_ns = find(self.widget, QToolButton, "btnAddNamespace")
                        if self.btn_add_ns:
                            self.btn_add_ns.clicked.connect(self.on_add_namespace_clicked)
                    else:
                        widget.editingFinished.connect(lambda k=prop_key: self.on_doc_prop_edited(k))

        if self.event_list:
            self.event_list.currentItemChanged.connect(self.on_event_selected)
            self.event_list.model().layoutChanged.connect(self.serialize_document_by_tree)

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
            self.trigger.focusOutEvent = lambda event: self.on_text_focus_out("trigger", self.trigger, event)
        if self.mtth:
            self.mtth.focusOutEvent = lambda event: self.on_text_focus_out("mean_time_to_happen", self.mtth, event)
        if self.immediate:
            self.immediate.focusOutEvent = lambda event: self.on_text_focus_out("immediate", self.immediate, event)
        if self.after:
            self.after.focusOutEvent = lambda event: self.on_text_focus_out("after", self.after, event)

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

        # 翻訳先参照ボタンのバインド
        title_btn = find(self.widget, object, "titleLocFileBrowseButton")
        if title_btn and self.title_loc_file:
            title_btn.clicked.connect(lambda: self.browse_loc_file(self.title_loc_file))
            
        desc_btn = find(self.widget, object, "descLocFileBrowseButton")
        if desc_btn and self.desc_loc_file:
            desc_btn.clicked.connect(lambda: self.browse_loc_file(self.desc_loc_file))

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

    def set_params(self, params):
        """外部から渡されたパラメータ（target_id等）を処理する"""
        if not params:
            return
            
        target_id = params.get("target_id")
        if target_id == "file_settings":
            self.selected_event_id = "__file_settings__"
            self.select_event_tree_item("file_settings")
        elif target_id and self.event_list:
            # リスト内を検索して選択を切り替える
            self.selected_event_id = target_id
            self.select_event_tree_item(target_id)

    def select_event_tree_item(self, target_id):
        if not self.event_list:
            return
        for i in range(self.event_list.topLevelItemCount()):
            top_item = self.event_list.topLevelItem(i)
            data = top_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, str) and data.startswith("namespace_settings:"):
                ns = data.split(":", 1)[1]
                if target_id == f"namespace_settings:{ns}" or (target_id == "file_settings" and i == 0):
                    self.event_list.setCurrentItem(top_item)
                    self.event_list.scrollToItem(top_item)
                    return
            for j in range(top_item.childCount()):
                item = top_item.child(j)
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, ParsedEvent) and data.event_id == target_id:
                    self.event_list.setCurrentItem(item)
                    self.event_list.scrollToItem(item)
                    return
                elif isinstance(data, str) and data == target_id:
                    self.event_list.setCurrentItem(item)
                    self.event_list.scrollToItem(item)
                    return

    def open_chain_event(self, event_id: str):
        local_event = self.find_event_by_id(event_id)
        if local_event:
            self.select_event_tree_item(event_id)
            return

        for event in self.get_chain_events():
            if event.event_id != event_id:
                continue
            source_path = event.source_path
            if source_path and os.path.exists(source_path):
                core.api.open_tab(source_path, "event_editor", {"target_id": event_id})
            return

    def resolve_event_label(self, event: ParsedEvent, is_current=False) -> str:
        title_val = ""
        if is_current and self.title_text:
            title_val = self.title_text.text().strip()
            
        if not title_val:
            plugin = self.get_hoi4_plugin()
            registry = getattr(plugin, "localisation_registry", None) if plugin else None
            title_assign = event.first("title")
            title_key = scalar_text(title_assign)
            if registry and title_key:
                status, entry = registry.search_key_status(title_key)
                if entry and entry.get("value"):
                    title_val = entry["value"].strip()
                    
        if title_val:
            return title_val
            
        title_assign = event.first("title")
        title_key = scalar_text(title_assign)
        if title_key:
            return title_key
            
        return event.event_id or f"{event.key}@{event.node.range.start.line}"

    def refresh(self):
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
                    
                    namespaces = getattr(doc, "properties", {}).get("namespaces", [])
                    if not namespaces:
                        namespaces = [""]
                        
                    ns_items = {}
                    target_item = None
                    
                    for ns in namespaces:
                        root_label = ns or os.path.basename(self.file_path)
                        root_item = QTreeWidgetItem(self.event_list)
                        root_item.setText(0, root_label)
                        root_item.setData(0, Qt.ItemDataRole.UserRole, f"namespace_settings:{ns}")
                        root_item.setExpanded(True)
                        flags = root_item.flags() | Qt.ItemFlag.ItemIsDropEnabled
                        flags &= ~Qt.ItemFlag.ItemIsDragEnabled
                        if ns:
                            flags |= Qt.ItemFlag.ItemIsEditable
                        root_item.setFlags(flags)
                        ns_items[ns] = root_item
                        
                        if selected == f"namespace_settings:{ns}":
                            target_item = root_item
                            
                    if selected == "__file_settings__" and ns_items:
                        target_item = list(ns_items.values())[0]
                        
                    for event in self.events:
                        ns = getattr(event, "namespace", "")
                        parent_item = ns_items.get(ns)
                        if not parent_item:
                            if "" in ns_items:
                                parent_item = ns_items[""]
                            else:
                                root_item = QTreeWidgetItem(self.event_list)
                                root_item.setText(0, ns or os.path.basename(self.file_path))
                                root_item.setData(0, Qt.ItemDataRole.UserRole, f"namespace_settings:{ns}")
                                root_item.setExpanded(True)
                                flags = root_item.flags() | Qt.ItemFlag.ItemIsDropEnabled
                                flags &= ~Qt.ItemFlag.ItemIsDragEnabled
                                if ns:
                                    flags |= Qt.ItemFlag.ItemIsEditable
                                root_item.setFlags(flags)
                                ns_items[ns] = root_item
                                parent_item = root_item
                                
                        is_curr = (event.event_id == selected)
                        label = self.resolve_event_label(event, is_current=is_curr)
                        
                        item = QTreeWidgetItem(parent_item)
                        item.setText(0, label)
                        item.setData(0, Qt.ItemDataRole.UserRole, event.event_id)
                        flags = item.flags() | Qt.ItemFlag.ItemIsDragEnabled
                        flags &= ~Qt.ItemFlag.ItemIsDropEnabled
                        item.setFlags(flags)
                        if event.event_id == selected:
                            target_item = item
                            
                    if target_item:
                        self.event_list.setCurrentItem(target_item)
                    elif self.event_list.topLevelItemCount() > 0:
                        first_parent = self.event_list.topLevelItem(0)
                        if first_parent.childCount() > 0:
                            self.event_list.setCurrentItem(first_parent.child(0))
                        else:
                            self.event_list.setCurrentItem(first_parent)
                            
                    self.load_event(self.current_event())
                finally:
                    self.event_list.setUpdatesEnabled(True)
                    self.event_list.blockSignals(was_blocked)
            
            # アクティブなネームスペースのテキスト連動
            active_ns = ""
            current_item = self.event_list.currentItem() if self.event_list else None
            if current_item:
                data = current_item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(data, ParsedEvent):
                    active_ns = getattr(data, "namespace", "")
                elif isinstance(data, str) and not data.startswith("namespace_settings:"):
                    ev = self.find_event_by_id(data)
                    active_ns = getattr(ev, "namespace", "") if ev else ""
                elif isinstance(data, str) and data.startswith("namespace_settings:"):
                    active_ns = data.split(":", 1)[1]
                    
            if not active_ns and namespaces:
                active_ns = namespaces[0]
                
            pass
                
            for prop_key, widget in self.doc_prop_widgets.items():
                if prop_key == "add_namespace":
                    continue
                val = getattr(doc, "properties", {}).get(prop_key, "")
                if widget.text() != val:
                    widget.setText(val)
            
            if self.new_event_btn:
                self.new_event_btn.setEnabled(bool(active_ns))
                self.new_event_btn.setToolTip("" if active_ns else "イベントを追加するにはネームスペースを定義してください")

            
            has_event = bool(self.current_event())
            if self.duplicate_event_btn:
                self.duplicate_event_btn.setEnabled(bool(active_ns) and has_event)
                if not active_ns:
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
                if not active_ns:
                    ns_widget.setStyleSheet("border: 1px solid #f44336; background-color: rgba(244, 67, 54, 0.1); border-radius: 4px;")
                else:
                    ns_widget.setStyleSheet("")
            
            # フォームとプレビューの表示制御
            has_namespace = bool(active_ns)
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

    def on_tree_item_changed(self, item, column):
        if self.updating:
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        new_text = item.text(0).strip()
        if not new_text:
            self.refresh()
            return
            
        # A. 親ノード (ネームスペース名) の編集時
        if isinstance(data, str) and data.startswith("namespace_settings:"):
            old_ns = data.split(":", 1)[1]
            if old_ns == new_text:
                return
                
            self.updating = True
            try:
                doc = self.parser.parse_document(self.file_path, self.widget.content)
                text = self.widget.content
                
                target = None
                for ast_item in doc.ast.items:
                    if isinstance(ast_item, AssignmentNode) and ast_item.key == "add_namespace":
                        from plugins.hoi4.script_parser import ScalarNode
                        val = str(ast_item.value.value) if isinstance(ast_item.value, ScalarNode) else ""
                        if val == old_ns:
                            target = ast_item
                            break
                            
                rename_all = False
                if old_ns and doc.events:
                    from PySide6.QtWidgets import QMessageBox
                    reply = QMessageBox.question(
                        self.widget,
                        "ID一括リネーム",
                        f"ネームスペースが '{old_ns}' から '{new_text}' に変更されました。\n"
                        f"ファイル内のイベントIDおよび関連するキー（例: {old_ns}.X -> {new_text}.X）を一括で更新しますか？",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        rename_all = True
                        
                if target:
                    val_range = target.value.range
                    text = text[:val_range.start_offset] + new_text + text[val_range.end_offset:]
                    
                if rename_all:
                    text = text.replace(f"{old_ns}.", f"{new_text}.")
                    
                self.widget.content = text
                self.selected_event_id = f"namespace_settings:{new_text}"
            finally:
                self.updating = False
                
            self.serialize_document_by_tree()
            self.refresh()
            
        pass

    def on_event_selected(self, current, previous):
        if self.updating:
            return
        self.updating = True
        try:
            if current and current.data(0, Qt.ItemDataRole.UserRole) == "file_settings":
                self.selected_event_id = "__file_settings__"
                self.load_event(None)
            else:
                self.load_event(self.current_event())
        finally:
            self.updating = False

    def find_event_by_id(self, event_id: str) -> Optional[ParsedEvent]:
        for event in getattr(self, "events", []):
            if event.event_id == event_id:
                return event
        return None

    def current_event(self) -> Optional[ParsedEvent]:
        if not self.event_list:
            return self.events[0] if self.events else None
        item = self.event_list.currentItem()
        if not item:
            return None
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(data, ParsedEvent):
            return data
        if isinstance(data, str) and not data.startswith("namespace_settings:"):
            return self.find_event_by_id(data)
        return None

    def load_event(self, event: Optional[ParsedEvent]):
        if event:
            self.selected_event_id = event.event_id
        elif self.selected_event_id != "__file_settings__":
            self.selected_event_id = ""
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
        self.update_event_chain()

    def on_title_text_changed(self, text=None):
        if self.updating or not self.event_list:
            return
        item = self.event_list.currentItem()
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        event = None
        if isinstance(data, ParsedEvent):
            event = data
        elif isinstance(data, str) and not data.startswith("namespace_settings:"):
            event = self.find_event_by_id(data)
            
        if isinstance(event, ParsedEvent):
            label = self.resolve_event_label(event, is_current=True)
            item.setText(0, label)

    def update_preview(self):
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
            
            loader = QUiLoader()
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
            name_key = scalar_text(first(properties.get("name", [])))
            name_edit = find(option_widget, QLineEdit, "nameKeyEdit")
            set_line(name_edit, name_key)
            if name_edit:
                name_edit.editingFinished.connect(lambda idx=i, edit=name_edit: self.update_option_property(idx, "name", edit.text()))
                
            name_text_edit = find(option_widget, QLineEdit, "nameTextEdit")
            if name_text_edit:
                if name_key:
                    name_text_edit.setText(self.localised_text(name_key))
                name_text_edit.editingFinished.connect(self.update_preview)

            opt_loc_edit = find(option_widget, QLineEdit, "optionLocFileEdit")
            opt_browse_btn = find(option_widget, QPushButton, "optionLocFileBrowseButton")
            if opt_loc_edit:
                opt_loc_edit.setReadOnly(True)
                plugin = self.get_hoi4_plugin()
                if plugin and hasattr(plugin, "localisation_registry") and name_key:
                    registry = plugin.localisation_registry
                    status, entry = registry.search_key_status(name_key)
                    if status in ("exists_in_mod", "duplicate") and entry:
                        opt_loc_edit.setText(os.path.basename(entry["file"]))
                        opt_loc_edit.setStyleSheet("color: #4caf50;")
                    elif status == "exists_in_hoi4" and entry:
                        opt_loc_edit.setText(os.path.basename(entry["file"]))
                        opt_loc_edit.setStyleSheet("color: #ff9800;")
                    else:
                        opt_loc_edit.setText(self.default_loc_filename())
                        opt_loc_edit.setStyleSheet("color: #2196f3;")
                else:
                    opt_loc_edit.setText(self.default_loc_filename())
                    opt_loc_edit.setStyleSheet("color: #2196f3;")

            if opt_browse_btn and opt_loc_edit:
                opt_browse_btn.clicked.connect(lambda _, edit=opt_loc_edit: self.browse_loc_file(edit))

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


    def on_add_namespace_clicked(self):
        ns_widget = self.doc_prop_widgets.get("add_namespace")
        if not ns_widget:
            return
            
        ns_text = ns_widget.text().strip()
        if not ns_text:
            return
            
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        namespaces = getattr(doc, "properties", {}).get("namespaces", [])
        
        if ns_text in namespaces:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self.widget,
                "追加不可",
                f"ネームスペース '{ns_text}' はすでに存在します。"
            )
            ns_widget.clear()
            return
            
        text = self.widget.content.rstrip()
        self.widget.content = text + f"\n\nadd_namespace = {ns_text}\n"
        
        self.selected_event_id = f"namespace_settings:{ns_text}"
        self.refresh()
        ns_widget.clear()


    def replace_top_level_property(self, property_name, replacement):
        if self.updating: return
        doc = self.parser.parse_document(self.file_path, self.widget.content)
        text = self.widget.content
        
        target = None
        for item in doc.ast.items:
            if isinstance(item, AssignmentNode) and item.key == property_name:
                target = item
                break
        
        if property_name == "add_namespace" and target and replacement:
            from PySide6.QtWidgets import QMessageBox
            from plugins.hoi4.script_parser import ScalarNode
            old_ns = str(target.value.value) if isinstance(target.value, ScalarNode) else ""
            if old_ns and old_ns != replacement and doc.events:
                reply = QMessageBox.question(
                    self.widget,
                    "ID一括リネーム",
                    f"ネームスペースが '{old_ns}' から '{replacement}' に変更されました。\n"
                    f"ファイル内のイベントIDおよび関連するキー（例: {old_ns}.X -> {replacement}.X）を一括で更新しますか？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.Yes:
                    text = text.replace(f"{old_ns}.", f"{replacement}.")
                    self.widget.content = text
                    self.serialize_document_by_tree()
                    self.refresh()
                    return

        if not replacement:
            if target:
                start = target.range.start_offset
                end = target.range.end_offset
                if start > 0 and text[start-1] == "\n": start -= 1
                self.widget.content = text[:start] + text[end:]
                self.serialize_document_by_tree()
                self.refresh()
            return

        if target:
            val_range = target.value.range
            self.widget.content = text[:val_range.start_offset] + replacement + text[val_range.end_offset:]
        else:
            new_prop = f"{property_name} = {replacement}\n\n"
            self.widget.content = new_prop + text
            
        self.serialize_document_by_tree()
        self.refresh()

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
            
        self.serialize_document_by_tree()
        self.refresh()

    def reformat_event(self, event_id):
        self.serialize_document_by_tree()
        self.refresh()

    def serialize_document_by_tree(self):
        if self.updating or not self.event_list:
            return
            
        was_blocked = self.event_list.blockSignals(True)
        self.updating = True
        try:
            sections = []
            for i in range(self.event_list.topLevelItemCount()):
                parent_item = self.event_list.topLevelItem(i)
                data = parent_item.data(0, Qt.ItemDataRole.UserRole)
                ns = ""
                if isinstance(data, str) and data.startswith("namespace_settings:"):
                    ns = data.split(":", 1)[1]
                    
                event_texts = []
                for j in range(parent_item.childCount()):
                    child_item = parent_item.child(j)
                    data = child_item.data(0, Qt.ItemDataRole.UserRole)
                    event = None
                    if isinstance(data, ParsedEvent):
                        event = data
                    elif isinstance(data, str) and not data.startswith("namespace_settings:"):
                        event = self.find_event_by_id(data)
                        
                    if isinstance(event, ParsedEvent):
                        event_text = self.serialize_event(event)
                        if event_text:
                            event_texts.append(event_text)
                            
                section = ""
                if ns:
                    section += f"add_namespace = {ns}"
                if event_texts:
                    if section:
                        section += "\n\n"
                    section += "\n\n".join(event_texts)
                    
                if section:
                    sections.append(section)
                    
            full_text = "\n\n".join(sections) + "\n"
            
            if self.widget.content != full_text:
                self.widget.content = full_text
                
        finally:
            self.updating = False
            self.event_list.blockSignals(was_blocked)
            
        self.refresh()

    def serialize_event(self, event: ParsedEvent) -> str:
        config = self.format_config.get("event", {})
        key_order = config.get("key_order", [])
        
        opt_config = self.format_config.get("option", {})
        opt_key_order = opt_config.get("key_order", ["name", "trigger", "ai_chance"])

        nodes = {}
        if isinstance(event.node.value, ObjectNode):
            for item in event.node.value.items:
                if isinstance(item, AssignmentNode):
                    if item.key not in nodes:
                        nodes[item.key] = []
                    nodes[item.key].append(item)

        lines = []
        used_keys = set()
        
        for key in key_order:
            if key == "":
                if lines and lines[-1] != "":
                    lines.append("")
                continue
                
            if key in nodes:
                for node in nodes[key]:
                    if key == "option":
                        formatted = self.serialize_option_node(node, opt_key_order, indent_level=1)
                    else:
                        formatted = self.serialize_ast_node(node, opt_key_order, indent_level=1)
                    if formatted:
                        lines.append(f"\t{formatted}")
                used_keys.add(key)

        for key, node_list in nodes.items():
            if key not in used_keys:
                for node in node_list:
                    formatted = self.serialize_ast_node(node, opt_key_order, indent_level=1)
                    if formatted:
                        lines.append(f"\t{formatted}")

        while lines and lines[-1] == "":
            lines.pop()

        inner_text = "\n".join(lines)
        return f"{event.key} = {{\n{inner_text}\n}}"

    def serialize_option_node(self, node, opt_key_order, indent_level) -> str:
        if not isinstance(node.value, ObjectNode):
            return self.serialize_ast_node(node, opt_key_order, indent_level)
            
        opt_nodes = {}
        for item in node.value.items:
            if isinstance(item, AssignmentNode):
                if item.key not in opt_nodes:
                    opt_nodes[item.key] = []
                opt_nodes[item.key].append(item)
                
        lines = []
        used_keys = set()
        tabs = "\t" * (indent_level + 1)
        
        for key in opt_key_order:
            if key in opt_nodes:
                for n in opt_nodes[key]:
                    formatted = self.serialize_ast_node(n, opt_key_order, indent_level + 1)
                    if formatted:
                        lines.append(f"{tabs}{formatted}")
                used_keys.add(key)
                
        for key, node_list in opt_nodes.items():
            if key not in used_keys:
                for n in node_list:
                    formatted = self.serialize_ast_node(n, opt_key_order, indent_level + 1)
                    if formatted:
                        lines.append(f"{tabs}{formatted}")
                        
        close_tabs = "\t" * indent_level
        inner_text = "\n".join(lines)
        return f"option = {{\n{inner_text}\n{close_tabs}}}"

    def serialize_ast_node(self, node, opt_key_order, indent_level) -> str:
        from plugins.hoi4.script_parser import ScalarNode, ObjectNode, AssignmentNode
        if isinstance(node, AssignmentNode):
            val = self.serialize_ast_node(node.value, opt_key_order, indent_level)
            return f"{node.key} = {val}"
        if isinstance(node, ScalarNode):
            return node.raw
        if isinstance(node, ObjectNode):
            tabs = "\t" * (indent_level + 1)
            inner_lines = []
            for item in node.items:
                formatted = self.serialize_ast_node(item, opt_key_order, indent_level + 1)
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

    def after_save_localisation(self, key, save_path: str):
        self.update_localisation_ui()

    def on_save_triggered(self):
        """本体からの保存要求時に呼ばれることを想定"""
        title_key = self.title_key.text() if self.title_key else ""
        title_text = self._get_loc_text(self.title_text)
        self.save_localisation(title_key, title_text, self.title_loc_file)
        
        desc_key = self.desc_key.text() if self.desc_key else ""
        desc_text = self._get_loc_text(self.desc_text)
        self.save_localisation(desc_key, desc_text, self.desc_loc_file)

    def extract_event_triggers(self, event: ParsedEvent) -> list[dict]:
        """イベントからトリガーされる他のイベントIDとコンテキストを抽出する"""
        triggers = []
        if not event:
            return triggers

        return self.extract_event_triggers_in_source_order(event)

    def extract_event_triggers_in_source_order(self, event: ParsedEvent) -> list[dict]:
        """イベント定義内の出現順で、他イベント呼び出しを抽出する。"""
        triggers = []
        option_names = self._event_option_labels(event)
        label_map = {
            "immediate": "即時効果",
            "after": "事後処理",
            "hidden_effect": "隠し効果",
        }

        if not isinstance(getattr(event, "node", None), AssignmentNode) or not isinstance(event.node.value, ObjectNode):
            return triggers

        option_index = 0
        for item in event.node.value.items:
            if not isinstance(item, AssignmentNode):
                continue

            if item.key == "option":
                context = option_names.get(id(item), f"選択肢 {option_index + 1}")
                option_index += 1
            else:
                context = label_map.get(item.key, item.key)

            triggers.extend(self._find_event_triggers_with_context(item, context))

        return triggers

    def _event_option_labels(self, event: ParsedEvent) -> dict[int, str]:
        option_names = {}
        for i, opt in enumerate(event.options):
            opt_name = f"選択肢 {i+1}"
            name_key = ""
            if isinstance(opt.value, ObjectNode):
                name_assign = first([item for item in opt.value.items if isinstance(item, AssignmentNode) and item.key == "name"])
                name_key = scalar_text(name_assign)
                plugin = self.get_hoi4_plugin()
                registry = getattr(plugin, "localisation_registry", None) if plugin else None
                status, entry = registry.search_key_status(name_key) if registry and name_key else ("not_found", None)
                if entry and entry.get("value"):
                    opt_name = entry["value"]
                elif name_key:
                    opt_name = name_key
            option_names[id(opt)] = opt_name
        return option_names

    def _find_event_triggers_with_context(self, node, context: str) -> list[dict]:
        triggers = []
        if isinstance(node, AssignmentNode):
            if node.key in {"country_event", "news_event"}:
                event_id = ""
                if isinstance(node.value, ScalarNode):
                    event_id = str(node.value.value)
                elif isinstance(node.value, ObjectNode):
                    id_assign = first([item for item in node.value.items if isinstance(item, AssignmentNode) and item.key == "id"])
                    if id_assign and isinstance(id_assign.value, ScalarNode):
                        event_id = str(id_assign.value.value)
                if event_id:
                    triggers.append({'id': event_id, 'context': context})
                return triggers
            triggers.extend(self._find_event_triggers_with_context(node.value, context))
        elif isinstance(node, ObjectNode):
            for item in node.items:
                triggers.extend(self._find_event_triggers_with_context(item, context))
        return triggers

    def _find_events_in_node(self, node) -> list[str]:
        """ノードから再帰的に country_event や news_event を探してイベントIDを抽出する"""
        events = []
        if isinstance(node, AssignmentNode):
            if node.key in {"country_event", "news_event"}:
                if isinstance(node.value, ScalarNode):
                    events.append(str(node.value.value))
                elif isinstance(node.value, ObjectNode):
                    id_assign = first([item for item in node.value.items if isinstance(item, AssignmentNode) and item.key == "id"])
                    if id_assign and isinstance(id_assign.value, ScalarNode):
                        events.append(str(id_assign.value.value))
            else:
                events.extend(self._find_events_in_node(node.value))
        elif isinstance(node, ObjectNode):
            for item in node.items:
                events.extend(self._find_events_in_node(item))
        return events

    def chain_position_key(self, node_item: EventNodeItem):
        return (node_item.chain_root_id, node_item.chain_node_key)

    def remember_chain_node_position(self, node_item: EventNodeItem):
        self.chain_node_positions[self.chain_position_key(node_item)] = (node_item.pos().x(), node_item.pos().y())
        if self.chain_scene:
            margin = 60
            self.chain_scene.setSceneRect(self.chain_scene.sceneRect().united(node_item.sceneBoundingRect().adjusted(-margin, -margin, margin, margin)))

    def apply_chain_node_position(self, node_item: EventNodeItem, x: float, y: float):
        saved = self.chain_node_positions.get(self.chain_position_key(node_item))
        if saved:
            x, y = saved
        node_item.setPos(x, y)

    def get_chain_events(self) -> list[ParsedEvent]:
        events_by_id = {}
        project_path = core.api.get_project_path()
        if project_path:
            scan_dir = self.parser.project_scan_dir(project_path)
            try:
                files = self.parser.iter_project_files(scan_dir) if os.path.exists(scan_dir) else []
                signature = tuple((os.path.normcase(path), os.path.getmtime(path)) for path in sorted(files))
                if signature != self._chain_project_signature:
                    self._chain_project_events = self.parser.parse_project(project_path)
                    self._chain_project_signature = signature
            except Exception:
                self._chain_project_events = []
                self._chain_project_signature = None

            current_path = os.path.normcase(os.path.abspath(self.file_path))
            for event in self._chain_project_events:
                source_path = os.path.normcase(os.path.abspath(event.source_path)) if event.source_path else ""
                if source_path == current_path:
                    continue
                if event.event_id:
                    events_by_id[event.event_id] = event

        for event in self.events:
            if event.event_id:
                events_by_id[event.event_id] = event

        return list(events_by_id.values())

    def chain_event_title(self, event: Optional[ParsedEvent], current_id: str) -> str:
        if not event:
            return ""
        if event.event_id == current_id and self.title_text:
            title_val = self.title_text.text().strip()
            if title_val:
                return title_val

        plugin = self.get_hoi4_plugin()
        registry = getattr(plugin, "localisation_registry", None) if plugin else None
        title_assign = event.first("title")
        title_key = scalar_text(title_assign)
        if registry and title_key:
            status, entry = registry.search_key_status(title_key)
            if entry and entry.get("value"):
                return entry["value"]
        return title_key or ""

    def update_full_event_chain(self, current_event: ParsedEvent):
        current_id = current_event.event_id
        events_by_id = {
            event.event_id: event
            for event in self.get_chain_events()
            if event.event_id
        }
        events_by_id[current_id] = current_event

        outgoing = {}
        incoming = {}
        edge_labels = {}
        edge_order = {}
        event_order = {event_id: index for index, event_id in enumerate(events_by_id.keys())}
        order_index = 0
        for event in events_by_id.values():
            source_id = event.event_id
            if not source_id:
                continue
            for trigger in self.extract_event_triggers(event):
                target_id = trigger.get("id", "")
                if not target_id:
                    continue
                targets = outgoing.setdefault(source_id, [])
                if target_id not in targets:
                    targets.append(target_id)
                    edge_order[(source_id, target_id)] = order_index
                    order_index += 1
                incoming.setdefault(target_id, set()).add(source_id)
                labels = edge_labels.setdefault((source_id, target_id), [])
                label = trigger.get("context", "")
                if label and label not in labels:
                    labels.append(label)

        connected_ids = set()
        pending = [current_id]
        while pending:
            event_id = pending.pop()
            if event_id in connected_ids:
                continue
            connected_ids.add(event_id)
            for next_id in outgoing.get(event_id, []):
                if next_id not in connected_ids:
                    pending.append(next_id)
            for prev_id in incoming.get(event_id, set()):
                if prev_id not in connected_ids:
                    pending.append(prev_id)

        edges = [
            (source_id, target_id, " / ".join(edge_labels.get((source_id, target_id), [])))
            for source_id in sorted(connected_ids, key=lambda event_id: event_order.get(event_id, 999999))
            for target_id in outgoing.get(source_id, [])
            if target_id in connected_ids
        ]

        roots = sorted(
            event_id for event_id in connected_ids
            if not any(source_id in connected_ids for source_id in incoming.get(event_id, set()))
        ) or [current_id]

        levels = {root: 0 for root in roots}
        for _ in range(max(1, len(connected_ids))):
            changed = False
            for source_id, target_id, _ in edges:
                if source_id not in levels:
                    continue
                next_level = levels[source_id] + 1
                if next_level > levels.get(target_id, -1):
                    levels[target_id] = next_level
                    changed = True
            if not changed:
                break

        for event_id in connected_ids:
            if event_id not in levels:
                levels[event_id] = 0 if event_id == current_id else levels.get(current_id, 0) + 1

        columns = {}
        for event_id in connected_ids:
            columns.setdefault(levels[event_id], []).append(event_id)

        def column_sort_key(event_id: str):
            parent_orders = [
                edge_order.get((source_id, event_id), 999999)
                for source_id in incoming.get(event_id, set())
                if source_id in connected_ids
            ]
            if parent_orders:
                return (min(parent_orders), event_id.lower())
            return (event_order.get(event_id, 999999), event_id.lower())

        for ids in columns.values():
            ids.sort(key=column_sort_key)

        margin_x = 40
        margin_y = 36
        horizontal_gap = 120
        vertical_gap = 34
        node_width = 180
        current_node_width = 200
        node_height = 50
        current_node_height = 60

        max_level = max(columns.keys()) if columns else 0
        max_rows = max((len(ids) for ids in columns.values()), default=1)
        column_width = max(current_node_width, node_width) + horizontal_gap
        content_height = max(current_node_height, max_rows * node_height + max(0, max_rows - 1) * vertical_gap)
        canvas_width = margin_x * 2 + max_level * column_width + max(current_node_width, node_width)
        canvas_height = max(350, content_height + margin_y * 2)

        def row_y(index: int, count: int) -> float:
            stack_height = count * node_height + max(0, count - 1) * vertical_gap
            return (canvas_height - stack_height) / 2 + index * (node_height + vertical_gap)

        chain_root_id = "|".join(sorted(connected_ids))
        self._updating_chain_layout = True
        node_items = {}
        for level in sorted(columns):
            ids = columns[level]
            x_pos = margin_x + level * column_width
            for index, event_id in enumerate(ids):
                event = events_by_id.get(event_id)
                is_current = event_id == current_id
                node_item = EventNodeItem(
                    event_id,
                    self.chain_event_title(event, current_id),
                    is_current=is_current,
                    is_external=event is None,
                    controller=self,
                    chain_root_id=chain_root_id,
                    chain_node_key=event_id,
                    is_hidden_event=prop_bool(event, "hidden") if event else False,
                )
                y_pos = row_y(index, len(ids))
                if is_current:
                    y_pos -= (current_node_height - node_height) / 2
                self.apply_chain_node_position(node_item, x_pos, y_pos)
                self.chain_scene.addItem(node_item)
                node_items[event_id] = node_item

        for source_id, target_id, label in edges:
            start_node = node_items.get(source_id)
            end_node = node_items.get(target_id)
            if start_node and end_node:
                self.draw_connection(start_node, end_node, label)

        scene_rect = QRectF(0, 0, canvas_width, canvas_height)
        for item in self.chain_scene.items():
            if isinstance(item, EventNodeItem):
                scene_rect = scene_rect.united(item.sceneBoundingRect().adjusted(-60, -60, 60, 60))
        self.chain_scene.setSceneRect(scene_rect)
        self._updating_chain_layout = False

    def update_event_chain(self):
        """イベントチェーン表示の更新"""
        if not hasattr(self, 'chain_scene') or not self.chain_scene:
            return

        self.chain_scene.clear()

        current_event = self.current_event()
        if not current_event:
            return

        self.update_full_event_chain(current_event)

    def draw_connection(self, start_node: EventNodeItem, end_node: EventNodeItem, label: str):
        """接続線と矢印、ラベルの描画"""
        connection = ChainConnectionItem(start_node, end_node, label)
        self.chain_scene.addItem(connection)


def first(values):
    return values[0] if values else None
