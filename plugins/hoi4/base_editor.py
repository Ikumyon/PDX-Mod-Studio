from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import core.api
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QPlainTextEdit,
)

from plugins.hoi4.script_parser import (
    AssignmentNode,
    ObjectNode,
    ParsedEntity,
    Parser,
    ScalarNode,
    SchemaEvaluator,
)


class BaseParsedEntity:
    """Common wrapper for schema-evaluated HOI4 script entities."""

    def __init__(self, entity: ParsedEntity):
        self.entity = entity
        self.id = entity.id
        self.parent_id = entity.parent_id
        self.node = entity.node
        self.source_path = entity.source_path

    @property
    def properties(self) -> dict[str, list[AssignmentNode]]:
        return self.entity.properties

    def first(self, key: str) -> Optional[AssignmentNode]:
        return self.entity.first(key)


@dataclass
class BaseDocument:
    properties: dict[str, Any] = field(default_factory=dict)
    ast: Any = None


class BaseParser:
    """Shared parser flow for editor documents backed by a single schema."""

    document_class = BaseDocument
    entity_class = BaseParsedEntity
    collection_attr = "entities"
    project_subdir = ""
    progress_label = "Parsing"
    cache_key: Optional[str] = None

    def __init__(self, schema_path: str):
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema_data = json.load(f)
        self.evaluator = SchemaEvaluator(self.schema_data)
        self.schema = self.schema_data

    def parse_ast(self, content: str):
        parser = Parser(content)
        ast, _, _ = parser.parse()
        return ast

    def create_document(self, ast, path: str) -> BaseDocument:
        doc = self.document_class()
        doc.ast = ast
        return doc

    def extract_document_properties(self, doc: BaseDocument, ast, path: str) -> None:
        pass

    def wrap_entity(self, entity: ParsedEntity):
        return self.entity_class(entity)

    def parse_document(self, path: str, content: str) -> BaseDocument:
        ast = self.parse_ast(content)
        doc = self.create_document(ast, path)
        self.extract_document_properties(doc, ast, path)

        items = getattr(doc, self.collection_attr)
        for entity in self.evaluator.evaluate(ast, path):
            items.append(self.wrap_entity(entity))
        return doc

    def project_scan_dir(self, project_path: str) -> str:
        return os.path.join(project_path, self.project_subdir)

    def iter_project_files(self, scan_dir: str) -> list[str]:
        all_files = []
        for root, _, files in os.walk(scan_dir):
            for file in files:
                if file.endswith(".txt"):
                    all_files.append(os.path.join(root, file))
        return all_files

    def parse_project(self, project_path: str) -> list[Any]:
        parsed_items = []
        scan_dir = self.project_scan_dir(project_path)
        if not os.path.exists(scan_dir):
            return parsed_items

        all_files = self.iter_project_files(scan_dir)
        total_files = len(all_files)
        for i, path in enumerate(all_files):
            if total_files:
                progress = int((i / total_files) * 100)
                core.api.set_progress(progress, f"{self.progress_label}: {os.path.basename(path)}")
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    doc = self.parse_document(path, f.read())
                parsed_items.extend(getattr(doc, self.collection_attr))
            except Exception:
                continue

        core.api.set_progress(100, "")
        self.store_project_cache(parsed_items)
        return parsed_items

    def serialize_project_items(self, items: list[Any]) -> list[dict[str, Any]]:
        return [{"id": item.id, "source_path": item.source_path} for item in items]

    def store_project_cache(self, items: list[Any]) -> None:
        if not self.cache_key:
            return
        plugin = core.api.get_active_plugin()
        if not plugin:
            return
        if not hasattr(plugin, "project_cache"):
            plugin.project_cache = {}
        plugin.project_cache[self.cache_key] = self.serialize_project_items(items)


