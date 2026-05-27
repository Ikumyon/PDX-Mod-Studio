import os
import json
import subprocess
import tempfile
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from PySide6.QtCore import QFile, Qt, QTimer, QEvent, QObject, QAbstractItemModel, QModelIndex, QRect
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QToolButton, 
    QPushButton, QTreeView, QLabel, QMessageBox, QStyle,
    QCheckBox, QHeaderView, QStyledItemDelegate, QStyleOptionViewItem
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPalette, QTextCursor, QBrush
from core.search_engine import SearchQuery
from core.utils import load_svg_icon
import core.api


@dataclass(frozen=True)
class ProjectSearchRequest:
    generation: int
    cancel_event: threading.Event
    project_path: str | None
    include_patterns: tuple[str, ...]
    exclude_patterns: tuple[str, ...]
    open_editors: dict
    query: SearchQuery
    regex_pattern: str
    ignored_occurrences: list


@dataclass(frozen=True)
class ProjectSearchResult:
    generation: int
    current_results: dict
    project_path: str | None
    status_text: str


class SearchResultNode:
    def __init__(self, node_type: str, data: dict, parent=None):
        self.node_type = node_type
        self.data = data
        self.parent = parent
        self.children = []

    def row(self):
        if self.parent is None:
            return 0
        return self.parent.children.index(self)


class SearchResultsModel(QAbstractItemModel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.root = SearchResultNode("root", {})

    def rebuild(self, current_results: dict, project_path: str | None):
        self.beginResetModel()
        self.root = SearchResultNode("root", {})
        for file_path in sorted(current_results.keys(), key=lambda path: self.owner._display_path(path, project_path).lower()):
            occurrences = current_results[file_path]
            file_node = SearchResultNode("file", {
                "type": "file",
                "path": file_path,
                "display_path": self.owner._display_path(file_path, project_path),
                "count": len(occurrences),
            }, self.root)
            self.root.children.append(file_node)
            for occurrence in occurrences:
                occurrence_data = dict(occurrence)
                occurrence_data["path"] = file_path
                file_node.children.append(SearchResultNode("occurrence", {
                    "type": "occurrence",
                    "path": file_path,
                    "line_number": occurrence.get("line_number"),
                    "line_text": occurrence.get("line_text"),
                    "pos": occurrence.get("pos"),
                    "length": occurrence.get("length"),
                    "occurrence": occurrence_data,
                    "display_text": occurrence.get("display_text", ""),
                    "tooltip_text": occurrence.get("tooltip_text", ""),
                }, file_node))
        self.endResetModel()

    def index(self, row, column, parent=QModelIndex()):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        if row < 0 or row >= len(parent_node.children):
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent_node = node.parent
        if parent_node is None or parent_node is self.root:
            return QModelIndex()
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent=QModelIndex()):
        parent_node = parent.internalPointer() if parent.isValid() else self.root
        return len(parent_node.children)

    def columnCount(self, parent=QModelIndex()):
        return 2

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        data = node.data
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if node.node_type == "file":
                if column == 0:
                    return data["display_path"]
                if column == 1:
                    return str(data["count"])
            elif node.node_type == "occurrence" and column == 0:
                return data["display_text"]
            return ""
        if role == Qt.ItemDataRole.ToolTipRole:
            if node.node_type == "file" and column == 0:
                return data["path"]
            if node.node_type == "occurrence" and column == 0:
                return data["tooltip_text"]
        if role == Qt.ItemDataRole.DecorationRole and node.node_type == "file" and column == 0:
            return self.owner._file_result_icon()
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 1:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.UserRole:
            return data
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class SearchResultDelegate(QStyledItemDelegate):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def _action_rects(self, option):
        size = self.owner.RESULT_ACTION_BUTTON_SIZE
        spacing = self.owner.RESULT_ACTION_BUTTON_SPACING
        total_width = size * 2 + spacing
        left = option.rect.left() + max(0, (option.rect.width() - total_width) // 2)
        top = option.rect.top() + max(0, (option.rect.height() - size) // 2)
        replace_rect = QRect(left, top, size, size)
        ignore_rect = QRect(left + size + spacing, top, size, size)
        return replace_rect, ignore_rect

    def action_at(self, option, pos):
        replace_rect, ignore_rect = self._action_rects(option)
        if replace_rect.contains(pos):
            return "replace"
        if ignore_rect.contains(pos):
            return "ignore"
        return None

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole) or {}
        if index.column() != 1 or not data:
            super().paint(painter, option, index)
            return

        hovered = index == self.owner._hovered_result_index
        if not hovered:
            super().paint(painter, option, index)
            return

        replace_rect, ignore_rect = self._action_rects(option)
        if data.get("type") == "file":
            replace_icon = self.owner._cached_icon("replace-all.svg")
        else:
            replace_icon = self.owner._cached_icon("replace.svg")
        ignore_icon = self.owner._cached_icon("close.svg")
        hover_action = self.owner._hovered_result_action if hovered else None
        hover_color = option.palette.color(QPalette.ColorRole.Light)
        if hover_action == "replace":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(hover_color))
            painter.drawRoundedRect(replace_rect.adjusted(-2, -2, 2, 2), 4, 4)
        elif hover_action == "ignore":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(hover_color))
            painter.drawRoundedRect(ignore_rect.adjusted(-2, -2, 2, 2), 4, 4)
        replace_icon.paint(painter, replace_rect, Qt.AlignmentFlag.AlignCenter)
        ignore_icon.paint(painter, ignore_rect, Qt.AlignmentFlag.AlignCenter)

    def editorEvent(self, event, model, option, index):
        if event.type() != QEvent.Type.MouseButtonRelease or index.column() != 1:
            return super().editorEvent(event, model, option, index)
        data = index.data(Qt.ItemDataRole.UserRole) or {}
        if not data:
            return False
        action = self.action_at(option, event.position().toPoint())
        if action == "replace":
            self.owner._activate_result_action(data, "replace")
            return True
        if action == "ignore":
            self.owner._activate_result_action(data, "ignore")
            return True
        return False


