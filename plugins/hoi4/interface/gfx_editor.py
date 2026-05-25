from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

import core.api
from core.utils import load_svg_icon
from core import save_result
from core import syntax_assets
from PySide6.QtCore import QFile, QEvent, QObject, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QMenu,
    QToolButton,
    QWidget,
)
from lib.save_ui import MultipleSaveTargetsDialog

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
from plugins.hoi4.interface.gfx_ui_bindings import (
    GFX_SCHEMA_FIELD_BINDINGS,
    GFX_SCHEMA_FIELD_VISIBILITY_BINDINGS,
    populate_type_combo,
    missing_required_tooltip,
    schema_required_fields,
    schema_fields_with_usage,
    schema_sub_fields_with_usage,
    schema_type_definition,
)
from plugins.hoi4.interface.ui_image_helpers import load_pil_image
from core.syntax_engine import AssignmentNode, ObjectNode, ParsedEntity, ScalarNode


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

DDS_TEXTURE_PROPERTIES = (
    "texturefile",
    "textureFile1",
    "textureFile2",
    "maskFile",
)

ANIMATED_PREVIEW_EXTENSIONS = {".gif", ".webp", ".apng"}


GFX_SCHEMA_GROUP_VISIBILITY_BINDINGS = {
    "groupBasic": ("name", "texturefile", "texturefile1", "texturefile2", "effectfile", "maskfile"),
    "groupAppearance": (
        "size",
        "bordersize",
        "color",
        "colortwo",
        "horizontal",
        "allwaystransparent",
        "legacy_lazy_load",
        "transparencecheck",
    ),
    "groupFrames": ("noofframes", "animation_rate_fps", "looping", "play_on_show", "pause_on_loop"),
    "groupFont": (),
    "groupMapText": (),
    "groupAnim": (
        "animationmaskfile",
        "animationtexturefile",
        "animationrotation",
        "animationlooping",
        "animationtime",
        "animationdelay",
        "animationblendmode",
        "animationrotationoffset",
        "animationtexturescale",
        "animationtype",
    ),
}


class ParsedGfxDefinition(BaseParsedEntity):
    def __init__(self, entity: ParsedEntity):
        super().__init__(entity)
        self.definition_type = entity.node.key if isinstance(entity.node, AssignmentNode) else "spriteType"
        self.root_group = entity.parent_id or "spriteTypes"


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

    def __init__(self, plugin=None):
        element = syntax_assets.plugin_element(plugin, "interface")
        schema_data = syntax_assets.load_element_schema(element)
        super().__init__(schema_data)


def setup(widget, file_path, content):
    controller = GfxEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    widget.on_save_triggered = controller.on_save_triggered
    widget.on_save_as_triggered = controller.on_save_as_triggered
    widget.on_write_save_plan = controller.on_write_save_plan
    widget.set_params = controller.set_params
    widget.setParams = controller.set_params
    controller.bind()
    core.api.notify_editor_ready(getattr(widget, "tab_id", None))


