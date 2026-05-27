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
    QCheckBox, QHeaderView, QStyledItemDelegate
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPalette, QTextCursor
from core.search_engine import SearchQuery
from core.utils import load_svg_icon
import core.api

def autodetect_encoding(raw):
    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best and best.encoding:
            return best.encoding
    except Exception:
        pass
    return None

def detect_text_encoding(raw):
    bom_candidates = [
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ]
    for prefix, encoding in bom_candidates:
        if raw.startswith(prefix):
            try:
                return raw.decode(encoding), encoding
            except Exception:
                pass

    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    detected_encoding = autodetect_encoding(raw)
    if detected_encoding:
        try:
            return raw.decode(detected_encoding), detected_encoding
        except UnicodeDecodeError:
            pass

    return raw.decode("cp932", errors="replace"), "cp932"


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
        spacing = 2
        total_width = size * 2 + spacing
        left = option.rect.left() + max(0, (option.rect.width() - total_width) // 2)
        top = option.rect.top() + max(0, (option.rect.height() - size) // 2)
        replace_rect = QRect(left, top, size, size)
        ignore_rect = QRect(left + size + spacing, top, size, size)
        return replace_rect, ignore_rect

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
        replace_icon.paint(painter, replace_rect, Qt.AlignmentFlag.AlignCenter)
        ignore_icon.paint(painter, ignore_rect, Qt.AlignmentFlag.AlignCenter)

    def editorEvent(self, event, model, option, index):
        if event.type() != QEvent.Type.MouseButtonRelease or index.column() != 1:
            return super().editorEvent(event, model, option, index)
        data = index.data(Qt.ItemDataRole.UserRole) or {}
        if not data:
            return False
        replace_rect, ignore_rect = self._action_rects(option)
        pos = event.position().toPoint()
        if replace_rect.contains(pos):
            self.owner._activate_result_action(data, "replace")
            return True
        if ignore_rect.contains(pos):
            self.owner._activate_result_action(data, "ignore")
            return True
        return False


class ProjectSearchDock(QObject):
    RESULT_COUNT_COLUMN_MIN_WIDTH = 28
    RESULT_COUNT_COLUMN_MAX_WIDTH = 72
    RESULT_COUNT_COLUMN_PADDING = 14
    RESULT_ACTION_BUTTON_SIZE = 14

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.current_results = {} # {file_path: [SearchOccurrence, ...]}
        self.ignored_occurrences = set()
        self._last_search_signature = None
        self._hovered_result_index = QModelIndex()
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
                    self._set_hovered_result_index(index)
            elif event.type() == QEvent.Type.Leave:
                self._set_hovered_result_index(QModelIndex())

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

    def _set_hovered_result_index(self, index: QModelIndex):
        if index.isValid() and index.column() != 1:
            index = index.siblingAtColumn(1)
        if index == self._hovered_result_index:
            return
        old_index = self._hovered_result_index
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
                {"path": path, "content": content}
                for path, content in request.open_editors.items()
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

    def _run_search_background(self, request: ProjectSearchRequest):
        request_path = None
        response_path = None
        try:
            if request.cancel_event.is_set():
                return None

            worker_path = self._search_worker_path()
            if not os.path.exists(worker_path):
                raise FileNotFoundError(f"Rust検索workerが見つかりません: {worker_path}")

            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                json.dump(self._worker_request_payload(request), handle, ensure_ascii=False)
                request_path = handle.name
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                response_path = handle.name

            stdout = self._run_worker_process(worker_path, request_path, response_path, request.cancel_event)
            if stdout is None or request.cancel_event.is_set():
                return None

            worker_result = json.loads(stdout)
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
        finally:
            if request_path:
                try:
                    os.remove(request_path)
                except OSError:
                    pass
            if response_path:
                try:
                    os.remove(response_path)
                except OSError:
                    pass
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
        self.current_results = {}
        self._update_result_action_column_width()
        self._search_results_model.rebuild(self.current_results, None)
        self.searchStatusLabel.setText(message)

    def _read_filter_patterns(self):
        include_patterns = tuple(p.strip() for p in self.includeInput.text().split(",") if p.strip())
        exclude_patterns = tuple(p.strip() for p in self.excludeInput.text().split(",") if p.strip())
        if not exclude_patterns:
            exclude_patterns = (".git", "__pycache__", "build", ".vs")
        return include_patterns, exclude_patterns

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
                    open_editors[os.path.normpath(tab_path)] = to_plain_text()
        return open_editors

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
            replaced_count = self._replace_file_without_opening_tab(file_path, [occurrence], self.replaceInput.text())
        except Exception as error:
            QMessageBox.warning(self.dock_widget, "この箇所を置換", f"置換に失敗しました。\n{error}")
            return

        if replaced_count <= 0:
            self.ignore_occurrence(occurrence)
            return

        self.on_search_clicked()

    def replace_file_occurrences(self, file_path: str):
        occurrences = self.current_results.get(file_path)
        if not occurrences:
            return

        try:
            replaced_count = self._replace_file_without_opening_tab(file_path, list(occurrences), self.replaceInput.text())
        except Exception as error:
            QMessageBox.warning(self.dock_widget, "このファイル内の全件を置換", f"置換に失敗しました。\n{error}")
            return

        if replaced_count <= 0:
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

    def _text_and_encoding_for_replace(self, file_path: str):
        open_widgets = self._open_editors_for_path(file_path)
        for widget in open_widgets:
            to_plain_text = getattr(widget, "toPlainText", None)
            if callable(to_plain_text):
                return to_plain_text(), getattr(widget, "file_encoding", "utf-8") or "utf-8", open_widgets

        with open(file_path, "rb") as handle:
            raw = handle.read()
        text, encoding = detect_text_encoding(raw)
        return text, encoding, open_widgets

    def _split_line_ending(self, line: str):
        if line.endswith("\r\n"):
            return line[:-2], "\r\n"
        if line.endswith("\n"):
            return line[:-1], "\n"
        if line.endswith("\r"):
            return line[:-1], "\r"
        return line, ""

    def _replace_occurrences_in_text(self, text: str, occurrences, replace_text: str):
        lines = text.splitlines(keepends=True)
        occurrences_by_line = {}
        for occ in occurrences:
            occurrences_by_line.setdefault(occ["line_number"], []).append(occ)

        replaced_count = 0
        for line_number, line_occurrences in occurrences_by_line.items():
            line_index = line_number - 1
            if line_index < 0 or line_index >= len(lines):
                continue

            body, line_ending = self._split_line_ending(lines[line_index])
            for occ in sorted(line_occurrences, key=lambda item: item["pos"], reverse=True):
                pos = occ["pos"]
                length = occ["length"]
                if pos < 0 or pos > len(body):
                    continue
                body = body[:pos] + replace_text + body[pos + length:]
                replaced_count += 1
            lines[line_index] = body + line_ending

        return "".join(lines), replaced_count

    def _sync_open_editors_after_replace(self, widgets, text: str, encoding: str):
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
            widget.is_dirty = False

            if editor_tabs:
                index = editor_tabs.indexOf(widget)
                if index >= 0:
                    tab_text = editor_tabs.tabText(index)
                    if tab_text.startswith("*"):
                        editor_tabs.setTabText(index, tab_text[1:])

    def _replace_file_without_opening_tab(self, file_path: str, occurrences, replace_text: str):
        text, encoding, open_widgets = self._text_and_encoding_for_replace(file_path)
        replaced_text, replaced_count = self._replace_occurrences_in_text(text, occurrences, replace_text)
        if replaced_count == 0:
            return 0

        with open(file_path, "w", encoding=encoding, newline="") as handle:
            handle.write(replaced_text)

        core.api.emit_event("file_saved", file_path)
        self._sync_open_editors_after_replace(open_widgets, replaced_text, encoding)
        return replaced_count


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
        for file_path, occs in self.current_results.items():
            try:
                file_replaced_count = self._replace_file_without_opening_tab(file_path, occs, replace_text)
            except Exception as error:
                failed_files.append((file_path, error))
                continue

            if file_replaced_count > 0:
                replaced_files += 1
                replaced_count += file_replaced_count

        # 再検索
        self.on_search_clicked()
        message = f"{replaced_files} 個のファイルで {replaced_count} 個の一致箇所を置換して保存しました。"
        if failed_files:
            message += f"\n{len(failed_files)} 個のファイルで置換に失敗しました。"
        QMessageBox.information(self.dock_widget, "すべて置換", message)
