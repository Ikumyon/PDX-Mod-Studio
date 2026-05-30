import os
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QFileDialog
import core.api
from core.encoding_controller import decode_with_encoding, read_text_with_detected_encoding
from core.inspector import (
    EncodingType as InspectorEncodingType,
    FileType as InspectorFileType,
    inspect_file,
)

tr = QCoreApplication.translate

class FileOpenController:
    def __init__(
        self,
        window,
        editor_tabs,
        editor_registry,
        project_tree,
        create_editor_widget,
        get_element_for_path,
        update_editor_selector,
        next_tab_id,
        text_editor_id,
    ):
        self.window = window
        self.editor_tabs = editor_tabs
        self.editor_registry = editor_registry
        self.project_tree = project_tree
        self.create_editor_widget = create_editor_widget
        self.get_element_for_path = get_element_for_path
        self.update_editor_selector = update_editor_selector
        self.next_tab_id = next_tab_id
        self.text_editor_id = text_editor_id

    def open_file(self, file_path, editor_id=None, params=None):
        if not self.editor_tabs:
            return

        # 事前のバイナリ・文字コード判別
        file_type, encoding_type = inspect_file(file_path)

        if file_type == InspectorFileType.Binary:
            QMessageBox.warning(
                self.window,
                tr("MainWindow", "ファイルオープン"),
                tr("MainWindow", "このファイルはバイナリファイル（または極めて巨大なファイル）のため、テキストエディタで開くことはできません。")
            )
            return

        element = self.get_element_for_path(file_path)
        available_editors = self.editor_registry.get_editors_for_element(element) if element else []
        if editor_id is None:
            editor_id = self.text_editor_id
        else:
            editor_id = self.editor_registry.normalize_editor_id(editor_id)

        for i in range(self.editor_tabs.count()):
            widget = self.editor_tabs.widget(i)
            current_editor_id = self.editor_registry.normalize_editor_id(getattr(widget, "editor_id", self.text_editor_id))
            if self.editor_tabs.tabToolTip(i) == file_path and current_editor_id == editor_id:
                self.editor_tabs.setCurrentIndex(i)
                # 既に開いている場合は即座に適用
                if params and hasattr(widget, "set_params"):
                    widget.set_params(params)
                elif params:
                    widget.params = params
                self.update_editor_selector(i)
                return

        try:
            if encoding_type != InspectorEncodingType.Unknown:
                with open(file_path, "rb") as handle:
                    raw = handle.read()
                content, detected_encoding = decode_with_encoding(raw, encoding_type.value)
            else:
                content, detected_encoding = read_text_with_detected_encoding(file_path)

            # 新しく開く場合は、まずウィジェットを生成
            editor = self.create_editor_widget(
                editor_id,
                file_path,
                content,
                available_editors,
                tab_id=self.next_tab_id(),
                file_encoding=detected_encoding,
            )
            
            # パラメータがあれば「準備完了後」に適用されるように予約
            if params:
                self.window.pending_params[getattr(editor, "tab_id", None)] = params
            file_name = os.path.basename(file_path)
            if editor_id != self.text_editor_id:
                file_name = f"[E] {file_name}"
            editor.tab_base_text = file_name

            icon = self.project_tree.get_icon_for_path(file_path)
            index = self.editor_tabs.addTab(editor, icon, file_name)
            self.editor_tabs.setTabToolTip(index, file_path)
            self.editor_tabs.setCurrentIndex(index)
            self.update_editor_selector(index)
            self.project_tree.update_open_editors(self.editor_tabs)
        except Exception as error:
            QMessageBox.warning(
                self.window,
                tr("MainWindow", "ファイルオープン"),
                tr("MainWindow", "ファイルを開けませんでした: {error}").format(error=error),
            )

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            tr("MainWindow", "ファイルを開く"),
            core.api.get_project_path() or os.getcwd(),
            tr("MainWindow", "すべてのファイル (*.*)"),
        )
        if path:
            self.open_file(path)