class BaseEditorController(QObject):
    """Common QObject controller utilities for HOI4 editors."""

    ELEMENT_ID = ""
    DEFAULT_FORMAT_FILE = ""
    PREVIEW_UPDATE_DELAY_MS = 150

    def __init__(self, widget, file_path: str, content: str):
        super().__init__()
        self.widget = widget
        self.file_path = file_path
        self.widget.content = content
        self.updating = False
        self.element_config = {}
        self.format_config = {}
        if self.ELEMENT_ID:
            self.initialize_config()

    def get_element_config(self) -> dict:
        """自身（具象クラス）の ELEMENT_ID に基づき、config情報を取得する"""
        plugin = self.get_hoi4_plugin()
        if plugin and self.ELEMENT_ID:
            for element in getattr(plugin, "elements", []):
                if element.id == self.ELEMENT_ID:
                    return element.raw
        return {}

    def load_format_config(self) -> dict:
        """自身（具象クラス）の情報に基づき、フォーマット設定ファイルをロードする"""
        config = self.get_element_config()
        format_file = config.get("format", "")
        
        if not format_file:
            format_file = self.DEFAULT_FORMAT_FILE
            
        if not format_file:
            return {}
            
        module = sys.modules[self.__class__.__module__]
        base_dir = os.path.dirname(getattr(module, "__file__", ""))
        
        path = os.path.join(base_dir, format_file)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def initialize_config(self):
        """要素のconfig情報およびフォーマット設定を初期化する"""
        self.element_config = self.get_element_config()
        self.format_config = self.load_format_config()

    def find(self, cls, name: str):
        return self.widget.findChild(cls, name)

    def get_hoi4_plugin(self):
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
        path = core.api.get_project_path()
        if path:
            return path
        return os.path.dirname(self.file_path)

    def plugin_root_dir(self) -> str:
        module = sys.modules[self.__class__.__module__]
        module_file = getattr(module, "__file__", "")
        module_dir = os.path.dirname(module_file)
        if os.path.basename(module_dir) in {"achievement", "decisions", "events", "localisation"}:
            return os.path.dirname(module_dir)
        return module_dir

    def get_plugin_settings(self):
        settings_path = os.path.join(self.plugin_root_dir(), "settings.json")
        try:
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def get_item_content(self, path: str) -> str:
        if not path or path == self.file_path:
            return self.widget.content

        cache = getattr(self, "file_contents", None)
        if cache is not None and path in cache:
            return cache[path]

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return ""

        if cache is not None:
            cache[path] = content
        return content

    def apply_format(self, fmt: str, **kwargs) -> str:
        try:
            return fmt.format(**kwargs)
        except Exception:
            result = fmt
            for key, value in kwargs.items():
                result = result.replace(f"{{{key}}}", str(value))
            return result

    def localised_text(self, key: str, fallback: str = "") -> str:
        return self.localisation_value(key, fallback=fallback, allow_empty=False)

    def localisation_registry(self):
        plugin = self.get_hoi4_plugin()
        return getattr(plugin, "localisation_registry", None) if plugin else None

    def localisation_lookup(self, key: str):
        registry = self.localisation_registry()
        if not registry:
            return "not_found", None
        return registry.search_key_status(key)

    def localisation_entry(self, key: str):
        _, entry = self.localisation_lookup(key)
        return entry

    def localisation_value(self, key: str, fallback: str = "", allow_empty: bool = True, strip: bool = False) -> str:
        if not key:
            return fallback
        _, entry = self.localisation_lookup(key)
        if entry and "value" in entry:
            value = entry.get("value") or ""
            if value or allow_empty:
                return value.strip() if strip else value
        return fallback

    def localisation_file_errors(self, entry) -> list:
        if not entry:
            return []
        registry = self.localisation_registry()
        if not registry:
            return []
        return registry.get_file_errors(entry.get("file", ""))

    def update_preview_delayed(self) -> None:
        if not hasattr(self, "preview_timer"):
            self.preview_timer = QTimer()
            self.preview_timer.setSingleShot(True)
            self.preview_timer.timeout.connect(self.update_preview)
        self.preview_timer.start(self.PREVIEW_UPDATE_DELAY_MS)

    def set_content(self, content: str) -> None:
        self.widget.content = content
        self.refresh()
        self.widget.is_dirty = False

    def set_params(self, params) -> None:
        pass

    def refresh(self) -> None:
        raise NotImplementedError

    def connect_scalar(self, control, property_name: str) -> None:
        if control:
            control.editingFinished.connect(lambda: self.replace_property(property_name, control.text()))

    def connect_text(self, control, property_name: str) -> None:
        if control:
            control.focusOutEvent = lambda event: self.on_text_focus_out(property_name, control, event)

    def connect_spin(self, control, property_name: str) -> None:
        if control:
            control.valueChanged.connect(lambda value: self.replace_property(property_name, str(value) if value > 0 else ""))

    def connect_bool(self, control, property_name: str) -> None:
        if not control:
            return

        def on_toggled(checked, name=property_name):
            if self.updating:
                return
            settings = self.get_plugin_settings()
            value = "yes" if checked else ("no" if settings.get("explicit_no_export", False) else "")
            self.replace_property(name, value)

        control.toggled.connect(on_toggled)

    def connect_combo(self, control, property_name: str) -> None:
        if control:
            control.currentIndexChanged.connect(lambda: self.replace_property(property_name, control.currentText()))

    def on_text_focus_out(self, property_name: str, control, event) -> None:
        QPlainTextEdit.focusOutEvent(control, event)
        self.replace_property(property_name, control.toPlainText())

    def _get_loc_text(self, widget) -> str:
        if not widget:
            return ""
        if hasattr(widget, "toPlainText"):
            return widget.toPlainText()
        if hasattr(widget, "text"):
            return widget.text()
        return ""

    def default_loc_filename(self) -> str:
        return "localisation_l_japanese.yml"

    def selected_loc_filename(self, widget) -> str:
        filename = widget.text().strip() if widget and hasattr(widget, "text") else ""
        if not filename or not filename.lower().endswith(".yml"):
            filename = self.default_loc_filename()
        return filename

    def selected_loc_path(self, loc_file_widget=None) -> str:
        filename = self.selected_loc_filename(loc_file_widget)
        if os.path.isabs(filename):
            return filename
        return os.path.join(self.get_mod_root(), "localisation", filename)

    def save_localisation(self, key, text, loc_file_widget=None) -> None:
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
        save_path = self.resolve_localisation_save_path(registry, key, status, entry, loc_file_widget)
        if not save_path:
            return

        save_empty_loc = settings.get("save_empty_localisation", False)
        self._write_to_loc_file(save_path, key, text, lang, save_empty_loc)
        self.refresh_localisation_registry(registry, save_path)
        self.after_save_localisation(key, save_path)

    def resolve_localisation_save_path(self, registry, key, status, entry, loc_file_widget=None) -> str:
        if status in ("exists_in_mod", "duplicate") and entry:
            save_path = entry["file"]
            if os.path.exists(save_path):
                registry.update_file(save_path, "mod")
                status, entry = registry.search_key_status(key)
                if status == "exists_in_hoi4":
                    print(f"Skipping save for HOI4 internal key after refresh: {key}")
                    return ""
                if status in ("exists_in_mod", "duplicate") and entry:
                    return entry["file"]
            else:
                if hasattr(registry, "remove_file_entries"):
                    registry.remove_file_entries(save_path)
                status, entry = registry.search_key_status(key)
                if status == "exists_in_hoi4":
                    print(f"Skipping save for HOI4 internal key after file deletion: {key}")
                    return ""
                if status in ("exists_in_mod", "duplicate") and entry:
                    return entry["file"]

        return self.selected_loc_path(loc_file_widget)

    def browse_loc_file(self, target_widget) -> None:
        if not target_widget:
            return
        
        project_path = core.api.get_project_path()
        if not project_path:
            return
            
        loc_dir = os.path.normpath(os.path.join(project_path, "localisation"))
        os.makedirs(loc_dir, exist_ok=True)
        
        loc_files = []
        for root, _, files in os.walk(loc_dir):
            for f in files:
                if f.lower().endswith(".yml"):
                    rel = os.path.relpath(os.path.join(root, f), loc_dir).replace("\\", "/")
                    loc_files.append(rel)
                    
        if loc_files:
            file, ok = QInputDialog.getItem(
                self.widget,
                "ファイル選択",
                "翻訳先ファイルを選択してください:",
                loc_files,
                0,
                False
            )
            if ok and file:
                target_widget.setText(file)
                return
                
        file_path, _ = QFileDialog.getOpenFileName(
            self.widget,
            "ローカリゼーションファイルの選択",
            loc_dir,
            "YAML Files (*.yml)"
        )
        if file_path:
            try:
                rel_path = os.path.relpath(file_path, loc_dir).replace("\\", "/")
                target_widget.setText(rel_path)
            except ValueError:
                target_widget.setText(file_path)

    def refresh_localisation_registry(self, registry, save_path: str) -> None:
        set_ignore_path = getattr(registry, "set_ignore_path", None)
        if set_ignore_path:
            try:
                registry.update_file(save_path, "mod")
                set_ignore_path(save_path, True)
            finally:
                QTimer.singleShot(500, lambda: set_ignore_path(save_path, False))
        else:
            registry.update_file(save_path, "mod")

    def after_save_localisation(self, key, save_path: str) -> None:
        pass

    def _write_to_loc_file(self, path, key, text, lang, save_empty_loc=False) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
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