class ProjectSearchDock(QObject):
    RESULT_COUNT_COLUMN_MIN_WIDTH = 34
    RESULT_COUNT_COLUMN_MAX_WIDTH = 72
    RESULT_COUNT_COLUMN_PADDING = 14
    RESULT_ACTION_BUTTON_SIZE = 14
    RESULT_ACTION_BUTTON_SPACING = 6

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.current_results = {} # {file_path: [SearchOccurrence, ...]}
        self.ignored_occurrences = set()
        self._last_search_signature = None
        self._hovered_result_index = QModelIndex()
        self._hovered_result_action = None
        self._result_action_column_width = self.RESULT_COUNT_COLUMN_MIN_WIDTH
        self._icon_cache = {}
        self._search_results_model = None
        self._search_result_delegate = None
        self._search_generation = 0
        self._search_cancel_event = None
        self._active_search_future = None
        self._search_dispatch_executor = ThreadPoolExecutor(max_workers=1)
        
        # リアルタイム（ライブ）検索用デバウンスタイマー
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300) # 300ms後に検索を実行
        self.search_timer.timeout.connect(self.on_search_clicked)
        self.search_result_timer = QTimer(self)
        self.search_result_timer.setInterval(30)
        self.search_result_timer.timeout.connect(self._poll_search_result)
        
        self._setup_ui()
        self._setup_connections()

    def get_widget(self) -> QDockWidget:
        return self.dock_widget

    def _setup_ui(self):
        loader = QUiLoader()
        ui_path = os.path.join(self.base_dir, "ui", "docks", "project_search_dock.ui")
        ui_file = QFile(ui_path)
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise FileNotFoundError(f"Cannot open UI file: {ui_path}")
        self.dock_widget = loader.load(ui_file, self.parent_window)
        ui_file.close()

        # UI要素の取得
        self.searchFieldContainer = self.dock_widget.findChild(QWidget, "searchFieldContainer")
        self.replaceRow = self.dock_widget.findChild(QWidget, "replaceRow")
        self.replaceFieldContainer = self.dock_widget.findChild(QWidget, "replaceFieldContainer")
        self.replaceAllButton = self.dock_widget.findChild(QToolButton, "replaceAllButton")
        self.filterPanel = self.dock_widget.findChild(QWidget, "filterPanel")
        self.projectSearchPanel = self.dock_widget.findChild(QWidget, "projectSearchPanel")
        self.includeInput = self.dock_widget.findChild(QLineEdit, "includeInput")
        self.excludeInput = self.dock_widget.findChild(QLineEdit, "excludeInput")
        self.searchOpenFilesCheckBox = self.dock_widget.findChild(QCheckBox, "searchOpenFilesCheckBox")
        self.searchButton = self.dock_widget.findChild(QPushButton, "searchButton")
        self.searchResultsTree = self.dock_widget.findChild(QTreeView, "searchResultsTree")
        self.searchStatusLabel = self.dock_widget.findChild(QLabel, "searchStatusLabel")

        # 新規追加されたトグルボタンの取得
        self.toggleReplaceButton = self.dock_widget.findChild(QToolButton, "toggleReplaceButton")
        self.toggleFilterButton = self.dock_widget.findChild(QToolButton, "toggleFilterButton")

        # 共通検索フィールドUIのロードと埋め込み
        search_field_ui_path = os.path.join(self.base_dir, "ui", "widgets", "search_input_field.ui")
        search_field_file = QFile(search_field_ui_path)
        if search_field_file.open(QFile.OpenModeFlag.ReadOnly):
            self.search_field = loader.load(search_field_file, self.searchFieldContainer)
            search_field_file.close()
            layout = QHBoxLayout(self.searchFieldContainer)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.search_field)
        else:
            raise FileNotFoundError(f"Cannot open UI file: {search_field_ui_path}")

        # 共通置換フィールドUIのロードと埋め込み
        replace_field_ui_path = os.path.join(self.base_dir, "ui", "widgets", "replace_input_field.ui")
        replace_field_file = QFile(replace_field_ui_path)
        if replace_field_file.open(QFile.OpenModeFlag.ReadOnly):
            self.replace_field = loader.load(replace_field_file, self.replaceFieldContainer)
            replace_field_file.close()
            layout = QHBoxLayout(self.replaceFieldContainer)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.replace_field)
        else:
            raise FileNotFoundError(f"Cannot open UI file: {replace_field_ui_path}")

        # 共通フィールド内ウィジェットのバインド
        self.searchInput = self.search_field.findChild(QLineEdit, "searchInput")
        self.caseSensitiveButton = self.search_field.findChild(QToolButton, "caseSensitiveButton")
        self.wholeWordButton = self.search_field.findChild(QToolButton, "wholeWordButton")
        self.regexButton = self.search_field.findChild(QToolButton, "regexButton")

        self.replaceInput = self.replace_field.findChild(QLineEdit, "replaceInput")
        self.preserveCaseButton = self.replace_field.findChild(QToolButton, "preserveCaseButton")

        # タイトルバーとアイコンの設定
        self.setup_title_bar()
        self._update_icons()

        # ツリー表示の設定
        self._search_results_model = SearchResultsModel(self)
        self._search_result_delegate = SearchResultDelegate(self)
        self.searchResultsTree.setModel(self._search_results_model)
        self.searchResultsTree.setItemDelegate(self._search_result_delegate)
        self.searchResultsTree.setHeaderHidden(True)
        self.searchResultsTree.setRootIsDecorated(True)
        self.searchResultsTree.setItemsExpandable(True)
        self.searchResultsTree.setUniformRowHeights(True)
        self.searchResultsTree.setIndentation(16)
        self.searchResultsTree.setMouseTracking(True)
        self.searchResultsTree.viewport().setMouseTracking(True)
        self.searchResultsTree.viewport().installEventFilter(self)
        header = self.searchResultsTree.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(20)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.searchResultsTree.setColumnWidth(1, self._result_action_column_width)
        
        # デフォルトで置換行は非表示（検索のみの状態）
        self.replaceRow.setVisible(False)

        # トグルボタンの初期状態の設定
        if self.toggleReplaceButton:
            self.toggleReplaceButton.setCheckable(True)
            self.toggleReplaceButton.setChecked(False)
        if self.toggleFilterButton:
            self.toggleFilterButton.setCheckable(True)
            self.toggleFilterButton.setChecked(True)
            self.toggleFilterButton.setText("フィルター")

        # イベントフィルターの適用（アクティブ枠線のQSS連動用）
        if self.searchInput:
            self.searchInput.installEventFilter(self)
        if self.replaceInput:
            self.replaceInput.installEventFilter(self)
        self.dock_widget.destroyed.connect(self._cleanup_event_filters)


        # toggleViewActionの設定（アクティビティバー用）
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        icon_search = load_svg_icon(os.path.join(icons_dir, "search.svg"), text_color)
        view_action = self.dock_widget.toggleViewAction()
        view_action.setIcon(icon_search)
        view_action.setText("検索")

    def _setup_connections(self):
        if self.searchButton:
            self.searchButton.clicked.connect(self.trigger_instant_search)
        if self.searchInput:
            self.searchInput.textChanged.connect(self.trigger_live_search)
            self.searchInput.returnPressed.connect(self.trigger_instant_search)
        if self.searchResultsTree:
            self.searchResultsTree.doubleClicked.connect(self.on_item_double_clicked)
            self.searchResultsTree.activated.connect(self.on_item_double_clicked)
        if self.replaceAllButton:
            self.replaceAllButton.clicked.connect(self.on_replace_all_clicked)

        if self.toggleReplaceButton:
            self.toggleReplaceButton.toggled.connect(self.on_toggle_replace)
        if self.toggleFilterButton:
            self.toggleFilterButton.toggled.connect(self.on_toggle_filter)

    def trigger_live_search(self):
        self._cancel_running_search()
        if hasattr(self, "search_timer"):
            self.search_timer.start()

    def trigger_instant_search(self):
        if hasattr(self, "search_timer"):
            self.search_timer.stop()
        self.on_search_clicked()

    def _cleanup_event_filters(self, *args):
        if hasattr(self, "search_timer"):
            self.search_timer.stop()
        if hasattr(self, "search_result_timer"):
            self.search_result_timer.stop()
        self._cancel_running_search()
        try:
            self._search_dispatch_executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._search_dispatch_executor.shutdown(wait=False)
        for widget_name in ("searchInput", "replaceInput"):
            try:
                widget = getattr(self, widget_name, None)
            except RuntimeError:
                continue
            if widget is None:
                continue
            try:
                widget.removeEventFilter(self)
            except RuntimeError:
                pass

    def _cancel_running_search(self):
        self._search_generation += 1
        if self._search_cancel_event:
            self._search_cancel_event.set()
        if self._active_search_future:
            self._active_search_future.cancel()
        if hasattr(self, "search_result_timer"):
            self.search_result_timer.stop()

    def eventFilter(self, watched, event):
        results_viewport = None
        try:
            results_viewport = self.searchResultsTree.viewport()
        except RuntimeError:
            pass

        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            has_focus = (event.type() == QEvent.Type.FocusIn)
            state = "true" if has_focus else "false"

            if watched == self.searchInput:
                self.search_field.setProperty("active", state)
                self.search_field.style().unpolish(self.search_field)
                self.search_field.style().polish(self.search_field)
            elif watched == self.replaceInput:
                self.replace_field.setProperty("active", state)
                self.replace_field.style().unpolish(self.replace_field)
                self.replace_field.style().polish(self.replace_field)
        elif watched == results_viewport:
            if event.type() == QEvent.Type.MouseMove:
                index = self.searchResultsTree.indexAt(event.position().toPoint())
                if index.isValid():
                    self._set_hovered_result_index(index, event.position().toPoint())
            elif event.type() == QEvent.Type.Leave:
                self._set_hovered_result_index(QModelIndex(), None)

        return False

    def setup_title_bar(self):
        self.title_widget = QWidget(self.dock_widget)
        bg_color = self.parent_window.palette().color(QPalette.ColorRole.Window).darker(110).name()
        self.title_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {bg_color};
                border-radius: 4px;
            }}
        """)
        
        layout = QHBoxLayout(self.title_widget)
        layout.setContentsMargins(8, 2, 2, 2)
        layout.setSpacing(2)

        # タイトルラベル
        self.title_label = QLabel("検索")
        layout.addWidget(self.title_label)
        layout.addStretch()

        # フロートボタン
        self.floatButton = QToolButton()
        self.floatButton.setIcon(self.dock_widget.style().standardIcon(QStyle.SP_TitleBarNormalButton))
        self.floatButton.setAutoRaise(True)
        self.floatButton.setToolTip("フロート切り替え")
        self.floatButton.clicked.connect(lambda: self.dock_widget.setFloating(not self.dock_widget.isFloating()))
        layout.addWidget(self.floatButton)

        # 閉じボタン
        self.closeButton = QToolButton()
        self.closeButton.setIcon(self.dock_widget.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.closeButton.setAutoRaise(True)
        self.closeButton.setToolTip("閉じる")
        self.closeButton.clicked.connect(self.dock_widget.close)
        layout.addWidget(self.closeButton)

        self.dock_widget.setTitleBarWidget(self.title_widget)

    def _update_icons(self):
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")

        case_sensitive_icon = load_svg_icon(os.path.join(icons_dir, "case-sensitive.svg"), text_color)
        whole_word_icon = load_svg_icon(os.path.join(icons_dir, "case-lower.svg"), text_color)
        regex_icon = load_svg_icon(os.path.join(icons_dir, "regex.svg"), text_color)
        preserve_case_icon = load_svg_icon(os.path.join(icons_dir, "case-upper.svg"), text_color)
        replace_icon = load_svg_icon(os.path.join(icons_dir, "replace.svg"), text_color)
        replace_all_icon = load_svg_icon(os.path.join(icons_dir, "replace-all.svg"), text_color)
        chevron_right_icon = load_svg_icon(os.path.join(icons_dir, "chevron-right.svg"), text_color)

        self.caseSensitiveButton.setIcon(case_sensitive_icon)
        self.caseSensitiveButton.setText("")
        self.wholeWordButton.setIcon(whole_word_icon)
        self.wholeWordButton.setText("")
        self.regexButton.setIcon(regex_icon)
        self.regexButton.setText("")
        self.preserveCaseButton.setIcon(preserve_case_icon)
        self.preserveCaseButton.setText("")

        self.replaceAllButton.setIcon(replace_all_icon)
        self.replaceAllButton.setText("")

        chevron_down_icon = load_svg_icon(os.path.join(icons_dir, "chevron-down.svg"), text_color)

        if self.toggleReplaceButton:
            self.toggleReplaceButton.setIcon(chevron_right_icon)
            self.toggleReplaceButton.setToolTip("置換の切り替え")
        if self.toggleFilterButton:
            self.toggleFilterButton.setIcon(chevron_down_icon)
            self.toggleFilterButton.setToolTip("フィルターの切り替え")

    def on_toggle_replace(self, checked: bool):
        self.replaceRow.setVisible(checked)
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        if checked:
            icon = load_svg_icon(os.path.join(icons_dir, "chevron-down.svg"), text_color)
        else:
            icon = load_svg_icon(os.path.join(icons_dir, "chevron-right.svg"), text_color)
        self.toggleReplaceButton.setIcon(icon)

    def on_toggle_filter(self, checked: bool):
        if self.projectSearchPanel:
            self.projectSearchPanel.setVisible(checked)
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        if checked:
            icon = load_svg_icon(os.path.join(icons_dir, "chevron-down.svg"), text_color)
        else:
            icon = load_svg_icon(os.path.join(icons_dir, "chevron-right.svg"), text_color)
        if self.toggleFilterButton:
            self.toggleFilterButton.setIcon(icon)

    def get_query(self) -> SearchQuery:
        return SearchQuery(
            search_text=self.searchInput.text(),
            match_case=self.caseSensitiveButton.isChecked(),
            use_regex=self.regexButton.isChecked(),
            whole_word=self.wholeWordButton.isChecked()
        )

    def _display_path(self, file_path: str, project_path: str | None) -> str:
        if project_path:
            try:
                return os.path.relpath(file_path, project_path).replace("\\", "/")
            except ValueError:
                pass
        return file_path

    def _cached_icon(self, icon_name: str):
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        cache_key = (icon_name, text_color)
        icon = self._icon_cache.get(cache_key)
        if icon is None:
            icons_dir = os.path.join(self.base_dir, "assets", "icons")
            icon = load_svg_icon(os.path.join(icons_dir, icon_name), text_color)
            self._icon_cache[cache_key] = icon
        return icon

    def _update_result_action_column_width(self):
        max_count = max((len(occs) for occs in self.current_results.values()), default=0)
        count_text = str(max_count) if max_count else ""
        text_width = self.searchResultsTree.fontMetrics().horizontalAdvance(count_text)
        column_width = text_width + self.RESULT_COUNT_COLUMN_PADDING
        column_width = max(self.RESULT_COUNT_COLUMN_MIN_WIDTH, column_width)
        column_width = min(self.RESULT_COUNT_COLUMN_MAX_WIDTH, column_width)
        self._result_action_column_width = column_width
        self.searchResultsTree.setColumnWidth(1, column_width)

    def _file_result_icon(self):
        return self._cached_icon("file.svg")

    def _set_hovered_result_index(self, index: QModelIndex, pos=None):
        if index.isValid() and index.column() != 1:
            index = index.siblingAtColumn(1)
        action = None
        if index.isValid() and pos is not None:
            option = QStyleOptionViewItem()
            option.rect = self.searchResultsTree.visualRect(index)
            action = self._search_result_delegate.action_at(option, pos)

        if index == self._hovered_result_index and action == self._hovered_result_action:
            return
        old_index = self._hovered_result_index
        self._hovered_result_action = action
        self._hovered_result_index = index
        for changed_index in (old_index, index):
            if changed_index.isValid():
                self.searchResultsTree.viewport().update(self.searchResultsTree.visualRect(changed_index))

    def _activate_result_action(self, data: dict, action: str):
        item_type = data.get("type")
        if item_type == "file":
            file_path = data.get("path")
            if not file_path:
                return
            if action == "replace":
                self.replace_file_occurrences(file_path)
            elif action == "ignore":
                self.ignore_file(file_path)
        elif item_type == "occurrence":
            occurrence = data.get("occurrence")
            if not occurrence:
                return
            if action == "replace":
                self.replace_occurrence(dict(occurrence))
            elif action == "ignore":
                self.ignore_occurrence(dict(occurrence))

    def _results_counts(self):
        file_count = len(self.current_results)
        match_count = sum(len(occs) for occs in self.current_results.values())
        return file_count, match_count

    def _update_results_status(self):
        files_found, matches_found = self._results_counts()
        self.searchStatusLabel.setText(f"{files_found} 個のファイルで {matches_found} 個の一致が見つかりました。")

    def _build_results_tree(self, project_path: str | None):
        self._hovered_result_index = QModelIndex()
        self._hovered_result_action = None
        self._update_result_action_column_width()
        self._search_results_model.rebuild(self.current_results, project_path)
        self.searchResultsTree.expandAll()
        return sum(len(occs) for occs in self.current_results.values())

    def _search_worker_path(self):
        executable = "project_search_worker.exe" if os.name == "nt" else "project_search_worker"
        return os.path.join(self.base_dir, "bin", executable)

    def _ignored_occurrences_payload(self):
        payload = []
        for file_path, line_number, pos, length, line_text in self.ignored_occurrences:
            payload.append({
                "path": file_path,
                "line_number": line_number,
                "pos": pos,
                "length": length,
                "line_text": line_text,
            })
        return payload

    def _worker_request_payload(self, request: ProjectSearchRequest):
        return {
            "project_path": request.project_path,
            "include_patterns": list(request.include_patterns),
            "exclude_patterns": list(request.exclude_patterns),
            "query": {
                "search_text": request.query.search_text,
                "match_case": request.query.match_case,
                "use_regex": request.query.use_regex,
                "whole_word": request.query.whole_word,
                "regex_pattern": request.regex_pattern,
            },
            "open_editors": [
                dict(editor)
                for editor in request.open_editors.values()
            ],
            "ignored_occurrences": request.ignored_occurrences,
        }

    def _run_worker_process(self, worker_path: str, request_path: str, response_path: str, cancel_event: threading.Event):
        process = subprocess.Popen(
            [worker_path, "--request", request_path, "--response", response_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        while process.poll() is None:
            if cancel_event.is_set():
                process.kill()
                process.communicate()
                return None
            time.sleep(0.02)

        stdout, stderr = process.communicate()
        if process.returncode != 0:
            error = stderr.strip() or stdout.strip() or f"worker exited with code {process.returncode}"
            raise RuntimeError(error)
        with open(response_path, "r", encoding="utf-8") as handle:
            return handle.read()

    def _run_worker_payload(self, payload: dict, cancel_event: threading.Event | None = None):
        request_path = None
        response_path = None
        cancel_event = cancel_event or threading.Event()
        try:
            worker_path = self._search_worker_path()
            if not os.path.exists(worker_path):
                raise FileNotFoundError(f"Rust検索workerが見つかりません: {worker_path}")

            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                json.dump(payload, handle, ensure_ascii=False)
                request_path = handle.name
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                response_path = handle.name

            stdout = self._run_worker_process(worker_path, request_path, response_path, cancel_event)
            if stdout is None or cancel_event.is_set():
                return None
            return json.loads(stdout)
        finally:
            for path in (request_path, response_path):
                if path:
                    try:
                        os.remove(path)
                    except OSError:
                        pass

    def _run_search_background(self, request: ProjectSearchRequest):
        try:
            if request.cancel_event.is_set():
                return None

            worker_result = self._run_worker_payload(self._worker_request_payload(request), request.cancel_event)
            if worker_result is None or request.cancel_event.is_set():
                return None

            current_results = {}
            for file_result in worker_result.get("files", []):
                file_path = os.path.normpath(file_result.get("path", ""))
                occurrences = file_result.get("occurrences", [])
                if file_path and occurrences:
                    for occurrence in occurrences:
                        occurrence["path"] = file_path
                    current_results[file_path] = occurrences

            files_found = len(current_results)
            matches_found = sum(len(occs) for occs in current_results.values())
            status_text = f"{files_found} 個のファイルで {matches_found} 個の一致が見つかりました。"
            return ProjectSearchResult(
                generation=request.generation,
                current_results=current_results,
                project_path=request.project_path,
                status_text=status_text,
            )
        except Exception as error:
            if not request.cancel_event.is_set():
                return ProjectSearchResult(
                    generation=request.generation,
                    current_results={},
                    project_path=request.project_path,
                    status_text=f"検索に失敗しました: {error}",
                )
        return None

    def _poll_search_result(self):
        future = self._active_search_future
        if not future or not future.done():
            return

        self.search_result_timer.stop()
        self._active_search_future = None
        try:
            result = future.result()
        except Exception as error:
            self.searchStatusLabel.setText(f"検索に失敗しました: {error}")
            return

        if result:
            self._on_search_completed(result)

    def _on_search_completed(self, result: ProjectSearchResult):
        if result.generation != self._search_generation:
            return
        if result.status_text.startswith("検索に失敗しました:"):
            self._clear_search_results(result.status_text)
            return
        self.current_results = result.current_results
        self._build_results_tree(result.project_path)
        files_found, matches_found = self._results_counts()
        self.searchStatusLabel.setText(f"{files_found} 個のファイルで {matches_found} 個の一致が見つかりました。")

    def _clear_search_results(self, message: str):
        self._hovered_result_index = QModelIndex()
        self._hovered_result_action = None
        self.current_results = {}
        self._update_result_action_column_width()
        self._search_results_model.rebuild(self.current_results, None)
        self.searchStatusLabel.setText(message)

    def _read_gitignore_patterns(self, file_path) -> list[str]:
        patterns = []
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            patterns.append(line)
            except Exception as e:
                print(f"Failed to read ignore file {file_path}: {e}")
        return patterns

    def _read_vscode_exclude_patterns(self, settings_path, key) -> list[str]:
        patterns = []
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    excludes = data.get(key, {})
                    for pattern, enabled in excludes.items():
                        if enabled:
                            patterns.append(pattern)
            except Exception as e:
                print(f"Failed to read vscode settings {settings_path}: {e}")
        return patterns

    def _read_filter_patterns(self):
        from core.settings import settings_manager
        
        include_patterns = list(p.strip() for p in self.includeInput.text().split(",") if p.strip())
        
        # 1. UIの除外入力
        exclude_patterns = list(p.strip() for p in self.excludeInput.text().split(",") if p.strip())
        
        # 2. UIの入力が無い場合は、設定からデフォルト除外パターンを読み込む
        if not exclude_patterns:
            default_ex = settings_manager.get("default_excludes", ".git, __pycache__, .vs")
            exclude_patterns = list(p.strip() for p in default_ex.split(",") if p.strip())
            
        # 3. 各種除外ファイルの読み込みとマージ
        project_path = core.api.get_project_path()
        if project_path:
            # .gitignore の除外
            if settings_manager.get("ignore_gitignore", True):
                gitignore_path = os.path.join(project_path, ".gitignore")
                exclude_patterns.extend(self._read_gitignore_patterns(gitignore_path))
                
            # .ignore の除外
            if settings_manager.get("ignore_ignore", True):
                ignore_path = os.path.join(project_path, ".ignore")
                exclude_patterns.extend(self._read_gitignore_patterns(ignore_path))
                
            # vscode settings.json
            vscode_settings_path = os.path.join(project_path, ".vscode", "settings.json")
            if os.path.exists(vscode_settings_path):
                # files.exclude
                if settings_manager.get("ignore_files_exclude", True):
                    exclude_patterns.extend(self._read_vscode_exclude_patterns(vscode_settings_path, "files.exclude"))
                # search.exclude
                if settings_manager.get("ignore_search_exclude", True):
                    exclude_patterns.extend(self._read_vscode_exclude_patterns(vscode_settings_path, "search.exclude"))
                    
        # 重複排除
        unique_excludes = []
        for p in exclude_patterns:
            if p not in unique_excludes:
                unique_excludes.append(p)
                
        return tuple(include_patterns), tuple(unique_excludes)

    def _search_signature(self, query: SearchQuery, include_patterns, exclude_patterns):
        return (
            query.search_text,
            query.match_case,
            query.use_regex,
            query.whole_word,
            tuple(include_patterns),
            tuple(exclude_patterns),
            self.searchOpenFilesCheckBox.isChecked(),
        )

    def _compile_search_pattern(self, query: SearchQuery):
        q_regex = query.to_regular_expression()
        if not q_regex.isValid():
            raise ValueError("無効な検索パターンまたは正規表現です。")
        return q_regex.pattern()

    def _collect_open_editors(self, has_open_tabs: bool):
        open_editors = {}
        if not self.searchOpenFilesCheckBox.isChecked() or not has_open_tabs:
            return open_editors

        for idx in range(self.parent_window.editorTabs.count()):
            tab_path = self.parent_window.editorTabs.tabToolTip(idx)
            widget = self.parent_window.editorTabs.widget(idx)
            if tab_path and widget and not tab_path.startswith("untitled:"):
                to_plain_text = getattr(widget, "toPlainText", None)
                if callable(to_plain_text):
                    path = os.path.normpath(tab_path)
                    open_editors[path] = {
                        "path": path,
                        "content": to_plain_text(),
                        "dirty": bool(getattr(widget, "is_dirty", False)),
                        "encoding": getattr(widget, "file_encoding", "utf-8") or "utf-8",
                    }
        return open_editors

    def _collect_open_editors_for_worker(self):
        has_open_tabs = hasattr(self.parent_window, "editorTabs") and self.parent_window.editorTabs.count() > 0
        return self._collect_open_editors(has_open_tabs)

    def _create_search_request(self, query: SearchQuery, project_path: str | None, has_open_tabs: bool):
        include_patterns, exclude_patterns = self._read_filter_patterns()
        search_signature = self._search_signature(query, include_patterns, exclude_patterns)
        if search_signature != self._last_search_signature:
            self.ignored_occurrences.clear()
            self._last_search_signature = search_signature

        cancel_event = threading.Event()
        self._search_cancel_event = cancel_event
        return ProjectSearchRequest(
            generation=self._search_generation,
            cancel_event=cancel_event,
            project_path=project_path,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            open_editors=self._collect_open_editors(has_open_tabs),
            query=query,
            regex_pattern=self._compile_search_pattern(query),
            ignored_occurrences=self._ignored_occurrences_payload(),
        )

    def _start_search_request(self, request: ProjectSearchRequest):
        self.searchStatusLabel.setText("検索中...")
        self._hovered_result_index = QModelIndex()
        self._hovered_result_action = None
        self.current_results = {}
        self._update_result_action_column_width()
        self._search_results_model.rebuild(self.current_results, request.project_path)
        self._active_search_future = self._search_dispatch_executor.submit(
            self._run_search_background,
            request,
        )
        self.search_result_timer.start()

    def on_search_clicked(self):
        self._cancel_running_search()

        query = self.get_query()
        if query.is_empty():
            self._clear_search_results("検索語を入力してください。")
            return

        project_path = core.api.get_project_path()
        # プロジェクトフォルダが開かれていないかつエディタでも何も開かれていない場合はエラーにする
        has_open_tabs = hasattr(self.parent_window, "editorTabs") and self.parent_window.editorTabs.count() > 0
        if not project_path and not has_open_tabs:
            self._clear_search_results("プロジェクトフォルダが開かれていないか、ファイルが開かれていません。")
            return

        try:
            request = self._create_search_request(query, project_path, has_open_tabs)
        except ValueError as e:
            self.searchStatusLabel.setText(str(e))
            return
        except Exception as e:
            self.searchStatusLabel.setText(f"正規表現エラー: {e}")
            return

        self._start_search_request(request)

    def _occurrence_matches(self, occurrence, target):
        return (
            occurrence.get("line_number") == target.get("line_number")
            and occurrence.get("pos") == target.get("pos")
            and occurrence.get("length") == target.get("length")
            and occurrence.get("line_text") == target.get("line_text")
        )

    def _occurrence_key(self, file_path, occurrence):
        return (
            os.path.normpath(file_path),
            occurrence.get("line_number"),
            occurrence.get("pos"),
            occurrence.get("length"),
            occurrence.get("line_text"),
        )

    def _remove_occurrence_from_results(self, target):
        file_path = target.get("path")
        if not file_path or file_path not in self.current_results:
            return False

        occurrences = self.current_results[file_path]
        for index, occurrence in enumerate(occurrences):
            if self._occurrence_matches(occurrence, target):
                del occurrences[index]
                if not occurrences:
                    self.current_results.pop(file_path, None)
                return True
        return False

    def ignore_occurrence(self, occurrence):
        file_path = occurrence.get("path")
        if file_path:
            self.ignored_occurrences.add(self._occurrence_key(file_path, occurrence))
        if not self._remove_occurrence_from_results(occurrence):
            return

        self._build_results_tree(core.api.get_project_path())
        self._update_results_status()

    def ignore_file(self, file_path: str):
        occurrences = self.current_results.get(file_path)
        if not occurrences:
            return

        for occurrence in occurrences:
            self.ignored_occurrences.add(self._occurrence_key(file_path, occurrence))
        self.current_results.pop(file_path, None)
        self._build_results_tree(core.api.get_project_path())
        self._update_results_status()

    def replace_occurrence(self, occurrence):
        file_path = occurrence.get("path")
        if not file_path:
            return

        try:
            replace_result = self._replace_with_worker({file_path: [occurrence]}, self.replaceInput.text())
        except Exception as error:
            QMessageBox.warning(self.dock_widget, "この箇所を置換", f"置換に失敗しました。\n{error}")
            return

        if replace_result.get("replaced_count", 0) <= 0:
            self.ignore_occurrence(occurrence)
            return

        self.on_search_clicked()

    def replace_file_occurrences(self, file_path: str):
        occurrences = self.current_results.get(file_path)
        if not occurrences:
            return

        try:
            replace_result = self._replace_with_worker({file_path: list(occurrences)}, self.replaceInput.text())
        except Exception as error:
            QMessageBox.warning(self.dock_widget, "このファイル内の全件を置換", f"置換に失敗しました。\n{error}")
            return

        if replace_result.get("replaced_count", 0) <= 0:
            self.ignore_file(file_path)
            return

        self.on_search_clicked()

    def on_item_double_clicked(self, index: QModelIndex):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        file_path = data.get("path")
        if not file_path or not os.path.exists(file_path):
            return

        # ファイルを開く
        self.parent_window.open_file(file_path)

        # エディタが準備完了してからカーソルを移動する
        if data.get("type") == "occurrence":
            line_number = data.get("line_number")
            def jump_to_line():
                widget = self.parent_window.editorTabs.currentWidget()
                from PySide6.QtWidgets import QPlainTextEdit
                if widget and isinstance(widget, QPlainTextEdit):
                    doc = widget.document()
                    block = doc.findBlockByLineNumber(line_number - 1)
                    if block.isValid():
                        cursor = widget.textCursor()
                        cursor.setPosition(block.position())
                        # 少しハイライトしたい場合は、その一致した位置にカーソルを合わせる
                        pos_in_line = data.get("pos", 0)
                        length = data.get("length", 0)
                        cursor.setPosition(block.position() + pos_in_line)
                        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, length)
                        widget.setTextCursor(cursor)
                        widget.ensureCursorVisible()
                        widget.setFocus()
            
            # 即座に実行し、念のため少しディレイを置いてもう一度実行
            jump_to_line()
            QTimer.singleShot(50, jump_to_line)
            QTimer.singleShot(200, jump_to_line)


    def _replace_occurrence_payload(self, occurrence):
        return {
            "line_number": occurrence.get("line_number"),
            "pos": occurrence.get("pos"),
            "length": occurrence.get("length"),
        }

    def _replace_with_worker(self, occurrences_by_path, replace_text: str):
        payload = {
            "operation": "replace",
            "project_path": core.api.get_project_path(),
            "include_patterns": [],
            "exclude_patterns": [],
            "query": {
                "search_text": "",
                "match_case": True,
                "use_regex": False,
                "whole_word": False,
                "regex_pattern": "",
            },
            "open_editors": list(self._collect_open_editors_for_worker().values()),
            "ignored_occurrences": [],
            "replace_text": replace_text,
            "targets": [
                {
                    "path": os.path.normpath(file_path),
                    "occurrences": [self._replace_occurrence_payload(occ) for occ in occurrences],
                }
                for file_path, occurrences in occurrences_by_path.items()
            ],
        }
        result = self._run_worker_payload(payload)
        if result is None:
            raise RuntimeError("置換がキャンセルされました。")
        self._apply_replace_result(result)
        failed_files = result.get("failed_files", [])
        if failed_files:
            first_failure = failed_files[0]
            raise RuntimeError(f"{first_failure.get('path')}: {first_failure.get('error')}")
        return result

    def _open_editors_for_path(self, file_path: str):
        editor_tabs = getattr(self.parent_window, "editorTabs", None)
        if not editor_tabs:
            return []

        normalized_path = os.path.normpath(file_path)
        widgets = []
        for index in range(editor_tabs.count()):
            tab_path = editor_tabs.tabToolTip(index)
            if tab_path and not tab_path.startswith("untitled:") and os.path.normpath(tab_path) == normalized_path:
                widget = editor_tabs.widget(index)
                if widget:
                    widgets.append(widget)
        return widgets

    def _sync_open_editors_after_replace(self, widgets, text: str, encoding: str, dirty: bool):
        editor_tabs = getattr(self.parent_window, "editorTabs", None)
        for widget in widgets:
            set_plain_text = getattr(widget, "setPlainText", None)
            if callable(set_plain_text):
                widget.blockSignals(True)
                try:
                    set_plain_text(text)
                finally:
                    widget.blockSignals(False)

            widget.file_encoding = encoding
            if hasattr(widget, "content"):
                widget.content = text
            if hasattr(widget, "_last_notified_content"):
                widget._last_notified_content = text
            widget.is_dirty = dirty

            if editor_tabs:
                index = editor_tabs.indexOf(widget)
                if index >= 0:
                    tab_text = editor_tabs.tabText(index)
                    if dirty and not tab_text.startswith("*"):
                        editor_tabs.setTabText(index, "*" + tab_text)
                    elif not dirty and tab_text.startswith("*"):
                        editor_tabs.setTabText(index, tab_text[1:])

    def _apply_replace_result(self, result):
        for updated in result.get("updated_open_editors", []):
            widgets = self._open_editors_for_path(updated.get("path", ""))
            self._sync_open_editors_after_replace(
                widgets,
                updated.get("new_text", ""),
                updated.get("encoding", "utf-8") or "utf-8",
                bool(updated.get("dirty", False)),
            )
        for file_path in result.get("saved_files", []):
            core.api.emit_event("file_saved", file_path)


    def on_replace_all_clicked(self):
        if not self.current_results:
            QMessageBox.information(self.dock_widget, "すべて置換", "置換対象の一致箇所がありません。先に検索を実行してください。")
            return

        replace_text = self.replaceInput.text()
        reply = QMessageBox.question(
            self.dock_widget,
            "すべて置換",
            f"検出されたすべての一致箇所を「{replace_text}」に置換して保存しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        replaced_files = 0
        replaced_count = 0
        failed_files = []
        try:
            replace_result = self._replace_with_worker(self.current_results, replace_text)
            replaced_files = replace_result.get("replaced_files", 0)
            replaced_count = replace_result.get("replaced_count", 0)
            failed_files = replace_result.get("failed_files", [])
        except Exception as error:
            QMessageBox.warning(self.dock_widget, "すべて置換", f"置換に失敗しました。\n{error}")
            return

        # 再検索
        self.on_search_clicked()
        message = f"{replaced_files} 個のファイルで {replaced_count} 個の一致箇所を置換して保存しました。"
        if failed_files:
            message += f"\n{len(failed_files)} 個のファイルで置換に失敗しました。"
        QMessageBox.information(self.dock_widget, "すべて置換", message)
