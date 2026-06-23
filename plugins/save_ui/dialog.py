from __future__ import annotations

import os
from typing import Iterable

from PySide6.QtCore import QFile, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractItemDelegate,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)


class MultipleSaveTargetsDialog(QDialog):
    COLUMN_ENABLED = 0
    COLUMN_ROLE = 1
    COLUMN_DIRECTORY = 2
    COLUMN_FILENAME = 3
    COLUMN_FORMAT = 4
    COLUMN_BROWSE = 5

    def __init__(
        self,
        parent=None,
        *,
        title: str | None = None,
        description: str | None = None,
        targets: Iterable[dict] | None = None,
        format_options: Iterable[str] | None = None,
    ):
        super().__init__(parent)
        self._loader_root = None
        self._format_options = [str(value) for value in (format_options or []) if str(value)]
        self._load_ui()
        if title:
            self.setWindowTitle(title)
            self.labelTitle.setText(title)
        if description:
            self.labelDescription.setText(description)

        self._configure_table()
        self.btnSave.clicked.connect(self._accept_and_commit)
        self.btnCancel.clicked.connect(self.reject)

        if targets:
            self.set_targets(targets)

    def _load_ui(self) -> None:
        ui_path = os.path.join(os.path.dirname(__file__), "multiple_save_targets_dialog.ui")
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f"Could not open UI file: {ui_path}")

        try:
            loader = QUiLoader()
            loaded = loader.load(ui_file, self)
        finally:
            ui_file.close()

        if loaded is None:
            raise RuntimeError(f"Could not load UI file: {ui_path}")

        self._loader_root = loaded
        self.setLayout(loaded.layout())
        self.labelTitle = self.findChild(object, "labelTitle")
        self.labelDescription = self.findChild(object, "labelDescription")
        self.tableSaveTargets = self.findChild(QTableWidget, "tableSaveTargets")
        self.btnSave = self.findChild(QPushButton, "btnSave")
        self.btnCancel = self.findChild(QPushButton, "btnCancel")

        loaded.hide()

    def _configure_table(self) -> None:
        table = self.tableSaveTargets
        table.setRowCount(0)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(self.COLUMN_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(self.COLUMN_ROLE, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(self.COLUMN_DIRECTORY, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(self.COLUMN_FILENAME, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(self.COLUMN_FORMAT, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(self.COLUMN_BROWSE, QHeaderView.ResizeMode.ResizeToContents)

    def set_targets(self, targets: Iterable[dict]) -> None:
        target_list = [self._normalize_target(target) for target in targets]
        self.tableSaveTargets.setRowCount(0)
        for target in target_list:
            self._append_target_row(target)

    def _append_target_row(self, target: dict) -> None:
        table = self.tableSaveTargets
        row = table.rowCount()
        table.insertRow(row)

        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        enabled_item.setCheckState(Qt.CheckState.Checked if target["enabled"] else Qt.CheckState.Unchecked)
        enabled_item.setData(Qt.ItemDataRole.UserRole, target)
        table.setItem(row, self.COLUMN_ENABLED, enabled_item)

        role_item = QTableWidgetItem(target["role"])
        role_item.setFlags(role_item.flags() | Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, self.COLUMN_ROLE, role_item)

        directory_item = QTableWidgetItem(target["directory"])
        directory_item.setFlags(directory_item.flags() | Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, self.COLUMN_DIRECTORY, directory_item)

        filename_item = QTableWidgetItem(target["file_name"])
        filename_item.setFlags(filename_item.flags() | Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, self.COLUMN_FILENAME, filename_item)

        format_item = QTableWidgetItem(target["format"] or "")
        format_item.setFlags(format_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        table.setItem(row, self.COLUMN_FORMAT, format_item)

        browse_button = QPushButton("...", table)
        browse_button.clicked.connect(lambda checked=False, current_row=row: self._browse_row_path(current_row))
        table.setCellWidget(row, self.COLUMN_BROWSE, browse_button)

    def _normalize_target(self, target: dict) -> dict:
        normalized = dict(target or {})
        path = str(normalized.get("path", "") or "")
        directory = str(normalized.get("directory", "") or "")
        file_name = str(normalized.get("file_name", "") or "")
        fmt = str(normalized.get("format", "") or "")
        if path:
            split_dir, split_name = os.path.split(path)
            directory = directory or split_dir
            file_name = file_name or split_name
        file_name = self._ensure_extension(file_name, fmt)

        return {
            **normalized,
            "enabled": bool(normalized.get("enabled", True)),
            "role": str(normalized.get("role", "") or ""),
            "directory": directory,
            "file_name": file_name,
            "format": fmt,
            "path": path,
            "metadata": dict(normalized.get("metadata", {}) or {}),
        }

    def _browse_row_path(self, row: int) -> None:
        directory_item = self.tableSaveTargets.item(row, self.COLUMN_DIRECTORY)
        file_name_item = self.tableSaveTargets.item(row, self.COLUMN_FILENAME)
        format_item = self.tableSaveTargets.item(row, self.COLUMN_FORMAT)
        start_path = ""
        if directory_item and file_name_item:
            directory = directory_item.text().strip()
            file_name = file_name_item.text().strip()
            start_path = os.path.join(directory, file_name) if directory or file_name else ""

        selected_path, _ = QFileDialog.getSaveFileName(self, self.windowTitle(), start_path)
        if not selected_path:
            return

        selected_dir, selected_name = os.path.split(selected_path)
        selected_name = self._ensure_extension(selected_name, format_item.text().strip() if format_item else "")
        if directory_item:
            directory_item.setText(selected_dir)
        if file_name_item:
            file_name_item.setText(selected_name)

    def result_targets(self) -> list[dict]:
        results = []
        table = self.tableSaveTargets
        for row in range(table.rowCount()):
            enabled_item = table.item(row, self.COLUMN_ENABLED)
            role_item = table.item(row, self.COLUMN_ROLE)
            directory_item = table.item(row, self.COLUMN_DIRECTORY)
            file_name_item = table.item(row, self.COLUMN_FILENAME)
            format_item = table.item(row, self.COLUMN_FORMAT)

            original = enabled_item.data(Qt.ItemDataRole.UserRole) if enabled_item else {}
            directory = directory_item.text().strip() if directory_item else ""
            fmt = format_item.text().strip() if format_item else ""
            file_name = self._ensure_extension(file_name_item.text().strip() if file_name_item else "", fmt)
            path = os.path.join(directory, file_name) if directory or file_name else ""

            results.append(
                {
                    **dict(original or {}),
                    "enabled": enabled_item.checkState() == Qt.CheckState.Checked if enabled_item else True,
                    "role": role_item.text().strip() if role_item else "",
                    "directory": directory,
                    "file_name": file_name,
                    "format": fmt,
                    "path": path,
                }
            )
        return results

    def _accept_and_commit(self) -> None:
        table = self.tableSaveTargets
        editor = self.focusWidget()
        if editor and table and table.isAncestorOf(editor):
            table.commitData(editor)
            table.closeEditor(editor, QAbstractItemDelegate.EndEditHint.NoHint)
        if table:
            table.clearFocus()
            table.viewport().update()
        self.accept()

    def _ensure_extension(self, file_name: str, fmt: str) -> str:
        file_name = str(file_name or "").strip()
        fmt = str(fmt or "").strip().lstrip(".")
        if not file_name or not fmt:
            return file_name

        root, ext = os.path.splitext(file_name)
        if not ext:
            return f"{file_name}.{fmt}"
        if ext == ".":
            return f"{root}.{fmt}"
        return file_name