def scalar_text(assignment: Optional[AssignmentNode]) -> str:
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return ""
    return str(assignment.value.value)


def find(widget, cls, name: str):
    return widget.findChild(cls, name)


def prop_text(item: Optional[BaseParsedEntity], name: str) -> str:
    return scalar_text(item.first(name)) if item else ""


def prop_bool(item: Optional[BaseParsedEntity], name: str) -> bool:
    assignment = item.first(name) if item else None
    if not assignment or not isinstance(assignment.value, ScalarNode):
        return False
    if assignment.value.value_type == "bool":
        return bool(assignment.value.value)
    return str(assignment.value.raw).lower() in {"yes", "true"}


def block_text(content: str, node: Optional[AssignmentNode], name: str = "") -> str:
    if not node:
        return ""

    target_node = node
    if name:
        target_node = None
        if isinstance(node.value, ObjectNode):
            target_node = node.value.first_assignment(name)

    if not target_node:
        return ""

    value = target_node.value if hasattr(target_node, "value") else target_node
    if isinstance(value, ObjectNode):
        start = value.open_range.end_offset if value.open_range else value.range.start_offset + 1
        end = value.close_range.start_offset if value.close_range else value.range.end_offset - 1
        inner = content[start:end]
        lines = inner.strip("\r\n").splitlines()
        if not lines:
            return ""

        margin = None
        for line in lines:
            if not line.strip():
                continue
            match = re.match(r"^(\s*)", line)
            indent = match.group(1)
            if margin is None or len(indent) < len(margin):
                margin = indent

        if margin:
            lines = [line[len(margin):] if line.startswith(margin) else line for line in lines]

        return "\n".join(lines).strip("\r\n\t ")
    return content[value.range.start_offset : value.range.end_offset]


def set_line(control, value) -> None:
    if control:
        was_blocked = control.blockSignals(True)
        control.setText(value or "")
        control.blockSignals(was_blocked)


def set_plain(control, value) -> None:
    if control:
        was_blocked = control.blockSignals(True)
        control.setPlainText(value or "")
        control.blockSignals(was_blocked)


def set_spin(control, value) -> None:
    if control:
        was_blocked = control.blockSignals(True)
        try:
            control.setValue(int(value or 0))
        except Exception:
            control.setValue(0)
        control.blockSignals(was_blocked)


def set_checked(control, value) -> None:
    if control:
        was_blocked = control.blockSignals(True)
        control.setChecked(bool(value))
        control.blockSignals(was_blocked)


def set_combo(control, value) -> None:
    if not control:
        return
    was_blocked = control.blockSignals(True)
    index = control.findText(value, Qt.MatchFlag.MatchExactly)
    if index >= 0:
        control.setCurrentIndex(index)
    control.blockSignals(was_blocked)
