import os
from PySide6.QtGui import QIcon
from core.i18n import tr

class EditorTabController:
    def __init__(self, parent_window, project_tree, next_tab_id_func, update_split_editor_button_func):
        self.window = parent_window
        self.project_tree = project_tree
        self.next_tab_id = next_tab_id_func
        self.update_split_editor_button = update_split_editor_button_func
        self.diagnostics_controller = None
        
        # 外部参照用コールバック（main.py側の関数を紐付ける）
        self.update_editor_corner_controls_pane = None
        self.update_editor_selector = None
        self.update_encoding_status = None
        self.get_widget_text_content = None
        self.get_widget_encoding = None
        self.create_editor_widget = None
        self.TEXT_EDITOR_ID = "core.plain_text"

    def _tab_text_without_dirty_marker(self, text):
        return text[1:] if text.startswith("*") else text

    def update_tab_label(self, widget):
        if not self.window.editorTabs or not widget:
            return
        index = self.window.editorTabs.indexOf(widget)
        if index < 0:
            return
        base_text = getattr(widget, "tab_base_text", None)
        if not base_text:
            base_text = self._tab_text_without_dirty_marker(self.window.editorTabs.tabText(index))
            widget.tab_base_text = base_text
        diagnostic_count = int(getattr(widget, "diagnostic_count", 0) or 0)
        text = f"{base_text} {diagnostic_count}" if diagnostic_count > 0 else base_text
        if getattr(widget, "is_dirty", False):
            text = f"*{text}"
        self.window.editorTabs.setTabText(index, text)

    def mark_tab_dirty(self, widget):
        if getattr(widget, "is_dirty", False):
            return
        widget.is_dirty = True
        self.update_tab_label(widget)
        self.project_tree.update_open_editors(self.window.editorTabs)

    def mark_tab_clean(self, widget):
        widget.is_dirty = False
        self.update_tab_label(widget)
        self.project_tree.update_open_editors(self.window.editorTabs)

    def update_saved_widget_path(self, widget, path):
        if not path:
            return
        widget.file_path = path
        index = self.window.editorTabs.indexOf(widget)
        if index >= 0:
            self.window.editorTabs.setTabToolTip(index, path)
            clean_text = self._tab_text_without_dirty_marker(self.window.editorTabs.tabText(index))
            editor_prefix = "[E] " if clean_text.startswith("[E] ") else ""
            widget.tab_base_text = f"{editor_prefix}{os.path.basename(path)}"
            self.update_tab_label(widget)
            self.project_tree.update_open_editors(self.window.editorTabs)

    def close_editor_tab(self, index):
        widget = self.window.editorTabs.widget(index)
        tab_id = getattr(widget, "tab_id", None)
        if tab_id in getattr(self.window, "pending_params", {}):
            del self.window.pending_params[tab_id]
        self.window.editorTabs.removeTab(index)
        self.project_tree.update_open_editors(self.window.editorTabs)
        if self.update_editor_corner_controls_pane:
            self.update_editor_corner_controls_pane()
        if self.update_split_editor_button:
            self.update_split_editor_button()

    def on_tab_changed(self, index):
        self.project_tree.sync_selection(index)
        if self.update_editor_corner_controls_pane:
            self.update_editor_corner_controls_pane()
        if self.update_editor_selector:
            self.update_editor_selector(index)
        if self.update_split_editor_button:
            self.update_split_editor_button()
        if self.update_encoding_status:
            self.update_encoding_status()
        if self.diagnostics_controller:
            self.diagnostics_controller.schedule_language_diagnostics(
                self.window.editorTabs.widget(index) if index >= 0 else None
            )

    def split_active_editor_right(self):
        if not self.window.editorTabs:
            return

        source_index = self.window.editorTabs.currentIndex()
        source_widget = self.window.editorTabs.currentWidget()
        if source_index < 0 or not source_widget:
            return

        file_path = self.window.editorTabs.tabToolTip(source_index)
        editor_id = self.TEXT_EDITOR_ID
        if hasattr(self.window, "editor_registry") and self.window.editor_registry:
            editor_id = self.window.editor_registry.normalize_editor_id(
                getattr(source_widget, "editor_id", self.TEXT_EDITOR_ID)
            )

        content = None
        if self.get_widget_text_content:
            content = self.get_widget_text_content(source_widget)
        if content is None:
            content = getattr(source_widget, "content", "")
        if content is None:
            content = ""

        split_tab_id = self.next_tab_id()
        file_encoding = None
        if self.get_widget_encoding:
            file_encoding = self.get_widget_encoding(source_widget)

        if not self.create_editor_widget:
            return

        split_widget = self.create_editor_widget(
            editor_id,
            file_path,
            content,
            getattr(source_widget, "available_editors", []),
            params=getattr(source_widget, "params", None),
            tab_id=split_tab_id,
            file_encoding=file_encoding,
        )

        if getattr(source_widget, "params", None) is not None:
            if not hasattr(self.window, "pending_params"):
                self.window.pending_params = {}
            self.window.pending_params[split_tab_id] = getattr(source_widget, "params")

        tab_name = getattr(source_widget, "tab_base_text", None) or self._tab_text_without_dirty_marker(
            self.window.editorTabs.tabText(source_index)
        )
        split_widget.tab_base_text = tab_name
        split_widget.diagnostic_count = int(getattr(source_widget, "diagnostic_count", 0) or 0)
        icon = self.window.editorTabs.tabIcon(source_index)
        target_pane = self.window.editorTabs.createPaneAfterActive()
        new_index = self.window.editorTabs.addTabToPane(
            split_widget,
            icon,
            tab_name,
            target_pane,
        )
        self.window.editorTabs.setTabToolTip(new_index, file_path)
        self.window.editorTabs.setCurrentIndex(new_index)
        self.update_tab_label(split_widget)

        if getattr(source_widget, "is_dirty", False):
            self.mark_tab_dirty(split_widget)

        self.project_tree.update_open_editors(self.window.editorTabs)
        if self.update_split_editor_button:
            self.update_split_editor_button()
        
        # 翻訳キーの適用
        self.window.statusBar().showMessage(tr("dashboard.error.split_success", "MainWindow"), 3000)
