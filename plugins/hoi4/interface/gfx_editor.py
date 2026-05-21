from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import core.api
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from plugins.hoi4.base_editor import (
    BaseDocument,
    BaseEditorController,
    BaseParsedEntity,
    BaseParser,
    find,
    set_checked,
    set_combo,
    set_line,
    set_spin,
)
from plugins.hoi4.script_parser import AssignmentNode, ObjectNode, ParsedEntity, ScalarNode


EDITOR_NAME = "GFX Editor"

STRING_PROPERTIES = {
    "texturefile",
    "textureFile1",
    "textureFile2",
    "maskFile",
    "effectFile",
    "animationmaskfile",
    "animationtexturefile",
}
BOOL_PROPERTIES = {
    "horizontal",
    "allwaystransparent",
    "legacy_lazy_load",
    "transparencecheck",
    "looping",
    "play_on_show",
    "animationlooping",
}
NUMERIC_PROPERTIES = {
    "noOfFrames",
    "animation_rate_fps",
    "pause_on_loop",
    "animationrotation",
    "animationtime",
    "animationdelay",
}


class ParsedGfxDefinition(BaseParsedEntity):
    def __init__(self, entity: ParsedEntity):
        super().__init__(entity)
        self.gfx_type = entity.node.key if isinstance(entity.node, AssignmentNode) else "spriteType"
        self.group = entity.parent_id or "spriteTypes"


@dataclass
class GfxDocument(BaseDocument):
    definitions: list[ParsedGfxDefinition] = field(default_factory=list)


class GfxParser(BaseParser):
    document_class = GfxDocument
    entity_class = ParsedGfxDefinition
    collection_attr = "definitions"
    project_subdir = "interface"
    progress_label = "Parsing gfx"
    cache_key = "gfx"

    def __init__(self):
        base_dir = os.path.dirname(__file__)
        super().__init__(os.path.join(base_dir, "gfx_schema.json"))


def setup(widget, file_path, content):
    controller = GfxEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    widget.set_params = controller.set_params
    widget.setParams = controller.set_params
    widget.on_save_triggered = controller.on_save_triggered
    widget.on_save_as_triggered = controller.on_save_as_triggered
    controller.bind()
    core.api.notify_editor_ready(widget)


