import os
import fnmatch
import re
from PySide6.QtCore import QFile, Qt, QTimer, QSize, QEvent, QObject
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QToolButton, 
    QPushButton, QTreeWidget, QTreeWidgetItem, QLabel, QMessageBox, QStyle,
    QCheckBox, QHeaderView
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QIcon, QPalette, QTextCursor, QBrush, QColor
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

    detected_encoding = autodetect_encoding(raw)
    if detected_encoding:
        try:
            return raw.decode(detected_encoding), detected_encoding
        except UnicodeDecodeError:
            pass

    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    return raw.decode("cp932", errors="replace"), "cp932"

class ProjectSearchDock(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.current_results = {} # {file_path: [SearchOccurrence, ...]}
        self.ignored_occurrences = set()
        self._last_search_signature = None
        self._result_item_action_buttons = {}
        self._result_item_count_badges = {}
        
        # リアルタイム（ライブ）検索用デバウンスタイマー
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300) # 300ms後に検索を実行
        self.search_timer.timeout.connect(self.on_search_clicked)
        
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
        self.searchResultsTree = self.dock_widget.findChild(QTreeWidget, "searchResultsTree")
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
        self.searchResultsTree.setColumnCount(2)
        self.searchResultsTree.setHeaderHidden(True)
        self.searchResultsTree.setRootIsDecorated(True)
        self.searchResultsTree.setItemsExpandable(True)
        self.searchResultsTree.setUniformRowHeights(True)
        self.searchResultsTree.setIndentation(16)
        self.searchResultsTree.setMouseTracking(True)
        self.searchResultsTree.viewport().setMouseTracking(True)
        self.searchResultsTree.viewport().installEventFilter(self)
        header = self.searchResultsTree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        
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
            self.searchResultsTree.itemDoubleClicked.connect(self.on_item_double_clicked)
            self.searchResultsTree.itemActivated.connect(self.on_item_double_clicked)
            self.searchResultsTree.itemEntered.connect(self._on_result_item_entered)
        if self.replaceAllButton:
            self.replaceAllButton.clicked.connect(self.on_replace_all_clicked)

        if self.toggleReplaceButton:
            self.toggleReplaceButton.toggled.connect(self.on_toggle_replace)
        if self.toggleFilterButton:
            self.toggleFilterButton.toggled.connect(self.on_toggle_filter)

    def trigger_live_search(self):
        if hasattr(self, "search_timer"):
            self.search_timer.start()

    def trigger_instant_search(self):
        if hasattr(self, "search_timer"):
            self.search_timer.stop()
        self.on_search_clicked()

    def _cleanup_event_filters(self, *args):
        if hasattr(self, "search_timer"):
            self.search_timer.stop()
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
                item = self.searchResultsTree.itemAt(event.position().toPoint())
                self._set_hovered_result_item(item)
            elif event.type() == QEvent.Type.Leave:
                self._set_hovered_result_item(None)

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

    def _create_count_badge(self, count: int) -> QLabel:
        badge = QLabel(str(count), self.searchResultsTree)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setMinimumWidth(24)
        badge.setFixedHeight(22)
        badge.setStyleSheet("""
            QLabel {
                background-color: palette(mid);
                color: palette(bright-text);
                border-radius: 11px;
                padding: 0 7px;
            }
        """)
        return badge

    def _register_result_action_button(self, item: QTreeWidgetItem, button: QToolButton):
        button.setVisible(False)
        self._result_item_action_buttons.setdefault(id(item), []).append(button)

    def _register_result_count_badge(self, item: QTreeWidgetItem, badge: QLabel):
        self._result_item_count_badges[id(item)] = badge

    def _set_hovered_result_item(self, item):
        hovered_id = id(item) if item else None
        for item_id, buttons in list(self._result_item_action_buttons.items()):
            visible = item_id == hovered_id
            for button in buttons:
                try:
                    button.setVisible(visible)
                except RuntimeError:
                    pass
        for item_id, badge in list(self._result_item_count_badges.items()):
            try:
                badge.setVisible(item_id != hovered_id)
            except RuntimeError:
                pass

    def _on_result_item_entered(self, item, column):
        self._set_hovered_result_item(item)

    def _create_file_actions(self, item: QTreeWidgetItem, file_path: str, count: int):
        container = QWidget(self.searchResultsTree)
        container.setMinimumWidth(76)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")

        count_badge = self._create_count_badge(count)
        self._register_result_count_badge(item, count_badge)
        layout.addWidget(count_badge)

        replace_button = QToolButton(container)
        replace_button.setIcon(load_svg_icon(os.path.join(icons_dir, "replace-all.svg"), text_color))
        replace_button.setToolTip("このファイル内の全件を置換")
        replace_button.setAutoRaise(True)
        replace_button.setFixedSize(22, 22)
        replace_button.clicked.connect(lambda checked=False, path=file_path: self.replace_file_occurrences(path))
        self._register_result_action_button(item, replace_button)

        ignore_button = QToolButton(container)
        ignore_button.setIcon(load_svg_icon(os.path.join(icons_dir, "close.svg"), text_color))
        ignore_button.setToolTip("このファイルを無視")
        ignore_button.setAutoRaise(True)
        ignore_button.setFixedSize(22, 22)
        ignore_button.clicked.connect(lambda checked=False, path=file_path: self.ignore_file(path))
        self._register_result_action_button(item, ignore_button)

        layout.addWidget(replace_button)
        layout.addWidget(ignore_button)
        return container

    def _create_occurrence_actions(self, item: QTreeWidgetItem, occurrence):
        container = QWidget(self.searchResultsTree)
        container.setMinimumWidth(48)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")

        replace_button = QToolButton(container)
        replace_button.setIcon(load_svg_icon(os.path.join(icons_dir, "replace.svg"), text_color))
        replace_button.setToolTip("この箇所を置換")
        replace_button.setAutoRaise(True)
        replace_button.setFixedSize(22, 22)
        replace_button.clicked.connect(lambda checked=False, occ=dict(occurrence): self.replace_occurrence(occ))
        self._register_result_action_button(item, replace_button)

        ignore_button = QToolButton(container)
        ignore_button.setIcon(load_svg_icon(os.path.join(icons_dir, "close.svg"), text_color))
        ignore_button.setToolTip("この箇所を無視")
        ignore_button.setAutoRaise(True)
        ignore_button.setFixedSize(22, 22)
        ignore_button.clicked.connect(lambda checked=False, occ=dict(occurrence): self.ignore_occurrence(occ))
        self._register_result_action_button(item, ignore_button)

        layout.addWidget(replace_button)
        layout.addWidget(ignore_button)
        return container

    def _results_counts(self):
        file_count = len(self.current_results)
        match_count = sum(len(occs) for occs in self.current_results.values())
        return file_count, match_count

    def _update_results_status(self):
        files_found, matches_found = self._results_counts()
        self.searchStatusLabel.setText(f"{files_found} 個のファイルで {matches_found} 個の一致が見つかりました。")

    def _build_results_tree(self, project_path: str | None):
        self.searchResultsTree.clear()
        self._result_item_action_buttons = {}
        self._result_item_count_badges = {}
        text_color = self.parent_window.palette().color(QPalette.ColorRole.WindowText).name()
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        icon_file = load_svg_icon(os.path.join(icons_dir, "file.svg"), text_color)

        self.searchResultsTree.setUpdatesEnabled(False)
        try:
            for file_path in sorted(self.current_results.keys(), key=lambda path: self._display_path(path, project_path).lower()):
                occs = self.current_results[file_path]
                display_path = self._display_path(file_path, project_path)
                file_item = QTreeWidgetItem(self.searchResultsTree)
                file_item.setText(0, display_path)
                file_item.setText(1, str(len(occs)))
                file_item.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                file_item.setToolTip(0, file_path)
                file_item.setIcon(0, icon_file)
                file_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "file", "path": file_path})
                file_item.setExpanded(True)
                self.searchResultsTree.setItemWidget(file_item, 1, self._create_file_actions(file_item, file_path, len(occs)))

                for occ in occs:
                    child_item = QTreeWidgetItem(file_item)
                    occurrence = dict(occ)
                    occurrence["path"] = file_path
                    trimmed = occ["line_text"].strip()
                    child_item.setText(0, f"{occ['line_number']}: {trimmed}")
                    child_item.setToolTip(0, occ["line_text"])
                    child_item.setData(0, Qt.ItemDataRole.UserRole, {
                        "type": "occurrence",
                        "path": file_path,
                        "line_number": occ["line_number"],
                        "line_text": occ["line_text"],
                        "pos": occ["pos"],
                        "length": occ["length"]
                    })
                    self.searchResultsTree.setItemWidget(child_item, 1, self._create_occurrence_actions(child_item, occurrence))
        finally:
            self.searchResultsTree.setUpdatesEnabled(True)

    def on_search_clicked(self):
        query = self.get_query()
        if query.is_empty():
            self.searchResultsTree.clear()
            self.searchStatusLabel.setText("検索語を入力してください。")
            return

        project_path = core.api.get_project_path()
        # プロジェクトフォルダが開かれていないかつエディタでも何も開かれていない場合はエラーにする
        has_open_tabs = hasattr(self.parent_window, "editorTabs") and self.parent_window.editorTabs.count() > 0
        if not project_path and not has_open_tabs:
            self.searchResultsTree.clear()
            self.searchStatusLabel.setText("プロジェクトフォルダが開かれていないか、ファイルが開かれていません。")
            return

        self.searchStatusLabel.setText("検索中...")
        self.searchResultsTree.clear()
        self.current_results = {}

        # フィルタパターンのパース
        include_patterns = [p.strip() for p in self.includeInput.text().split(",") if p.strip()]
        exclude_patterns = [p.strip() for p in self.excludeInput.text().split(",") if p.strip()]
        # 除外の既定値
        if not exclude_patterns:
            exclude_patterns = [".git", "__pycache__", "build", ".vs"]

        search_signature = (
            query.search_text,
            query.match_case,
            query.use_regex,
            query.whole_word,
            tuple(include_patterns),
            tuple(exclude_patterns),
            self.searchOpenFilesCheckBox.isChecked(),
        )
        if search_signature != self._last_search_signature:
            self.ignored_occurrences.clear()
            self._last_search_signature = search_signature

        # 正規表現パターンの準備
        try:
            q_regex = query.to_regular_expression()
            if not q_regex.isValid():
                self.searchStatusLabel.setText("無効な検索パターンまたは正規表現です。")
                return
            pattern_str = q_regex.pattern()
            flags = 0
            if not query.match_case:
                flags |= re.IGNORECASE
            re_pattern = re.compile(pattern_str, flags)
        except Exception as e:
            self.searchStatusLabel.setText(f"正規表現エラー: {e}")
            return

        # 1. 開いているエディタ（未保存のメモリ上コンテンツ）の収集
        open_editors = {} # {正規化パス: テキスト}
        if self.searchOpenFilesCheckBox.isChecked() and has_open_tabs:
            from PySide6.QtWidgets import QPlainTextEdit
            for idx in range(self.parent_window.editorTabs.count()):
                tab_path = self.parent_window.editorTabs.tabToolTip(idx)
                widget = self.parent_window.editorTabs.widget(idx)
                if tab_path and widget and not tab_path.startswith("untitled:"):
                    to_plain_text = getattr(widget, "toPlainText", None)
                    if callable(to_plain_text):
                        open_editors[os.path.normpath(tab_path)] = to_plain_text()

        # 2. 検索対象ファイルのパス候補リストを収集
        target_files = set() # {正規化パス}

        # プロジェクト内ファイルの追加
        if project_path:
            for root, dirs, files in os.walk(project_path):
                # 除外ディレクトリのフィルタリング
                dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, pat) for pat in exclude_patterns)]
                for file in files:
                    file_path = os.path.join(root, file)
                    target_files.add(os.path.normpath(file_path))

        # 開いているファイルのパスを追加（プロジェクト外でも対象化）
        for open_path in open_editors.keys():
            target_files.add(open_path)

        # 3. 各ファイルの検索処理
        matches_found = 0
        files_found = 0

        for file_path in sorted(target_files):
            file_name = os.path.basename(file_path)

            # 除外ファイルのチェック
            if any(fnmatch.fnmatch(file_name, pat) for pat in exclude_patterns):
                continue

            # 含めるファイルのチェック
            if include_patterns:
                if not any(fnmatch.fnmatch(file_name, pat) for pat in include_patterns):
                    continue

            # テキストコンテンツの取得（メモリ上にあれば優先し、無ければディスクから読む）
            content = None
            encoding = "utf-8"
            if file_path in open_editors:
                content = open_editors[file_path]
            else:
                try:
                    with open(file_path, "rb") as f:
                        raw = f.read(1024 * 1024 * 5) # 最大5MBまで読み込む
                    
                    # バイナリチェック（簡易）
                    if b"\x00" in raw:
                        continue

                    content, encoding = detect_text_encoding(raw)
                except Exception:
                    continue

            if content is None:
                continue

            try:
                lines = content.splitlines()
                file_occurrences = []
                for line_idx, line in enumerate(lines):
                    for match in re_pattern.finditer(line):
                        pos = match.start()
                        length = match.end() - pos
                        occurrence = {
                            "path": file_path,
                            "line_number": line_idx + 1,
                            "line_text": line,
                            "pos": pos,
                            "length": length,
                            "encoding": encoding
                        }
                        if self._occurrence_key(file_path, occurrence) in self.ignored_occurrences:
                            continue
                        file_occurrences.append(occurrence)
                        matches_found += 1
                
                if file_occurrences:
                    self.current_results[file_path] = file_occurrences
                    files_found += 1
            except Exception as e:
                print(f"Error searching in {file_path}: {e}")

        self._build_results_tree(project_path)
        self._update_results_status()

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

    def on_item_double_clicked(self, item, column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
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
