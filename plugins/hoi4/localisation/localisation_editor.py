from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import core.api
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)


EDITOR_NAME = "ローカリゼーションエディタ"


@dataclass
class LocalisationEntry:
    key: str
    value: str
    line: int | None = None
    line_index: int | None = None
    version: str = ""
    indent: str = " "
    comment: str = ""
    deleted: bool = False


class LocalisationEditorController:
    entry_re = re.compile(r'^(\s*)([A-Za-z0-9._-]+):(\d+)?\s*"(.*)"\s*(#.*)?$')
    header_re = re.compile(r'^\s*([A-Za-z0-9._-]+):\s*$')

    def __init__(self, widget, file_path, content):
        self.widget = widget
        self.file_path = file_path
        self.widget.content = content
        self.lines: list[str] = []
        self.entries: list[LocalisationEntry] = []
        self.errors: list[dict] = []
        self.header_language = ""
        self.header_line_index: int | None = None
        self.is_updating = False

    def bind(self):
        self.combo_language = self.find(QComboBox, "comboLanguage")
        self.edit_search = self.find(QLineEdit, "editSearch")
        self.combo_filter = self.find(QComboBox, "comboFilter")
        self.button_add = self.find(QPushButton, "buttonAdd")
        self.button_delete = self.find(QPushButton, "buttonDelete")
        self.button_reload = self.find(QPushButton, "buttonReload")
        self.table = self.find(QTableWidget, "tableEntries")
        self.edit_key = self.find(QLineEdit, "editKey")
        self.edit_value = self.find(QPlainTextEdit, "editValue")
        self.label_status = self.find(QLabel, "labelStatus")
        self.list_issues = self.find(QListWidget, "listIssues")

        self.setup_language_combo()
        self.setup_filter_combo()
        self.setup_table()
        self.connect_signals()
        self.refresh()

    def find(self, cls, name):
        return self.widget.findChild(cls, name)

    def setup_language_combo(self):
        if not self.combo_language:
            return
        for lang in self.load_config_languages():
            self.combo_language.addItem(lang.get("name", lang["id"]), lang["id"])

        if self.combo_language.count() == 0:
            for lang in ("l_english", "l_japanese", "l_french", "l_german", "l_spanish", "l_russian", "l_polish", "l_braz_por", "l_simp_chinese", "l_korean"):
                self.combo_language.addItem(lang, lang)

    def load_config_languages(self):
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                return json.load(handle).get("languages", [])
        except Exception:
            return []

    def setup_filter_combo(self):
        if not self.combo_filter:
            return
        filters = [
            ("すべて", "all"),
            ("未入力", "empty"),
            ("重複", "duplicate"),
            ("エラー", "error"),
            ("MOD登録済み", "mod"),
            ("HOI4由来", "hoi4"),
        ]
        for label, value in filters:
            self.combo_filter.addItem(label, value)

    def setup_table(self):
        if not self.table:
            return
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Key", "翻訳文", "状態", "行", "参照元"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

    def connect_signals(self):
        if self.edit_search:
            self.edit_search.textChanged.connect(self.apply_filter)
        if self.combo_filter:
            self.combo_filter.currentIndexChanged.connect(self.apply_filter)
        if self.combo_language:
            self.combo_language.currentIndexChanged.connect(self.on_language_changed)
        if self.button_add:
            self.button_add.clicked.connect(self.add_entry)
        if self.button_delete:
            self.button_delete.clicked.connect(self.delete_selected_entry)
        if self.button_reload:
            self.button_reload.clicked.connect(self.reload_from_disk)
        if self.table:
            self.table.itemChanged.connect(self.on_table_item_changed)
            self.table.currentCellChanged.connect(lambda *_args: self.show_selected_entry())
        if self.edit_key:
            self.edit_key.textEdited.connect(self.on_detail_key_changed)
        if self.edit_value:
            self.edit_value.textChanged.connect(self.on_detail_value_changed)

    def refresh(self):
        self.parse_content(self.widget.content)
        self.select_header_language()
        self.apply_filter()
        self.show_selected_entry()

    def parse_content(self, content):
        self.lines = content.splitlines(True)
        self.entries = []
        self.errors = []
        self.header_language = ""
        self.header_line_index = None

        header_found = False
        for index, line in enumerate(self.lines):
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            if not header_found:
                header_match = self.header_re.match(clean)
                if header_match:
                    self.header_language = header_match.group(1)
                    self.header_line_index = index
                    header_found = True
                    continue
                self.errors.append({"line": index + 1, "message": "言語ヘッダーが見つかりません"})
                continue

            entry_match = self.entry_re.match(line.rstrip("\r\n"))
            if entry_match:
                self.entries.append(LocalisationEntry(
                    key=entry_match.group(2),
                    value=self.unescape_value(entry_match.group(4)),
                    version=entry_match.group(3) or "",
                    indent=entry_match.group(1) or " ",
                    comment=entry_match.group(5) or "",
                    line=index + 1,
                    line_index=index,
                ))
            else:
                self.errors.append({"line": index + 1, "message": "ローカリゼーション行として解釈できません"})

        if not header_found:
            self.errors.append({"line": 0, "message": "言語ヘッダーがありません"})

    def select_header_language(self):
        if not self.combo_language:
            return
        target = self.header_language or self.default_language()
        for index in range(self.combo_language.count()):
            if self.combo_language.itemData(index) == target:
                blocker = QSignalBlocker(self.combo_language)
                self.combo_language.setCurrentIndex(index)
                del blocker
                return

    def default_language(self):
        plugin = core.api.get_active_plugin()
        settings_path = os.path.join(plugin.path, "settings.json") if plugin else ""
        try:
            with open(settings_path, "r", encoding="utf-8") as handle:
                return json.load(handle).get("display_language", "l_japanese")
        except Exception:
            return "l_japanese"

    def active_filter(self):
        if not self.combo_filter:
            return "all"
        return self.combo_filter.currentData() or "all"

    def apply_filter(self):
        if not self.table:
            return

        query = self.edit_search.text().strip().lower() if self.edit_search else ""
        active_filter = self.active_filter()
        counts = self.key_counts()

        blocker = QSignalBlocker(self.table)
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for entry_index, entry in enumerate(self.entries):
            if entry.deleted or not self.entry_matches(entry, query, active_filter, counts):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.set_table_entry(row, entry_index, entry, counts)

        self.table.setSortingEnabled(sorting)
        del blocker

        if self.table.rowCount() > 0 and self.table.currentRow() < 0:
            self.table.setCurrentCell(0, 0)

        self.refresh_issue_list()

    def entry_matches(self, entry, query, active_filter, counts):
        if query and query not in entry.key.lower() and query not in entry.value.lower():
            return False
        status, _source = self.entry_status(entry, counts)
        if active_filter == "empty":
            return not entry.value.strip()
        if active_filter == "duplicate":
            return status in {"duplicate", "duplicate_in_file"}
        if active_filter == "error":
            return not entry.key.strip() or not self.valid_key(entry.key)
        if active_filter == "mod":
            return status == "exists_in_mod"
        if active_filter == "hoi4":
            return status == "exists_in_hoi4"
        return True

    def set_table_entry(self, row, entry_index, entry, counts):
        status, source = self.entry_status(entry, counts)
        key_item = self.editable_item(entry.key)
        key_item.setData(Qt.ItemDataRole.UserRole, entry_index)
        self.table.setItem(row, 0, key_item)
        self.table.setItem(row, 1, self.editable_item(entry.value))
        self.table.setItem(row, 2, self.readonly_item(self.status_label(status)))
        self.table.setItem(row, 3, self.readonly_item(str(entry.line or "")))
        self.table.setItem(row, 4, self.readonly_item(source))

    def editable_item(self, text):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def readonly_item(self, text):
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def key_counts(self):
        counts = {}
        for entry in self.entries:
            if not entry.deleted and entry.key:
                counts[entry.key] = counts.get(entry.key, 0) + 1
        return counts

    def entry_status(self, entry, counts=None):
        counts = counts or self.key_counts()
        if not entry.key or not self.valid_key(entry.key):
            return "invalid", ""
        if counts.get(entry.key, 0) > 1:
            return "duplicate_in_file", "current file"

        plugin = core.api.get_active_plugin()
        registry = getattr(plugin, "localisation_registry", None) if plugin else None
        if not registry:
            return "not_found", ""

        status, registry_entry = registry.search_key_status(entry.key)
        source = ""
        if registry_entry:
            source = registry_entry.get("source", "")
            source_file = registry_entry.get("file", "")
            if source_file:
                source = f"{source}: {os.path.basename(source_file)}"
        return status, source

    def status_label(self, status):
        return {
            "exists_in_mod": "MOD",
            "exists_in_hoi4": "HOI4",
            "duplicate": "重複",
            "duplicate_in_file": "ファイル内重複",
            "not_found": "未登録",
            "invalid": "不正",
            "unknown": "不明",
        }.get(status, status)

    def valid_key(self, key):
        return bool(re.match(r"^[A-Za-z0-9._-]+$", key or ""))

    def selected_entry_index(self):
        if not self.table:
            return None
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def selected_entry(self):
        index = self.selected_entry_index()
        if index is None or index < 0 or index >= len(self.entries):
            return None
        return self.entries[index]

    def show_selected_entry(self):
        entry = self.selected_entry()
        self.is_updating = True
        try:
            if self.edit_key:
                self.edit_key.setText(entry.key if entry else "")
            if self.edit_value:
                self.edit_value.setPlainText(entry.value if entry else "")
            if self.label_status:
                self.update_detail_status(entry)
        finally:
            self.is_updating = False

    def refresh_issue_list(self):
        if not self.list_issues:
            return
        self.list_issues.clear()
        for error in self.errors:
            line = error.get("line", 0)
            prefix = f"Line {line}: " if line else ""
            self.list_issues.addItem(prefix + error.get("message", ""))

        counts = self.key_counts()
        for key, count in sorted(counts.items()):
            if count > 1:
                self.list_issues.addItem(f"Duplicate key: {key} ({count})")

    def on_table_item_changed(self, item):
        if self.is_updating or not item:
            return
        index_item = self.table.item(item.row(), 0)
        if not index_item:
            return
        entry_index = index_item.data(Qt.ItemDataRole.UserRole)
        if entry_index is None or entry_index >= len(self.entries):
            return

        entry = self.entries[entry_index]
        if item.column() == 0:
            entry.key = item.text().strip()
        elif item.column() == 1:
            entry.value = item.text()
        else:
            return

        self.update_content_from_model()
        self.apply_filter()
        self.restore_selection(entry_index)

    def on_detail_key_changed(self, text):
        if self.is_updating:
            return
        entry_index = self.selected_entry_index()
        entry = self.selected_entry()
        if entry is None:
            return
        entry.key = text.strip()
        self.update_content_from_model()
        self.refresh_visible_row(entry_index)

    def on_detail_value_changed(self):
        if self.is_updating:
            return
        entry_index = self.selected_entry_index()
        entry = self.selected_entry()
        if entry is None or not self.edit_value:
            return
        entry.value = self.edit_value.toPlainText()
        self.update_content_from_model()
        self.refresh_visible_row(entry_index)

    def refresh_visible_row(self, entry_index):
        if entry_index is None or not self.table or entry_index >= len(self.entries):
            return
        entry = self.entries[entry_index]
        counts = self.key_counts()
        blocker = QSignalBlocker(self.table)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item or item.data(Qt.ItemDataRole.UserRole) != entry_index:
                continue
            status, source = self.entry_status(entry, counts)
            self.table.item(row, 0).setText(entry.key)
            self.table.item(row, 1).setText(entry.value)
            self.table.item(row, 2).setText(self.status_label(status))
            self.table.item(row, 3).setText(str(entry.line or ""))
            self.table.item(row, 4).setText(source)
            break
        del blocker
        self.update_detail_status(entry)
        self.refresh_issue_list()

    def update_detail_status(self, entry):
        if not self.label_status:
            return
        if entry:
            status, source = self.entry_status(entry)
            text = self.status_label(status)
            if source:
                text = f"{text} / {source}"
            self.label_status.setText(text)
        else:
            self.label_status.setText("-")

    def restore_selection(self, entry_index):
        if not self.table or entry_index is None:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == entry_index:
                self.table.setCurrentCell(row, 0)
                return
        self.show_selected_entry()

    def on_language_changed(self):
        if self.is_updating:
            return
        self.header_language = self.combo_language.currentData() or self.default_language()
        self.update_content_from_model()

    def add_entry(self):
        key = self.unique_key("new_key")
        entry = LocalisationEntry(key=key, value="")
        self.entries.append(entry)
        self.update_content_from_model()
        self.apply_filter()
        self.restore_selection(len(self.entries) - 1)
        if self.edit_key:
            self.edit_key.setFocus()
            self.edit_key.selectAll()

    def delete_selected_entry(self):
        entry_index = self.selected_entry_index()
        entry = self.selected_entry()
        if entry is None:
            return
        entry.deleted = True
        self.update_content_from_model()
        self.apply_filter()
        next_index = min(entry_index or 0, len(self.entries) - 1)
        self.restore_selection(next_index)

    def unique_key(self, base):
        existing = {entry.key for entry in self.entries if not entry.deleted}
        if base not in existing:
            return base
        index = 2
        while f"{base}_{index}" in existing:
            index += 1
        return f"{base}_{index}"

    def reload_from_disk(self):
        if getattr(self.widget, "is_dirty", False):
            result = QMessageBox.question(
                self.widget,
                "再読み込み",
                "未保存の変更を破棄してファイルを再読み込みしますか？",
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        try:
            with open(self.file_path, "r", encoding="utf-8-sig", errors="replace") as handle:
                self.widget.content = handle.read()
            self.widget._last_notified_content = self.widget.content
            self.refresh()
        except Exception as error:
            QMessageBox.warning(self.widget, "再読み込みできません", str(error))

    def set_content(self, content):
        self.widget.content = content
        self.refresh()

    def update_content_from_model(self):
        lines = list(self.lines)
        language = self.header_language or self.default_language()

        entry_by_line = {}
        for entry in self.entries:
            if entry.line_index is not None:
                entry_by_line[entry.line_index] = entry

        new_lines = []
        header_written = False
        for old_index, line in enumerate(lines):
            if old_index == self.header_line_index:
                self.header_line_index = len(new_lines)
                new_lines.append(self.with_line_ending(line, f"{language}:"))
                header_written = True
                continue

            entry = entry_by_line.get(old_index)
            if entry:
                if entry.deleted:
                    entry.line_index = None
                    entry.line = None
                    continue
                entry.line_index = len(new_lines)
                entry.line = entry.line_index + 1
                new_lines.append(self.with_line_ending(line, self.format_entry(entry)))
                continue

            new_lines.append(line)

        if not header_written:
            new_lines.insert(0, f"{language}:\n")
            self.header_line_index = 0
            for entry in self.entries:
                if entry.line_index is not None:
                    entry.line_index += 1
                    entry.line = entry.line_index + 1

        append_lines = []
        for entry in self.entries:
            if entry.deleted or entry.line_index is not None:
                continue
            entry.line_index = len(new_lines) + len(append_lines)
            entry.line = entry.line_index + 1
            append_lines.append(self.format_entry(entry) + "\n")

        if append_lines and new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"

        self.lines = new_lines + append_lines
        self.widget.content = "".join(self.lines)

    def with_line_ending(self, original, text):
        if original.endswith("\r\n"):
            return text + "\r\n"
        if original.endswith("\n"):
            return text + "\n"
        return text + "\n"

    def format_entry(self, entry):
        version = entry.version or ""
        comment = f" {entry.comment}" if entry.comment else ""
        return f'{entry.indent or " "}{entry.key}:{version} "{self.escape_value(entry.value)}"{comment}'

    def escape_value(self, value):
        return (value or "").replace("\\", "\\\\").replace('"', '\\"')

    def unescape_value(self, value):
        result = []
        index = 0
        while index < len(value):
            char = value[index]
            if char == "\\" and index + 1 < len(value) and value[index + 1] in {'"', "\\"}:
                result.append(value[index + 1])
                index += 2
            else:
                result.append(char)
                index += 1
        return "".join(result)

    def on_save_triggered(self):
        self.update_content_from_model()
        try:
            with open(self.file_path, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write(self.widget.content)
        except Exception as error:
            QMessageBox.warning(self.widget, "保存できません", str(error))
            return False

        self.after_saved(self.file_path)
        return True

    def on_save_as_triggered(self):
        path, _ = QFileDialog.getSaveFileName(self.widget, "名前を付けて保存", self.file_path, "YAML Files (*.yml)")
        if not path:
            return False
        self.file_path = path
        self.widget.file_path = path
        return self.on_save_triggered()

    def after_saved(self, path):
        plugin = core.api.get_active_plugin()
        registry = getattr(plugin, "localisation_registry", None) if plugin else None
        if registry:
            registry.update_file(path, "mod")
        core.api.notify_loc_changed()
        self.parse_content(self.widget.content)
        self.apply_filter()
        core.api.show_message(f"Saved localisation: {os.path.basename(path)}", 3000)


def setup(widget, file_path, content):
    controller = LocalisationEditorController(widget, file_path, content)
    widget.plugin_controller = controller
    widget.toPlainText = lambda: widget.content
    widget.setPlainText = controller.set_content
    widget.on_save_triggered = controller.on_save_triggered
    widget.on_save_as_triggered = controller.on_save_as_triggered
    controller.bind()
    core.api.notify_editor_ready(widget)