class GfxEditorController(BaseEditorController):
    ELEMENT_ID = "interface"
    DEFAULT_FORMAT_FILE = "gfx_format.json"

    def __init__(self, widget, file_path, content):
        super().__init__(widget, file_path, content)
        self.parser = GfxParser(self.get_hoi4_plugin())
        self.definitions: list[dict] = []
        self.selected_index: Optional[int] = None
        self.preview_scene = None
        self.preview_item = None
        self.preview_placeholder = None
        self.fit_preview_to_view = lambda: None
        self.name_frame = None
        self.inline_action_frame_by_edit = {}
        self.source_paths = {}
        self.schema_visibility_actions = {}
        self.schema_visibility_menus = []
        self.schema_visible_optional_fields = {}
        self.pending_new_definition_filter_settings = None
        self.pending_new_definition_filter_source_path = ""

    def bind(self):
        self.widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.widget.setVisible(True)
        self.widget.gfx_ui = self.widget

        title = os.path.basename(self.file_path) if self.file_path else "GFX Editor"
        self.widget.setWindowTitle(title)

        self.list_gfx_nodes = find(self.widget, QListWidget, "listGfxNodes")
        self.combo_gfx_type = find(self.widget, QComboBox, "comboGfxType")
        self.edit_source_path = find(self.widget, QLineEdit, "editSourcePath")
        self.edit_source_path1 = find(self.widget, QLineEdit, "editSourcePath1")
        self.edit_source_path2 = find(self.widget, QLineEdit, "editSourcePath2")
        self.btn_browse_source = find(self.widget, QPushButton, "btnBrowseSource")
        self.btn_browse_source1 = find(self.widget, QPushButton, "btnBrowseSource1")
        self.btn_browse_source2 = find(self.widget, QPushButton, "btnBrowseSource2")
        self.btn_browse_texture = find(self.widget, QPushButton, "btnBrowseTexture")
        self.btn_browse_texture1 = find(self.widget, QPushButton, "btnBrowseTexture1")
        self.btn_browse_texture2 = find(self.widget, QPushButton, "btnBrowseTexture2")
        self.btn_duplicate_node = find(self.widget, QPushButton, "btnDuplicateNode")
        self.btn_delete_node = find(self.widget, QPushButton, "btnDeleteNode")
        self.btn_add = find(self.widget, QPushButton, "btnAdd")
        self.btn_more_items = find(self.widget, QPushButton, "btnMoreItems")
        self.btn_more_anim_items = find(self.widget, QPushButton, "btnMoreAnimItems")
        self.btn_open_image_tools = find(self.widget, QPushButton, "btnOpenImageTools")
        self.group_preview_control = find(self.widget, QWidget, "groupPreviewControl")
        self.graphics_texture_view = find(self.widget, QGraphicsView, "graphicsTextureView")
        self.name_inline_host = find(self.widget, QWidget, "widgetNameHost")
        self.texture_inline_host = find(self.widget, QWidget, "widgetTextureHost")
        self.texture1_inline_host = find(self.widget, QWidget, "widgetTexture1Host")
        self.texture2_inline_host = find(self.widget, QWidget, "widgetTexture2Host")

        self.name_frame, self.edit_name, self.btn_auto_naming = self.load_inline_action_field(
            self.name_inline_host,
            icon_name="rotate-cw.svg",
            tooltip="名前を自動設定フォーマットに合わせて再設定します。",
            on_clicked=self.apply_auto_naming,
            icon_source="plugin",
        )
        self.texture_frame, self.edit_texture, self.btn_select_texture = self.load_inline_action_field(
            self.texture_inline_host,
            icon_name="rotate-cw.svg",
            tooltip="texturefile を自動設定フォーマットに合わせて再設定します。",
            on_clicked=lambda: self.apply_auto_texture_naming(self.edit_source_path, self.edit_texture, "texturefile"),
        )
        self.texture1_frame, self.edit_texture1, self.btn_select_texture1 = self.load_inline_action_field(
            self.texture1_inline_host,
            icon_name="rotate-cw.svg",
            tooltip="textureFile1 を自動設定フォーマットに合わせて再設定します。",
            on_clicked=lambda: self.apply_auto_texture_naming(self.edit_source_path1, self.edit_texture1, "textureFile1"),
        )
        self.texture2_frame, self.edit_texture2, self.btn_select_texture2 = self.load_inline_action_field(
            self.texture2_inline_host,
            icon_name="rotate-cw.svg",
            tooltip="textureFile2 を自動設定フォーマットに合わせて再設定します。",
            on_clicked=lambda: self.apply_auto_texture_naming(self.edit_source_path2, self.edit_texture2, "textureFile2"),
        )

        self.edit_effect = find(self.widget, QLineEdit, "editEffect")
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

        self.setup_schema_visibility_menus()
        self.populate_gfx_type_combo()

        if self.list_gfx_nodes:
            self.list_gfx_nodes.currentItemChanged.connect(self.on_definition_selected)

        if self.btn_duplicate_node:
            self.btn_duplicate_node.clicked.connect(self.duplicate_selected_definition)
            self.btn_duplicate_node.setEnabled(False)
        if self.btn_delete_node:
            self.btn_delete_node.clicked.connect(self.delete_selected_definition)
            self.btn_delete_node.setEnabled(False)
        if self.btn_browse_source:
            self.btn_browse_source.clicked.connect(self.browse_source)
        if self.btn_browse_source1:
            self.btn_browse_source1.clicked.connect(lambda: self.browse_texture_source(
                self.edit_source_path1,
                self.edit_texture1,
                "textureFile1",
                "Select texture image 1",
            ))
        if self.btn_browse_source2:
            self.btn_browse_source2.clicked.connect(lambda: self.browse_texture_source(
                self.edit_source_path2,
                self.edit_texture2,
                "textureFile2",
                "Select texture image 2",
            ))
        if self.btn_browse_texture:
            self.btn_browse_texture.clicked.connect(lambda: self.browse_texture_destination(
                self.edit_texture,
                "texturefile",
                "Select texture save destination",
                self.edit_source_path,
            ))
        if self.btn_browse_texture1:
            self.btn_browse_texture1.clicked.connect(lambda: self.browse_texture_destination(
                self.edit_texture1,
                "textureFile1",
                "Select texture save destination 1",
                self.edit_source_path1,
            ))
        if self.btn_browse_texture2:
            self.btn_browse_texture2.clicked.connect(lambda: self.browse_texture_destination(
                self.edit_texture2,
                "textureFile2",
                "Select texture save destination 2",
                self.edit_source_path2,
            ))
        if self.btn_add:
            self.btn_add.clicked.connect(self.add_definition_from_current)
        if self.btn_open_image_tools:
            self.btn_open_image_tools.clicked.connect(self.open_image_tools_dialog)
        if self.combo_gfx_type:
            self.combo_gfx_type.currentIndexChanged.connect(self.on_type_changed)

        self.connect_line(self.edit_name, "name")
        self.connect_source_line(self.edit_source_path, "texturefile", self.edit_texture, preview=True)
        self.connect_line(self.edit_texture, "texturefile", preview=True)
        self.connect_line(self.edit_effect, "effectFile")
        self.connect_source_line(self.edit_source_path1, "textureFile1", self.edit_texture1, preview=True)
        self.connect_source_line(self.edit_source_path2, "textureFile2", self.edit_texture2)
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
        self.connect_add_button_refresh()

        self.setup_preview_view()
        self.update_preview_controls_visibility("")
        self.refresh()

    def on_save_triggered(self) -> dict:
        return self.build_save_plan(save_as=False)

    def on_save_as_triggered(self) -> dict:
        return self.build_save_plan(save_as=True)

    def on_write_save_plan(self) -> dict:
        return self.write_save_plan()

    def build_save_plan(self, save_as: bool = False) -> dict:
        self.widget.save_plan = None
        primary_path = self.default_primary_save_path()
        requires_dialog = save_as or not self.file_path or str(self.file_path).startswith("untitled:")
        targets = self.collect_save_targets(primary_path)

        if requires_dialog:
            targets = self.open_save_targets_dialog(targets)
            if not targets:
                return save_result.save_cancelled()

        self.widget.save_plan = {
            "tab_kind": "gfx",
            "dialog": "custom" if requires_dialog else None,
            "save_as": bool(requires_dialog),
            "targets": targets,
        }
        return save_result.save_success()

    def default_primary_save_path(self) -> str:
        if self.file_path and not str(self.file_path).startswith("untitled:"):
            return self.file_path
        return os.path.join(self.get_mod_root(), "interface", f"{self.default_gfx_file_name()}.gfx")

    def open_save_targets_dialog(self, targets: list[dict]) -> list[dict]:
        dialog = MultipleSaveTargetsDialog(
            parent=self.widget,
            title="GFX 保存先",
            description="保存対象ごとの保存先を確認してください。",
            targets=targets,
            format_options=["gfx", "dds"],
        )
        if not dialog.exec():
            return []
        return dialog.result_targets()

    def collect_save_targets(self, primary_path: str) -> list[dict]:
        targets = [
            {
                "enabled": True,
                "kind": "gfx_definition",
                "role": "GFX定義ファイル",
                "path": primary_path,
                "format": "gfx",
            }
        ]

        seen_paths = {os.path.normcase(primary_path)}
        for definition_index, definition in enumerate(self.definitions):
            props = definition.get("properties", {})
            source_paths = definition.get("_source_paths", {})
            definition_name = definition.get("name", "")
            for property_name in DDS_TEXTURE_PROPERTIES:
                actual_key = self.actual_property_key(props, property_name)
                value = self.unquote(props.get(actual_key, ""))
                source_path = source_paths.get(actual_key, "")
                if not source_path and value:
                    source_path = self.resolve_texture_path(value)

                output_path = self.dds_output_path_for_texture(value, source_path)
                if not output_path:
                    continue

                normalized = os.path.normcase(output_path)
                if normalized in seen_paths:
                    continue
                seen_paths.add(normalized)

                targets.append(
                    {
                        "enabled": True,
                        "kind": "dds_texture",
                        "role": self.texture_target_label(definition_name, actual_key),
                        "property": actual_key,
                        "definition_name": definition_name,
                        "path": output_path,
                        "source_path": source_path,
                        "format": "dds",
                        "metadata": {
                            "definition_index": definition_index,
                            "property": actual_key,
                            "definition_name": definition_name,
                            "source_path": source_path,
                        },
                    }
                )

        return targets

    def write_save_plan(self) -> dict:
        plan = getattr(self.widget, "save_plan", None) or {}
        targets = self.normalize_save_targets(plan.get("targets", []))
        gfx_target = next((target for target in targets if target.get("kind") == "gfx_definition"), None)
        gfx_path = self.target_output_path(gfx_target) if gfx_target else ""
        if not gfx_path:
            missing_role = self.target_role_label(gfx_target, fallback="GFX定義ファイル")
            QMessageBox.warning(self.widget, "保存できません", f"{missing_role} の保存先が未設定です。")
            return save_result.save_failed()

        saved_definitions = self.build_saved_definitions(targets)
        saved_content = self.serialize_definitions(saved_definitions)

        try:
            parent = os.path.dirname(gfx_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(gfx_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(saved_content)
        except Exception as error:
            QMessageBox.warning(self.widget, "保存できません", str(error))
            return save_result.save_failed(message=str(error))

        failures = []
        for target in targets:
            if target.get("kind") != "dds_texture" or not target.get("enabled", True):
                continue

            source_path = target.get("source_path") or target.get("metadata", {}).get("source_path", "")
            output_path = self.target_output_path(target)
            
            metadata = target.get("metadata", {}) or {}
            definition_index = metadata.get("definition_index")
            filter_settings = None
            if definition_index is not None and 0 <= definition_index < len(self.definitions):
                filter_settings = self.definitions[definition_index].get("_filter_settings")

            if not source_path or not os.path.exists(source_path):
                failures.append(f"{target.get('role', '')}: {output_path}")
                continue
            if not output_path or not self.save_dds_texture(source_path, output_path, filter_settings):
                failures.append(f"{target.get('role', '')}: {output_path}")

        if failures:
            QMessageBox.warning(
                self.widget,
                "DDS書き出し失敗",
                "画像のDDS書き出しに失敗しました。\n\n" + "\n".join(failures),
            )
            return save_result.save_failed(message="\n".join(failures))

        self.definitions = saved_definitions
        self.widget.content = saved_content
        self.file_path = gfx_path
        self.widget.file_path = gfx_path
        if self.selected_index is not None:
            self.refresh_definition_list(self.selected_index)
            self.load_definition(self.selected_index)
        core.api.emit_event("file_saved", gfx_path)
        for target in targets:
            if target.get("kind") == "dds_texture" and target.get("enabled", True):
                core.api.emit_event("file_saved", self.target_output_path(target))
        return save_result.save_success(primary_path=gfx_path)

    def normalize_save_targets(self, targets) -> list[dict]:
        normalized_targets = []
        for target in list(targets or []):
            item = dict(target or {})
            item["path"] = self.target_output_path(item)
            normalized_targets.append(item)
        return normalized_targets

    def target_output_path(self, target: dict | None) -> str:
        if not target:
            return ""
        path = str(target.get("path", "") or "").strip()
        if path:
            return os.path.normpath(path)

        directory = str(target.get("directory", "") or "").strip()
        file_name = str(target.get("file_name", "") or "").strip()
        if not directory and not file_name:
            return ""
        return os.path.normpath(os.path.join(directory, file_name))

    def target_role_label(self, target: dict | None, fallback: str = "保存対象") -> str:
        if not target:
            return fallback
        role = str(target.get("role", "") or "").strip()
        return role or fallback

    def build_saved_definitions(self, targets: list[dict]) -> list[dict]:
        saved_definitions = deepcopy(self.definitions)
        self.apply_target_paths_to_definitions(saved_definitions, targets)
        return saved_definitions

    def apply_target_paths_to_definitions(self, definitions: list[dict], targets: list[dict]) -> None:
        for target in targets:
            if target.get("kind") != "dds_texture":
                continue

            metadata = target.get("metadata", {}) or {}
            definition_index = metadata.get("definition_index")
            property_name = metadata.get("property") or target.get("property")
            output_path = self.target_output_path(target)
            if definition_index is None or property_name is None or not output_path:
                continue
            if definition_index < 0 or definition_index >= len(definitions):
                continue

            definition = definitions[definition_index]
            props = definition.get("properties", {})
            actual_key = self.actual_property_key(props, property_name)
            props[actual_key] = self.texture_value_for_path(output_path)

    def texture_target_label(self, definition_name: str, property_name: str) -> str:
        display_name = definition_name.strip() or "名称未設定"
        return f"DDSテクスチャ ({display_name} / {property_name})"

    def populate_gfx_type_combo(self):
        if not self.combo_gfx_type:
            return

        schema = getattr(self.parser, "schema", {}) or {}
        current_type = ""
        current_definition = self.current_definition()
        if current_definition:
            current_type = current_definition.get("type", "")
        elif self.combo_gfx_type.currentText():
            current_type = self.combo_gfx_type.currentText()
        populate_type_combo(self.combo_gfx_type, schema, current_type)
        self.update_schema_visibility()
        self.update_add_button_state()

    def set_named_widget_visible(self, widget_name: str, visible: bool):
        widget = find(self.widget, QWidget, widget_name)
        if widget:
            widget.setVisible(visible)

    def setup_schema_visibility_menus(self):
        self.more_items_menu = QMenu(self.widget) if self.btn_more_items else None
        self.more_anim_items_menu = QMenu(self.widget) if self.btn_more_anim_items else None
        self.schema_visibility_menus = []

        if self.btn_more_items and self.more_items_menu:
            self.btn_more_items.setMenu(self.more_items_menu)
            self.more_items_menu.installEventFilter(self)
            self.schema_visibility_menus.append(self.more_items_menu)
        if self.btn_more_anim_items and self.more_anim_items_menu:
            self.btn_more_anim_items.setMenu(self.more_anim_items_menu)
            self.more_anim_items_menu.installEventFilter(self)
            self.schema_visibility_menus.append(self.more_anim_items_menu)

    def schema_visibility_state_key(self, definition_type: str, parent_field: str = "") -> str:
        key = definition_type.lower()
        if parent_field:
            key += f":{parent_field.lower()}"
        return key

    def schema_field_has_value(self, field_name: str) -> bool:
        definition = self.current_definition()
        props = definition.get("properties", {}) if definition else {}
        normalized = field_name.lower()
        for prop_name, value in props.items():
            if prop_name.lower() == normalized and str(value).strip():
                return True
        return False

    def schema_optional_field_visible(self, definition_type: str, field_name: str, parent_field: str = "") -> bool:
        state_key = self.schema_visibility_state_key(definition_type, parent_field)
        enabled_fields = self.schema_visible_optional_fields.get(state_key, set())
        return field_name.lower() in enabled_fields or self.schema_field_has_value(field_name)

    def set_schema_optional_field_visible(
        self,
        definition_type: str,
        field_name: str,
        parent_field: str,
        visible: bool,
    ):
        state_key = self.schema_visibility_state_key(definition_type, parent_field)
        enabled_fields = self.schema_visible_optional_fields.setdefault(state_key, set())
        normalized = field_name.lower()
        if visible:
            enabled_fields.add(normalized)
        else:
            enabled_fields.discard(normalized)

    def schema_field_translation_key(self, field_name: str) -> str:
        schema = getattr(self.parser, "schema", {}) or {}
        schema_name = schema.get("schema_name", "schema")
        return f"schema.{schema_name}.fields.{field_name}"

    def schema_field_label(self, field_name: str, usage: str) -> str:
        key = self.schema_field_translation_key(field_name)
        plugin = getattr(self.widget, "active_plugin", None)
        translated = core.api.plugin_translate(
            getattr(plugin, "id", None),
            key,
            fallback=field_name,
            context="schema_field",
            metadata={
                "schema_name": (getattr(self.parser, "schema", {}) or {}).get("schema_name", ""),
                "field": field_name,
            },
        )
        if translated and translated != field_name:
            return f"{translated}（{field_name}）"
        return field_name

    def schema_field_has_visibility_binding(self, field_name: str, schema: dict, definition_type: str) -> bool:
        normalized = field_name.lower()
        if normalized in GFX_SCHEMA_FIELD_VISIBILITY_BINDINGS:
            return True
        for sub_field_name, _usage in schema_sub_fields_with_usage(schema, definition_type, field_name):
            if sub_field_name.lower() in GFX_SCHEMA_FIELD_VISIBILITY_BINDINGS:
                return True
        return False

    def rebuild_schema_visibility_menus(self):
        if not self.combo_gfx_type:
            return

        schema = getattr(self.parser, "schema", {}) or {}
        definition_type = self.combo_gfx_type.currentText().strip()
        self.schema_visibility_actions = {}

        if self.more_items_menu:
            self.more_items_menu.clear()
            count = 0
            for field_name, usage in schema_fields_with_usage(schema, definition_type):
                if usage == "required":
                    continue
                if not self.schema_field_has_visibility_binding(field_name, schema, definition_type):
                    continue
                action = self.add_schema_visibility_action(
                    self.more_items_menu,
                    definition_type,
                    field_name,
                    usage,
                    "",
                )
                self.schema_visibility_actions[("", field_name.lower())] = action
                count += 1
            self.btn_more_items.setEnabled(count > 0)

        if self.more_anim_items_menu:
            self.more_anim_items_menu.clear()
            count = 0
            for field_name, usage in schema_sub_fields_with_usage(schema, definition_type, "animation"):
                if usage == "required":
                    continue
                if field_name.lower() not in GFX_SCHEMA_FIELD_VISIBILITY_BINDINGS:
                    continue
                action = self.add_schema_visibility_action(
                    self.more_anim_items_menu,
                    definition_type,
                    field_name,
                    usage,
                    "animation",
                )
                self.schema_visibility_actions[("animation", field_name.lower())] = action
                count += 1
            self.btn_more_anim_items.setEnabled(count > 0)

    def add_schema_visibility_action(self, menu, definition_type: str, field_name: str, usage: str, parent_field: str):
        required = usage == "required"
        checked = required or self.schema_optional_field_visible(definition_type, field_name, parent_field)
        action = QAction(self.schema_field_label(field_name, usage), menu)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setEnabled(not required)
        action.triggered.connect(
            lambda visible, f=field_name, p=parent_field, t=definition_type: self.on_schema_visibility_toggled(t, f, p, visible)
        )
        menu.addAction(action)
        return action

    def on_schema_visibility_toggled(self, definition_type: str, field_name: str, parent_field: str, visible: bool):
        self.set_schema_optional_field_visible(definition_type, field_name, parent_field, visible)
        self.update_schema_visibility(rebuild_menus=False)

    def update_schema_visibility(self, rebuild_menus: bool = True):
        if not self.combo_gfx_type:
            return

        schema = getattr(self.parser, "schema", {}) or {}
        definition_type = self.combo_gfx_type.currentText().strip()
        if rebuild_menus:
            self.rebuild_schema_visibility_menus()

        visible_fields = set()
        root_fields = schema_fields_with_usage(schema, definition_type)
        root_visible_fields = set()
        for field_name, usage in root_fields:
            normalized = field_name.lower()
            if usage == "required" or self.schema_optional_field_visible(definition_type, field_name):
                root_visible_fields.add(normalized)
                visible_fields.add(normalized)

        if "animation" in root_visible_fields:
            for field_name, usage in schema_sub_fields_with_usage(schema, definition_type, "animation"):
                if usage == "required" or self.schema_optional_field_visible(definition_type, field_name, "animation"):
                    visible_fields.add(field_name.lower())

        for field_name, widget_names in GFX_SCHEMA_FIELD_VISIBILITY_BINDINGS.items():
            is_visible = field_name.lower() in visible_fields
            for widget_name in widget_names:
                self.set_named_widget_visible(widget_name, is_visible)

        for group_name, group_fields in GFX_SCHEMA_GROUP_VISIBILITY_BINDINGS.items():
            is_visible = any(field_name.lower() in visible_fields for field_name in group_fields)
            self.set_named_widget_visible(group_name, is_visible)

    def schema_field_binding(self, property_name: str) -> Optional[dict]:
        return GFX_SCHEMA_FIELD_BINDINGS.get(property_name.lower())

    def schema_field_control(self, property_name: str):
        binding = self.schema_field_binding(property_name)
        if not binding:
            return None
        controls = []
        for attr_name in binding.get("controls", ()):
            control = getattr(self, attr_name, None)
            if control is not None:
                controls.append(control)
        if not controls:
            return None
        if len(controls) == 1:
            return controls[0]
        return tuple(controls)

    def schema_field_value(self, property_name: str) -> str:
        binding = self.schema_field_binding(property_name)
        control = self.schema_field_control(property_name)
        if not binding:
            return ""

        if not control:
            if property_name.lower() in {"texturefile", "texturefile1", "texturefile2"}:
                source_edit = self.source_edit_for_property(property_name)
                if source_edit:
                    source_path = source_edit.text().strip()
                    if source_path:
                        return self.default_dds_texture_value_for_source(source_path)
            return ""

        kind = binding.get("kind", "")
        if kind == "pair" and isinstance(control, tuple):
            values = [self.format_number(item.value()) for item in control]
            if all(value in {"", "0", "0.0"} for value in values):
                return ""
            return "{ " + " ".join(values) + " }"

        if isinstance(control, QLineEdit):
            return control.text().strip()
        if isinstance(control, (QSpinBox, QDoubleSpinBox)):
            value = self.format_number(control.value())
            return "" if value in {"", "0", "0.0"} and kind == "spin" else value
        if isinstance(control, QCheckBox):
            if control.isChecked():
                return "yes"
            settings = self.get_plugin_settings()
            return "no" if settings.get("explicit_no_export", False) else ""
        if isinstance(control, QComboBox):
            return control.currentText().strip()
        return ""

    def source_edit_for_property(self, property_name: str):
        mapping = {
            "texturefile": self.edit_source_path,
            "texturefile1": self.edit_source_path1,
            "texturefile2": self.edit_source_path2,
        }
        return mapping.get((property_name or "").lower())

    def update_add_button_state(self):
        if not self.btn_add or not self.combo_gfx_type:
            return

        has_selection = self.current_definition() is not None
        self.btn_add.setText("選択定義を更新" if has_selection else "定義を追加")

        definition_type = self.combo_gfx_type.currentText().strip()
        schema = getattr(self.parser, "schema", {}) or {}
        if not definition_type or not schema_type_definition(schema, definition_type):
            self.btn_add.setEnabled(False)
            self.btn_add.setToolTip("有効な型を選択してください")
            self.combo_gfx_type.setToolTip("有効な型を選択してください")
            return

        missing_fields = []
        for field_name in schema_required_fields(schema, definition_type, GFX_SCHEMA_FIELD_BINDINGS):
            if not self.schema_field_value(field_name).strip():
                missing_fields.append(field_name)

        self.combo_gfx_type.setToolTip(
            f"{definition_type}\n"
            f"{'、'.join(schema_required_fields(schema, definition_type, GFX_SCHEMA_FIELD_BINDINGS)) or '必須項目はありません'}"
        )

        if missing_fields:
            self.btn_add.setEnabled(False)
            self.btn_add.setToolTip(missing_required_tooltip(missing_fields))
            return

        self.btn_add.setEnabled(True)
        self.btn_add.setToolTip("選択中の定義を更新できます" if has_selection else "必須項目がそろっています")

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

    def inline_action_icon_path(self, icon_name: str, icon_source: str) -> str:
        base_dir = os.path.dirname(__file__)
        if icon_source == "plugin":
            return os.path.abspath(os.path.join(base_dir, "..", "asset", "icons", icon_name))
        return os.path.abspath(os.path.join(base_dir, "..", "..", "..", "assets", "icons", icon_name))

    def load_inline_action_field(self, host: QWidget, *, icon_name: str, tooltip: str, on_clicked=None, icon_source: str = "plugin"):
        if not host:
            return None, None, None

        ui_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "widgets", "inline_action_field.ui"))
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            return None, None, None

        try:
            loader = QUiLoader()
            field = loader.load(ui_file, host)
        finally:
            ui_file.close()

        if not field:
            return None, None, None

        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = host.layout()
        if layout is None:
            layout = QVBoxLayout(host)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
        layout.addWidget(field)

        edit = field.findChild(QLineEdit, "editInlineActionText")
        button = field.findChild(QToolButton, "btnInlineAction")

        field.setProperty("active", False)
        if edit:
            edit.installEventFilter(self)
            self.inline_action_frame_by_edit[edit] = field
        if button:
            button.setToolTip(tooltip)
            icon_path = self.inline_action_icon_path(icon_name, icon_source)
            if os.path.exists(icon_path):
                color_hex = self.widget.palette().color(self.widget.foregroundRole()).name()
                button.setIcon(load_svg_icon(icon_path, color_hex))
            button.setIconSize(button.sizeHint())
            if on_clicked:
                button.clicked.connect(on_clicked)

        return field, edit, button

    def eventFilter(self, watched, event):
        frame = self.inline_action_frame_by_edit.get(watched)
        if frame:
            if event.type() == QEvent.Type.FocusIn:
                self.update_inline_action_frame_focus(frame, True)
            elif event.type() == QEvent.Type.FocusOut:
                self.update_inline_action_frame_focus(frame, False)
        if isinstance(watched, QMenu) and event.type() == QEvent.Type.MouseButtonRelease:
            action = watched.actionAt(event.pos())
            if action and action.isCheckable() and action.isEnabled():
                action.trigger()
                return True
        return super().eventFilter(watched, event)

    def update_name_frame_focus(self, focused: bool):
        self.update_inline_action_frame_focus(self.name_frame, focused)

    def update_inline_action_frame_focus(self, frame, focused: bool):
        if not frame:
            return
        frame.setProperty("active", focused)
        frame.style().unpolish(frame)
        frame.style().polish(frame)
        frame.update()

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

    def connect_source_line(self, control, property_name: str, output_control=None, preview: bool = False):
        if not control:
            return

        def on_finished():
            source_path = control.text().strip()
            self.set_definition_source_path(property_name, source_path)
            if source_path:
                default_value = self.default_dds_texture_value_for_source(source_path)
                if output_control:
                    current_output = output_control.text().strip()
                    if not current_output:
                        set_line(output_control, default_value)
                    self.set_current_property(property_name, output_control.text().strip())
            elif output_control:
                self.set_current_property(property_name, "")
            if source_path and self.edit_name and not self.edit_name.text().strip():
                new_name = self.generate_graphic_definition_name(source_path)
                if new_name:
                    self.edit_name.setText(new_name)
                    self.set_current_property("name", new_name)
            if preview and source_path:
                self.load_preview(source_path)

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

    def connect_add_button_refresh(self):
        if self.combo_gfx_type:
            self.combo_gfx_type.currentIndexChanged.connect(self.update_add_button_state)

        line_edits = [
            self.edit_name,
            self.edit_texture,
            self.edit_source_path,
            self.edit_source_path1,
            self.edit_source_path2,
            self.edit_effect,
            self.edit_texture1,
            self.edit_texture2,
            self.edit_mask,
            self.edit_color,
            self.edit_color_two,
        ]
        for control in line_edits:
            if control:
                control.textChanged.connect(self.update_add_button_state)

        for control in [
            self.spin_size_w,
            self.spin_size_h,
            self.spin_border_x,
            self.spin_border_y,
            self.spin_frames,
            self.spin_rate,
            self.spin_pause_on_loop,
        ]:
            if control:
                control.valueChanged.connect(lambda _value: self.update_add_button_state())

        for control in [
            self.check_horizontal,
            self.check_transparent,
            self.check_lazy_load,
            self.check_transparence,
            self.check_looping,
            self.check_play_on_show,
        ]:
            if control:
                control.toggled.connect(lambda _checked: self.update_add_button_state())

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
            self.update_add_button_state()
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
            "type": definition.definition_type,
            "group": definition.root_group,
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
            set_line(self.edit_source_path, self.source_path_for_definition(definition, "texturefile") if definition else "")
            set_line(self.edit_source_path1, self.source_path_for_definition(definition, "textureFile1") if definition else "")
            set_line(self.edit_source_path2, self.source_path_for_definition(definition, "textureFile2") if definition else "")
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
        finally:
            self.updating = False

        self.update_schema_visibility()
        self.update_definition_state()
        self.update_add_button_state()
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

    def add_definition_from_current(self):
        if self.current_definition() is not None:
            self.apply_current_definition_changes()
            return

        source_path = ""
        if self.edit_source_path:
            source_path = self.edit_source_path.text().strip()

        name = self.edit_name.text().strip() if self.edit_name else ""
        definition_type = self.combo_gfx_type.currentText() if self.combo_gfx_type else None
        self.create_definition(definition_type=definition_type, name=name or None, source_path=source_path)

    def create_definition(self, definition_type=None, name=None, source_path=""):
        if definition_type is None and self.combo_gfx_type:
            definition_type = self.combo_gfx_type.currentText() or "spriteType"
        if name is None:
            name = self.generate_graphic_definition_name(source_path) if source_path else ""

        definition = {
            "name": name,
            "type": definition_type or "spriteType",
            "group": "spriteTypes",
            "properties": {
                "name": name,
            },
            "order": ["name", "texturefile"],
        }
        if source_path:
            definition["_source_paths"] = {"texturefile": source_path}
        if (
            self.pending_new_definition_filter_settings
            and os.path.normcase(self.pending_new_definition_filter_source_path or "") == os.path.normcase(source_path or "")
        ):
            definition["_filter_settings"] = deepcopy(self.pending_new_definition_filter_settings)
        self.definitions.append(definition)
        self.pending_new_definition_filter_settings = None
        self.pending_new_definition_filter_source_path = ""
        self.selected_index = len(self.definitions) - 1
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.load_definition(self.selected_index)
        self.widget.is_dirty = True

    def apply_current_definition_changes(self):
        if self.selected_index is None or self.selected_index >= len(self.definitions):
            return
        definition = self.definitions[self.selected_index]
        if self.combo_gfx_type:
            definition["type"] = self.combo_gfx_type.currentText() or definition.get("type", "spriteType")
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.load_definition(self.selected_index)
        self.widget.is_dirty = True

    def apply_auto_naming(self):
        if not self.edit_name:
            return

        source_path = self.preferred_auto_naming_source_path()

        new_name = self.generate_graphic_definition_name(source_path)
        if not new_name:
            return

        set_line(self.edit_name, new_name)
        if self.current_definition():
            self.set_current_property("name", new_name)
        else:
            self.update_add_button_state()

    def preferred_auto_naming_source_path(self) -> str:
        definition = self.current_definition()
        definition_type = ""
        if definition:
            definition_type = (definition.get("type", "") or "").strip().lower()
        elif self.combo_gfx_type:
            definition_type = self.combo_gfx_type.currentText().strip().lower()

        if definition_type == "progressbartype":
            property_order = ("textureFile1", "textureFile2", "texturefile")
            source_edits = {
                "textureFile1": self.edit_source_path1,
                "textureFile2": self.edit_source_path2,
                "texturefile": self.edit_source_path,
            }
        else:
            property_order = ("texturefile", "textureFile1", "textureFile2")
            source_edits = {
                "texturefile": self.edit_source_path,
                "textureFile1": self.edit_source_path1,
                "textureFile2": self.edit_source_path2,
            }

        for property_name in property_order:
            source_edit = source_edits.get(property_name)
            if source_edit:
                source_path = source_edit.text().strip()
                if source_path:
                    return source_path

            if definition:
                source_path = self.source_path_for_definition(definition, property_name)
                if source_path:
                    return source_path

                props = definition.get("properties", {})
                actual_key = self.actual_property_key(props, property_name)
                value = self.unquote(props.get(actual_key, ""))
                if value:
                    resolved = self.resolve_texture_path(value)
                    if resolved and os.path.exists(resolved):
                        return resolved

        return ""

    def apply_auto_texture_naming(self, source_edit, texture_edit, property_name: str):
        if not texture_edit:
            return

        source_path = ""
        if source_edit:
            source_path = source_edit.text().strip()
        if not source_path:
            definition = self.current_definition()
            if definition:
                source_path = self.source_path_for_definition(definition, property_name)

        if not source_path:
            return

        new_value = self.default_dds_texture_value_for_source(source_path)
        if not new_value:
            return

        set_line(texture_edit, new_value)
        if self.current_definition():
            self.set_current_property(property_name, new_value)

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
        if definition.get("_source_paths"):
            copy["_source_paths"] = dict(definition.get("_source_paths", {}))
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
        self.browse_texture_source(self.edit_source_path, self.edit_texture, "texturefile", "Select texture image")

    def open_image_tools_dialog(self):
        source_path = self.preferred_auto_naming_source_path()
        if not source_path and self.edit_source_path:
            source_path = self.edit_source_path.text().strip()
        if not source_path:
            QMessageBox.information(self.widget, "画像を開けません", "先に加工対象の画像を読み込んでください。")
            return
        if not os.path.exists(source_path):
            QMessageBox.warning(self.widget, "画像を開けません", f"画像ファイルが見つかりません。\n\n{source_path}")
            return

        from plugins.hoi4.interface.image_tools_dialog import ImageToolsDialog

        dialog = ImageToolsDialog(source_path, self.widget)
        
        definition = self.current_definition()
        pending_filter_settings = None
        if definition and "_filter_settings" in definition:
            pending_filter_settings = definition["_filter_settings"]
        elif (
            self.pending_new_definition_filter_settings
            and os.path.normcase(self.pending_new_definition_filter_source_path or "") == os.path.normcase(source_path or "")
        ):
            pending_filter_settings = self.pending_new_definition_filter_settings
        if pending_filter_settings:
            try:
                dialog.apply_filter_settings(pending_filter_settings)
            except Exception as e:
                print(f"Failed to apply previous filter settings: {e}")

        if dialog.exec() == 1:
            output_image = getattr(dialog, "preview_image", None) or getattr(dialog, "processed_image", None)
            if definition is not None:
                definition["_filter_settings"] = dialog.filter_settings
                self.widget.is_dirty = True
            else:
                self.pending_new_definition_filter_settings = deepcopy(dialog.filter_settings)
                self.pending_new_definition_filter_source_path = source_path

            if output_image is not None and not output_image.isNull():
                self.update_preview_controls_visibility(source_path)
                self.show_preview_pixmap(QPixmap.fromImage(output_image))
            else:
                self.load_preview_from_current()

    def browse_texture_destination(self, texture_edit, property_name: str, title: str, source_edit=None):
        default_path = ""
        if texture_edit:
            current_texture = texture_edit.text().strip()
            if current_texture:
                default_path = self.resolve_texture_path(current_texture)
        if not default_path and source_edit:
            source_path = source_edit.text().strip()
            if source_path:
                default_path = self.default_dds_output_path_for_source(source_path)

        path, _ = QFileDialog.getSaveFileName(
            self.widget,
            title,
            default_path or os.path.join(self.get_mod_root(), "gfx"),
            "DDS Files (*.dds);;All Files (*.*)",
        )
        if not path:
            return

        root, ext = os.path.splitext(path)
        if not ext:
            path = root + ".dds"
        texture_value = self.texture_value_for_path(path)
        if texture_edit:
            set_line(texture_edit, texture_value)
        self.set_current_property(property_name, texture_value)
        if self.current_definition():
            self.load_preview_from_current()

    def browse_texture_source(self, source_edit, texture_edit, property_name: str, title: str, overwrite_texture: bool = False):
        path = self.select_image_file(title, source_edit)
        if not path:
            return
        texture_value = self.default_dds_texture_value_for_source(path)
        if source_edit:
            set_line(source_edit, path)
        should_update_texture = bool(texture_edit) and (overwrite_texture or not texture_edit.text().strip())
        if should_update_texture:
            set_line(texture_edit, texture_value)
        self.set_definition_source_path(property_name, path)
        if should_update_texture:
            self.set_current_property(property_name, texture_value)

        if path and self.edit_name and not self.edit_name.text().strip():
            new_name = self.generate_graphic_definition_name(path)
            if new_name:
                self.edit_name.setText(new_name)
                self.set_current_property("name", new_name)

        self.load_preview(path)

    def select_image_file(self, title: str, source_edit=None) -> str:
        start_dir = ""
        if source_edit:
            current_value = source_edit.text().strip()
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
            self.update_add_button_state()
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
        self.update_add_button_state()

    def set_definition_source_path(self, property_name: str, path: str):
        definition = self.current_definition()
        if not definition:
            return
        source_paths = definition.setdefault("_source_paths", {})
        if path:
            source_paths[property_name] = path
        else:
            source_paths.pop(property_name, None)
        if not source_paths:
            definition.pop("_source_paths", None)

    def source_path_for_current_definition(self, property_name: str) -> str:
        definition = self.current_definition()
        if not definition:
            return ""
        return self.source_path_for_definition(definition, property_name)

    def source_path_for_definition(self, definition: dict, property_name: str) -> str:
        source_paths = definition.get("_source_paths", {}) if definition else {}
        return source_paths.get(property_name, "")

    def default_dds_output_path_for_source(self, source_path: str) -> str:
        if not source_path:
            return ""
        source_name = os.path.splitext(os.path.basename(source_path))[0]
        settings = self.get_plugin_settings()
        format_str = settings.get("graphic_texture_file_format", "GFX_{file}")
        formatted_name = self.apply_format(format_str, file=source_name, number=1, **{"a-z": "a"}).strip()
        if not formatted_name:
            formatted_name = source_name
        formatted_name = "_".join(formatted_name.split())
        return os.path.join(self.get_mod_root(), "gfx", f"{formatted_name}.dds")

    def default_gfx_file_name(self) -> str:
        settings = self.get_plugin_settings()
        format_str = settings.get("graphic_definition_file_name_format", "GFX_{file}")

        source_path = self.preferred_auto_naming_source_path()
        file_stem = os.path.splitext(os.path.basename(source_path))[0] if source_path else ""
        if not file_stem:
            current = self.current_definition()
            if current:
                file_stem = str(current.get("name", "") or "").strip()
        if not file_stem:
            file_stem = "untitled"

        formatted_name = self.apply_format(format_str, file=file_stem, number=1, **{"a-z": "a"}).strip()
        if not formatted_name:
            formatted_name = file_stem
        formatted_name = "_".join(formatted_name.split())
        return formatted_name or "untitled"

    def default_dds_texture_value_for_source(self, source_path: str) -> str:
        return self.texture_value_for_path(self.default_dds_output_path_for_source(source_path))

    def on_type_changed(self):
        if self.updating:
            return
        if not self.combo_gfx_type:
            return
        self.update_schema_visibility()
        self.update_add_button_state()

        definition = self.current_definition()
        if not definition:
            return
        definition["type"] = self.combo_gfx_type.currentText() or "spriteType"
        self.serialize_document()
        self.refresh_definition_list(self.selected_index)
        self.widget.is_dirty = True
        self.update_add_button_state()

    def actual_property_key(self, props: dict, property_name: str) -> str:
        for key in props.keys():
            if key.lower() == property_name.lower():
                return key
        return property_name

    def serialize_document(self):
        self.widget.content = self.serialize_definitions(self.definitions)

    def serialize_definitions(self, definitions: list[dict]) -> str:
        groups: dict[str, list[dict]] = {}
        for definition in definitions:
            groups.setdefault(definition.get("group", "spriteTypes"), []).append(definition)

        sections = []
        for group, group_definitions in groups.items():
            lines = [f"{group} = {{"]
            for definition in group_definitions:
                lines.append(self.serialize_definition(definition))
            lines.append("}")
            sections.append("\n".join(lines))
        return "\n\n".join(sections) + ("\n" if sections else "")

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

    def save_related_textures(self) -> bool:
        failures = []
        changed = False

        for definition in self.definitions:
            props = definition.get("properties", {})
            source_paths = definition.get("_source_paths", {})
            filter_settings = definition.get("_filter_settings")
            for property_name in DDS_TEXTURE_PROPERTIES:
                actual_key = self.actual_property_key(props, property_name)
                value = self.unquote(props.get(actual_key, ""))
                if not value and actual_key not in source_paths:
                    continue

                source_path = source_paths.get(actual_key, "")
                if not source_path and value:
                    source_path = self.resolve_texture_path(value)
                if not source_path or not os.path.exists(source_path):
                    failures.append(f"{definition.get('name', '')} / {actual_key}: {value}")
                    continue

                output_path = self.dds_output_path_for_texture(value, source_path)
                if not self.save_dds_texture(source_path, output_path, filter_settings):
                    failures.append(f"{definition.get('name', '')} / {actual_key}: {output_path}")
                    continue

                output_value = self.texture_value_for_path(output_path)
                if output_value != value:
                    props[actual_key] = output_value
                    changed = True

        if changed and self.selected_index is not None:
            self.load_definition(self.selected_index)

        if failures:
            QMessageBox.warning(
                self.widget,
                "DDS書き出し失敗",
                "画像のDDS書き出しに失敗しました。\n\n" + "\n".join(failures),
            )
            return False

        return True

    def save_dds_texture(self, source_path: str, output_path: str, filter_settings: dict = None) -> bool:
        pil_image = None
        if filter_settings:
            try:
                from plugins.hoi4.interface.image_tools_dialog import ImageToolsDialog
                dialog = ImageToolsDialog(source_path, self.widget)
                dialog.apply_filter_settings(filter_settings)
                processed_pil = dialog.build_processed_image()
                pil_image = dialog.build_preview_image(processed_pil)
            except Exception as e:
                print(f"Failed to apply filter settings for DDS export: {e}")
                pil_image = None

        if pil_image is None:
            pil_image = load_pil_image(source_path)

        if pil_image is None:
            return False

        try:
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            pil_image.save(output_path, format="DDS", pixel_format="DXT5")
        except Exception:
            return False
        return True

    def dds_output_path_for_texture(self, texture_value: str, source_path: str = "") -> str:
        texture_value = self.unquote(texture_value)
        if texture_value:
            if os.path.isabs(texture_value):
                root, _ = os.path.splitext(texture_value)
                return root + ".dds"
            normalized = texture_value.replace("\\", "/")
            if "/" not in normalized and not normalized.startswith("gfx/"):
                normalized = f"gfx/{normalized}"
            root, _ = os.path.splitext(os.path.join(self.get_mod_root(), normalized))
            return root + ".dds"
        if source_path:
            return self.default_dds_output_path_for_source(source_path)
        return ""

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
        props = definition.get("properties", {})
        source_paths = definition.get("_source_paths", {})
        
        filter_settings = definition.get("_filter_settings")
        
        for key in ("texturefile", "textureFile1", "textureFile2"):
            actual_key = self.actual_property_key(props, key)
            source_path = source_paths.get(actual_key, "")
            if source_path and os.path.exists(source_path):
                self.load_preview(source_path, filter_settings)
                return
            texture = self.unquote(props.get(actual_key, ""))
            if texture:
                resolved = self.resolve_texture_path(texture)
                if resolved and os.path.exists(resolved):
                    self.load_preview(resolved, filter_settings)
                    return
        self.clear_preview()

    def load_preview(self, path: str, filter_settings: dict = None):
        if not path:
            self.clear_preview()
            return False

        self.update_preview_controls_visibility(path)
        
        pixmap = None
        if filter_settings:
            try:
                from plugins.hoi4.interface.image_tools_dialog import ImageToolsDialog
                qimage = ImageToolsDialog.render_preview_from_settings(path, filter_settings, self.widget)
                if qimage and not qimage.isNull():
                    pixmap = QPixmap.fromImage(qimage)
            except Exception as e:
                print(f"Failed to render preview with filter settings: {e}")
                pixmap = None

        if pixmap is None:
            pixmap = QPixmap(path)

        if pixmap.isNull():
            self.clear_preview()
            return False

        self.show_preview_pixmap(pixmap)
        self.update_preview_placeholder_visibility()
        return True

    def show_preview_pixmap(self, pixmap):
        if self.preview_scene is None or pixmap is None or pixmap.isNull():
            return

        self.preview_scene.clear()

        try:
            from plugins.hoi4.interface.ui_image_helpers import create_checker_item
            checker_item = create_checker_item()
            checker_item.setRect(0, 0, pixmap.width(), pixmap.height())
            checker_item.setZValue(-1)
            self.preview_scene.addItem(checker_item)
        except Exception as e:
            print(f"Failed to create checker background: {e}")

        self.preview_item = QGraphicsPixmapItem(pixmap)
        self.preview_item.setZValue(0)
        self.preview_scene.addItem(self.preview_item)
        self.preview_scene.setSceneRect(self.preview_item.boundingRect())
        self.fit_preview_to_view()

    def clear_preview(self):
        if self.preview_scene:
            self.preview_scene.clear()
        self.preview_item = None
        self.update_preview_controls_visibility("")
        self.update_preview_placeholder_visibility()

    def update_preview_controls_visibility(self, path: str):
        if not self.group_preview_control:
            return
        ext = os.path.splitext(path or "")[1].lower()
        self.group_preview_control.setVisible(ext in ANIMATED_PREVIEW_EXTENSIONS)

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