class GfxEditorController(BaseEditorController):
    ELEMENT_ID = "interface"
    DEFAULT_FORMAT_FILE = "gfx_format.json"

    def __init__(self, widget, file_path, content):
        super().__init__(widget, file_path, content)
        self.parser = GfxParser()
        self.definitions: list[dict] = []
        self.selected_index: Optional[int] = None
        self.preview_scene = None
        self.preview_item = None
        self.preview_placeholder = None
        self.fit_preview_to_view = lambda: None

    def bind(self):
        self.widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.widget.setVisible(True)
        self.widget.gfx_ui = self.widget

        title = os.path.basename(self.file_path) if self.file_path else "GFX Editor"
        self.widget.setWindowTitle(title)

        self.list_gfx_nodes = find(self.widget, QListWidget, "listGfxNodes")
        self.combo_gfx_type = find(self.widget, QComboBox, "comboGfxType")
        self.edit_source_path = find(self.widget, QLineEdit, "editSourcePath")
        self.btn_browse_source = find(self.widget, QPushButton, "btnBrowseSource")
        self.btn_new_node = find(self.widget, QPushButton, "btnNewNode")
        self.btn_duplicate_node = find(self.widget, QPushButton, "btnDuplicateNode")
        self.btn_delete_node = find(self.widget, QPushButton, "btnDeleteNode")
        self.graphics_texture_view = find(self.widget, QGraphicsView, "graphicsTextureView")
        self.widget_center_pane = find(self.widget, QStackedWidget, "widgetCenterPane")

        self.edit_name = find(self.widget, QLineEdit, "editName")
        self.edit_texture = find(self.widget, QLineEdit, "editTexture")
        self.edit_effect = find(self.widget, QLineEdit, "editEffect")
        self.edit_texture1 = find(self.widget, QLineEdit, "editTexture1")
        self.edit_texture2 = find(self.widget, QLineEdit, "editTexture2")
        self.edit_mask = find(self.widget, QLineEdit, "editMask")
        self.edit_color = find(self.widget, QLineEdit, "editColor")
        self.edit_color_two = find(self.widget, QLineEdit, "editColorTwo")

        self.spin_size_w = find(self.widget, QDoubleSpinBox, "spinSizeW")
        self.spin_size_h = find(self.widget, QDoubleSpinBox, "spinSizeH")
        self.spin_border_x = find(self.widget, QSpinBox, "spinBorderX")
        self.spin_border_y = find(self.widget, QSpinBox, "spinBorderY")
        self.spin_frames = find(self.widget, QSpinBox, "spinFrames")
        self.spin_rate = find(self.widget, QDoubleSpinBox, "spinRate")
        self.spin_pause_on_loop = find(self.widget, QDoubleSpinBox, "spinPauseOnLoop")

        self.check_horizontal = find(self.widget, QCheckBox, "checkHorizontal")
        self.check_transparent = find(self.widget, QCheckBox, "checkTransparent")
        self.check_lazy_load = find(self.widget, QCheckBox, "checkLazyLoad")
        self.check_transparence = find(self.widget, QCheckBox, "checkTransparenceCheck")
        self.check_looping = find(self.widget, QCheckBox, "checkLooping")
        self.check_play_on_show = find(self.widget, QCheckBox, "checkPlayOnShow")

        if self.list_gfx_nodes:
            self.list_gfx_nodes.currentItemChanged.connect(self.on_definition_selected)

        if self.btn_new_node:
            self.btn_new_node.clicked.connect(self.create_definition_from_image)
        if self.btn_duplicate_node:
            self.btn_duplicate_node.clicked.connect(self.duplicate_selected_definition)
            self.btn_duplicate_node.setEnabled(False)
        if self.btn_delete_node:
            self.btn_delete_node.clicked.connect(self.delete_selected_definition)
            self.btn_delete_node.setEnabled(False)
        if self.btn_browse_source:
            self.btn_browse_source.clicked.connect(self.browse_source)
        if self.combo_gfx_type:
            self.combo_gfx_type.currentIndexChanged.connect(self.on_type_changed)

        self.connect_line(self.edit_name, "name")
        self.connect_line(self.edit_texture, "texturefile", preview=True)
        self.connect_line(self.edit_effect, "effectFile")
        self.connect_line(self.edit_texture1, "textureFile1", preview=True)
        self.connect_line(self.edit_texture2, "textureFile2")
        self.connect_line(self.edit_mask, "maskFile")
        self.connect_line(self.edit_color, "color")
        self.connect_line(self.edit_color_two, "colortwo")
        self.connect_pair(self.spin_size_w, self.spin_size_h, "size")
        self.connect_pair(self.spin_border_x, self.spin_border_y, "borderSize")
        self.connect_number(self.spin_frames, "noOfFrames")
        self.connect_number(self.spin_rate, "animation_rate_fps")
        self.connect_number(self.spin_pause_on_loop, "pause_on_loop")
        self.connect_check(self.check_horizontal, "horizontal")
        self.connect_check(self.check_transparent, "allwaystransparent")
        self.connect_check(self.check_lazy_load, "legacy_lazy_load")
        self.connect_check(self.check_transparence, "transparencecheck")
        self.connect_check(self.check_looping, "looping")
        self.connect_check(self.check_play_on_show, "play_on_show")

        self.setup_preview_view()
        self.refresh()

    def setup_preview_view(self):
        if not self.graphics_texture_view:
            return

        self.preview_scene = QGraphicsScene(self.graphics_texture_view)
        self.graphics_texture_view.setScene(self.preview_scene)
        self.graphics_texture_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graphics_texture_view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.graphics_texture_view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        def fit_preview_to_view():
            if not self.preview_scene:
                return
            rect = self.preview_scene.sceneRect()
            if not rect.isNull() and rect.width() > 0 and rect.height() > 0:
                self.graphics_texture_view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

        self.fit_preview_to_view = fit_preview_to_view

        class PreviewResizeFilter(QObject):
            def __init__(self, controller):
                super().__init__(controller.graphics_texture_view)
                self.controller = controller

            def eventFilter(self, watched, event):
                if (
                    watched == self.controller.graphics_texture_view.viewport()
                    and event.type() == QEvent.Type.Resize
                ):
                    self.controller.fit_preview_to_view()
                    self.controller.sync_preview_placeholder_geometry()
                    self.controller.update_preview_placeholder_visibility()
                return False

        self.preview_resize_filter = PreviewResizeFilter(self)
        self.graphics_texture_view.viewport().installEventFilter(self.preview_resize_filter)

        self.preview_placeholder = QLabel(
            "定義を追加してください。",
            self.graphics_texture_view,
        )
        self.preview_placeholder.setObjectName("gfxPreviewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_placeholder.setStyleSheet(
            "QLabel { color: #9a9a9a; background: transparent; border: none; font-size: 14px; }"
        )
        self.preview_placeholder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.sync_preview_placeholder_geometry()

    def sync_preview_placeholder_geometry(self):
        if self.preview_placeholder and self.graphics_texture_view:
            self.preview_placeholder.setGeometry(self.graphics_texture_view.viewport().rect())

    def update_preview_placeholder_visibility(self):
        if not self.preview_placeholder:
            return
        show_preview = self.preview_item is None
        self.preview_placeholder.setVisible(show_preview)
        if show_preview:
            self.preview_placeholder.raise_()

    def connect_line(self, control, property_name: str, preview: bool = False):
        if not control:
            return

        def on_finished():
            self.set_current_property(property_name, control.text().strip())
            if preview:
                self.load_preview_from_current()

        control.editingFinished.connect(on_finished)

    def connect_number(self, control, property_name: str):
        if not control:
            return
        control.valueChanged.connect(lambda value: self.set_current_property(property_name, self.format_number(value)))

    def connect_pair(self, first, second, property_name: str):
        if not first or not second:
            return

        def on_changed():
            values = [self.format_number(first.value()), self.format_number(second.value())]
            if all(value in {"", "0", "0.0"} for value in values):
                self.set_current_property(property_name, "")
            else:
                self.set_current_property(property_name, "{ " + " ".join(values) + " }")

        first.valueChanged.connect(lambda _: on_changed())
        second.valueChanged.connect(lambda _: on_changed())

    def connect_check(self, control, property_name: str):
        if not control:
            return

        def on_toggled(checked):
            settings = self.get_plugin_settings()
            value = "yes" if checked else ("no" if settings.get("explicit_no_export", False) else "")
            self.set_current_property(property_name, value)

        control.toggled.connect(on_toggled)

    def format_number(self, value) -> str:
        try:
            if float(value).is_integer():
                return str(int(value))
        except Exception:
            pass
        return str(value)

    def refresh(self):
        previous_name = self.current_definition_name()
        self.updating = True
        try:
            doc = self.parser.parse_document(self.file_path, self.widget.content)
            self.definitions = [self.definition_to_model(definition) for definition in doc.definitions]
            self.refresh_definition_list()
            self.restore_selection(previous_name)
            self.update_definition_state()
        finally:
            self.updating = False

    def definition_to_model(self, definition: ParsedGfxDefinition) -> dict:
        properties = {}
        order = []
        if isinstance(definition.node, AssignmentNode) and isinstance(definition.node.value, ObjectNode):
            for item in definition.node.value.items:
                if isinstance(item, AssignmentNode):
                    properties[item.key] = self.node_value_text(item.value)
                    order.append(item.key)

        if "name" not in properties:
            properties["name"] = definition.id
            order.insert(0, "name")

        return {
            "name": definition.id,
            "type": definition.gfx_type,
            "group": definition.group,
            "properties": properties,
            "order": order,
        }

    def node_value_text(self, node) -> str:
        if isinstance(node, ScalarNode):
            return node.raw
        if isinstance(node, ObjectNode):
            return self.serialize_ast_value(node, 1)
        return ""

    def serialize_ast_value(self, node, indent_level: int) -> str:
        if isinstance(node, AssignmentNode):
            return f"{node.key} = {self.serialize_ast_value(node.value, indent_level)}"
        if isinstance(node, ScalarNode):
            return node.raw
        if isinstance(node, ObjectNode):
            if all(isinstance(item, ScalarNode) for item in node.items):
                return "{ " + " ".join(item.raw for item in node.items) + " }"
            tabs = "\t" * (indent_level + 1)
            close_tabs = "\t" * indent_level
            lines = []
            for item in node.items:
                formatted = self.serialize_ast_value(item, indent_level + 1)
                if formatted:
                    lines.append(f"{tabs}{formatted}")
            return "{\n" + "\n".join(lines) + f"\n{close_tabs}}}"
        return ""

    def refresh_definition_list(self, select_index: Optional[int] = None):
        if not self.list_gfx_nodes:
            return
        was_blocked = self.list_gfx_nodes.blockSignals(True)
        self.list_gfx_nodes.clear()
        for index, definition in enumerate(self.definitions):
            item = QListWidgetItem(definition.get("name", ""))
            item.setToolTip(definition.get("type", ""))
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.list_gfx_nodes.addItem(item)
            if select_index is not None and index == select_index:
                self.list_gfx_nodes.setCurrentItem(item)
        self.list_gfx_nodes.blockSignals(was_blocked)

    def restore_selection(self, name: str):
        if not self.definitions:
            self.selected_index = None
            self.load_definition(None)
            return
        index = 0
        if name:
            for i, definition in enumerate(self.definitions):
                if definition.get("name") == name:
                    index = i
                    break
        self.selected_index = index
        if self.list_gfx_nodes:
            item = self.list_gfx_nodes.item(index)
            if item:
                self.list_gfx_nodes.setCurrentItem(item)
        self.load_definition(index)

    def on_definition_selected(self, current, previous=None):
        if self.updating:
            return
        index = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.selected_index = index if isinstance(index, int) else None
        self.load_definition(self.selected_index)
        self.update_definition_state()

    def load_definition(self, index: Optional[int]):
        self.updating = True
        try:
            definition = self.definitions[index] if index is not None and index < len(self.definitions) else None
            props = definition.get("properties", {}) if definition else {}

            set_combo(self.combo_gfx_type, definition.get("type", "spriteType") if definition else "spriteType")
            set_line(self.edit_name, props.get("name", ""))
            set_line(self.edit_texture, self.unquote(props.get("texturefile", "")))
            set_line(self.edit_effect, self.unquote(props.get("effectFile", "")))
            set_line(self.edit_texture1, self.unquote(props.get("textureFile1", "")))
            set_line(self.edit_texture2, self.unquote(props.get("textureFile2", "")))
            set_line(self.edit_mask, self.unquote(props.get("maskFile", "")))
            set_line(self.edit_color, props.get("color", ""))
            set_line(self.edit_color_two, props.get("colortwo", ""))
            self.set_pair_controls(self.spin_size_w, self.spin_size_h, props.get("size", ""))
            self.set_pair_controls(self.spin_border_x, self.spin_border_y, props.get("borderSize", ""))
            set_spin(self.spin_frames, self.number_from_text(props.get("noOfFrames", "1"), 1))
            self.set_double(self.spin_rate, props.get("animation_rate_fps", "0"))
            self.set_double(self.spin_pause_on_loop, props.get("pause_on_loop", "0"))
            set_checked(self.check_horizontal, self.bool_from_text(props.get("horizontal", "")))
            set_checked(self.check_transparent, self.bool_from_text(props.get("allwaystransparent", "")))
            set_checked(self.check_lazy_load, self.bool_from_text(props.get("legacy_lazy_load", "")))
            set_checked(self.check_transparence, self.bool_from_text(props.get("transparencecheck", "")))
            set_checked(self.check_looping, self.bool_from_text(props.get("looping", "")))
            set_checked(self.check_play_on_show, self.bool_from_text(props.get("play_on_show", "")))
            set_line(self.edit_source_path, self.first_texture_value(props))
        finally:
            self.updating = False

        self.set_definition_selected(definition is not None)
        self.load_preview_from_current()

    def set_double(self, control, value):
        if not control:
            return
        was_blocked = control.blockSignals(True)
        try:
            control.setValue(float(value or 0))
        except Exception:
            control.setValue(0)
        control.blockSignals(was_blocked)

    def set_pair_controls(self, first, second, value):
        values = self.object_numbers(value)
        for control, number in ((first, values[0] if len(values) > 0 else 0), (second, values[1] if len(values) > 1 else 0)):
            if not control:
                continue
            was_blocked = control.blockSignals(True)
            control.setValue(number)
            control.blockSignals(was_blocked)

    def set_definition_selected(self, selected: bool):
        if self.widget_center_pane:
            self.widget_center_pane.setCurrentIndex(0 if selected else 1)
        self.update_preview_placeholder_visibility()

    def update_definition_state(self):
        has_selection = self.selected_index is not None
        if self.btn_duplicate_node:
            self.btn_duplicate_node.setEnabled(has_selection)
        if self.btn_delete_node:
            self.btn_delete_node.setEnabled(has_selection)

    def create_definition_from_image(self):
        path = self.select_image_file("Select texture image for new definition")
        if not path:
            return
        self.create_definition(source_path=path)

    def create_definition(self, definition_type=None, name=None, source_path=""):
        if definition_type is None and self.combo_gfx_type:
            definition_type = self.combo_gfx_type.currentText() or "spriteType"
        if not name:
            name = self.generate_graphic_definition_name(source_path)

        texture_value = self.texture_value_for_path(source_path)
        definition = {
            "name": name,
            "type": definition_type or "spriteType",
            "group": "spriteTypes",
            "properties": {
                "name": name,
                "texturefile": texture_value,
            },
            "order": ["name", "texturefile"],
        }
        self.definitions.append(definition)
        self.selected_index = len(self.definitions) - 1
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.load_definition(self.selected_index)
        self.widget.is_dirty = True

    def generate_graphic_definition_name(self, source_path: str = "") -> str:
        file_stem = os.path.splitext(os.path.basename(source_path))[0] if source_path else ""
        extra = {"file": file_stem} if file_stem else {}
        return self.generate_unique_formatted_name(
            "graphic_definition_name_format",
            "{file}{number}",
            (definition.get("name", "") for definition in self.definitions),
            fallback="new_gfx",
            **extra,
        )

    def duplicate_selected_definition(self):
        definition = self.current_definition()
        if not definition:
            return
        source_name = definition.get("name", "new_gfx")
        copy = {
            "name": self.unique_copy_name(source_name),
            "type": definition.get("type", "spriteType"),
            "group": definition.get("group", "spriteTypes"),
            "properties": dict(definition.get("properties", {})),
            "order": list(definition.get("order", [])),
        }
        copy["properties"]["name"] = copy["name"]
        self.definitions.append(copy)
        self.selected_index = len(self.definitions) - 1
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.load_definition(self.selected_index)
        self.widget.is_dirty = True

    def unique_copy_name(self, base: str) -> str:
        existing = {definition.get("name", "") for definition in self.definitions}
        counter = 1
        while True:
            candidate = f"{base}_copy{counter}"
            if candidate not in existing:
                return candidate
            counter += 1

    def delete_selected_definition(self):
        if self.selected_index is None:
            return
        del self.definitions[self.selected_index]
        self.selected_index = min(self.selected_index, len(self.definitions) - 1) if self.definitions else None
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.load_definition(self.selected_index)
        self.widget.is_dirty = True

    def browse_source(self):
        path = self.select_image_file("Select texture image")
        if not path:
            return
        texture_value = self.texture_value_for_path(path)
        if self.edit_source_path:
            set_line(self.edit_source_path, texture_value)
        if self.edit_texture:
            set_line(self.edit_texture, texture_value)
        self.set_current_property("texturefile", texture_value)
        self.load_preview(path)

    def select_image_file(self, title: str) -> str:
        start_dir = ""
        if self.edit_source_path:
            current_value = self.edit_source_path.text().strip()
            if current_value:
                start_dir = os.path.dirname(current_value) or current_value
        path, _ = QFileDialog.getOpenFileName(
            self.widget,
            title,
            start_dir or os.path.dirname(self.file_path or "") or "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.dds);;All Files (*.*)",
        )
        return path or ""

    def set_current_property(self, property_name: str, value: str):
        if self.updating:
            return
        definition = self.current_definition()
        if not definition:
            return
        props = definition.setdefault("properties", {})
        order = definition.setdefault("order", [])
        actual_key = self.actual_property_key(props, property_name)

        if not value:
            props.pop(actual_key, None)
            if actual_key in order:
                order.remove(actual_key)
        else:
            props[actual_key] = value
            if actual_key not in order:
                order.append(actual_key)

        if property_name == "name":
            definition["name"] = value
            props["name"] = value
        if self.combo_gfx_type:
            definition["type"] = self.combo_gfx_type.currentText() or definition.get("type", "spriteType")

        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.widget.is_dirty = True

    def on_type_changed(self):
        if self.updating:
            return
        definition = self.current_definition()
        if not definition or not self.combo_gfx_type:
            return
        definition["type"] = self.combo_gfx_type.currentText() or "spriteType"
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.widget.is_dirty = True

    def actual_property_key(self, props: dict, property_name: str) -> str:
        for key in props.keys():
            if key.lower() == property_name.lower():
                return key
        return property_name

    def serialize_document(self):
        groups: dict[str, list[dict]] = {}
        for definition in self.definitions:
            groups.setdefault(definition.get("group", "spriteTypes"), []).append(definition)

        sections = []
        for group, definitions in groups.items():
            lines = [f"{group} = {{"]
            for definition in definitions:
                lines.append(self.serialize_definition(definition))
            lines.append("}")
            sections.append("\n".join(lines))
        self.widget.content = "\n\n".join(sections) + ("\n" if sections else "")

    def serialize_definition(self, definition: dict) -> str:
        definition_type = definition.get("type", "spriteType")
        props = dict(definition.get("properties", {}))
        props["name"] = definition.get("name", props.get("name", ""))
        order = self.definition_key_order(definition_type, definition.get("order", []), props)

        lines = [f"\t{definition_type} = {{"]
        for key in order:
            value = props.get(key, "")
            if value == "":
                continue
            lines.append(f"\t\t{key} = {self.format_property_value(key, value)}")
        lines.append("\t}")
        return "\n".join(lines)

    def definition_key_order(self, definition_type: str, existing_order: list[str], props: dict) -> list[str]:
        config = self.format_config.get(definition_type, {})
        configured = [key for key in config.get("key_order", []) if key]
        order = []
        for key in configured + existing_order + list(props.keys()):
            actual = self.actual_property_key(props, key)
            if actual in props and actual not in order:
                order.append(actual)
        if "name" in order:
            order.remove("name")
        return ["name"] + order

    def format_property_value(self, key: str, value: str) -> str:
        text = str(value).strip()
        if not text:
            return ""
        if text.startswith("{") or text.startswith('"') or text in {"yes", "no", "true", "false"}:
            return text
        if key in NUMERIC_PROPERTIES:
            return text
        if key in BOOL_PROPERTIES:
            return text.lower()
        if key in STRING_PROPERTIES:
            return f'"{self.unquote(text)}"'
        return text

    def on_save_triggered(self):
        self.serialize_document()
        if not self.save_content_to_file(save_as=False):
            return False
        self.widget.is_dirty = False
        return True

    def on_save_as_triggered(self):
        self.serialize_document()
        if not self.save_content_to_file(save_as=True):
            return False
        self.widget.is_dirty = False
        return True

    def save_content_to_file(self, save_as: bool = False) -> bool:
        file_path = self.file_path or getattr(self.widget, "file_path", "")
        if save_as or not file_path or str(file_path).startswith("untitled:"):
            file_path, _ = QFileDialog.getSaveFileName(
                self.widget,
                "Save GFX File",
                os.path.dirname(file_path) if file_path and not str(file_path).startswith("untitled:") else "",
                "GFX Files (*.gfx);;All Files (*.*)",
            )
            if not file_path:
                return False

        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(self.widget.content)
        except Exception as error:
            print(f"Failed to save GFX file: {error}")
            return False

        self.file_path = file_path
        self.widget.file_path = file_path
        return True

    def current_definition(self) -> Optional[dict]:
        if self.selected_index is None or self.selected_index < 0 or self.selected_index >= len(self.definitions):
            return None
        return self.definitions[self.selected_index]

    def current_definition_name(self) -> str:
        definition = self.current_definition()
        return definition.get("name", "") if definition else ""

    def first_texture_value(self, props: dict) -> str:
        for key in ("texturefile", "textureFile1", "textureFile2"):
            actual = self.actual_property_key(props, key)
            value = props.get(actual, "")
            if value:
                return self.unquote(value)
        return ""

    def load_preview_from_current(self):
        definition = self.current_definition()
        if not definition:
            self.clear_preview()
            return
        texture = self.first_texture_value(definition.get("properties", {}))
        self.load_preview(self.resolve_texture_path(texture))

    def load_preview(self, path: str):
        if not path:
            self.clear_preview()
            return False

        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.clear_preview()
            return False

        if self.preview_scene:
            self.preview_scene.clear()
            self.preview_item = QGraphicsPixmapItem(pixmap)
            self.preview_scene.addItem(self.preview_item)
            self.preview_scene.setSceneRect(self.preview_item.boundingRect())
            self.fit_preview_to_view()
        self.update_preview_placeholder_visibility()
        return True

    def clear_preview(self):
        if self.preview_scene:
            self.preview_scene.clear()
        self.preview_item = None
        self.update_preview_placeholder_visibility()

    def resolve_texture_path(self, texture: str) -> str:
        texture = self.unquote(texture)
        if not texture:
            return ""
        if os.path.isabs(texture):
            return texture
        mod_root = self.get_mod_root()
        project_path = os.path.normpath(os.path.join(mod_root, texture))
        if os.path.exists(project_path):
            return project_path
        settings = self.get_plugin_settings()
        game_path = settings.get("game_path", "")
        if game_path:
            game_texture = os.path.normpath(os.path.join(game_path, texture))
            if os.path.exists(game_texture):
                return game_texture
        return project_path

    def texture_value_for_path(self, path: str) -> str:
        if not path:
            return ""
        mod_root = self.get_mod_root()
        try:
            rel = os.path.relpath(path, mod_root)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except Exception:
            pass
        return path.replace("\\", "/")

    def unquote(self, value: str) -> str:
        text = str(value or "").strip()
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            return text[1:-1]
        return text

    def bool_from_text(self, value: str) -> bool:
        return str(value).strip().lower() in {"yes", "true"}

    def number_from_text(self, value: str, default=0):
        try:
            return int(float(str(value).strip()))
        except Exception:
            return default

    def object_numbers(self, value: str) -> list[float]:
        text = str(value or "").replace("{", " ").replace("}", " ")
        result = []
        for part in text.split():
            try:
                number = float(part)
                result.append(int(number) if number.is_integer() else number)
            except Exception:
                continue
        return result
