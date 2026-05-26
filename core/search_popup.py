import os
from PySide6.QtCore import QFile, QEvent, Signal, Qt, QPoint, QByteArray, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QToolButton, QLabel
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QMouseEvent, QIcon, QPixmap, QPalette

from core.search_engine import SearchQuery
from core.utils import load_svg_icon

class SearchPopUpWidget(QWidget):
    """エディタ上部にフロート表示する、VS Code風の検索・置換ポップアップウィジェット"""
    
    # 外部（エディタ連携など）へ通知するシグナル定義
    query_changed = Signal(SearchQuery)         # 検索キーワードまたはオプションが変更された
    find_next = Signal()                        # 「次へ」が押された
    find_previous = Signal()                    # 「前へ」が押された
    replace_requested = Signal(str, str)        # 1箇所置換が要求された（検索語, 置換語）
    replace_all_requested = Signal(str, str)    # すべて置換が要求された（検索語, 置換語）
    close_requested = Signal()                  # ポップアップが閉じられた

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.manually_moved = False             # ユーザーによってドラッグ移動されたかフラグ
        self.drag_position = QPoint()           # ドラッグ位置
        self.custom_width = 420                 # ユーザーが指定・調整したカスタム幅
        self.resize_mode = 0                    # 0: なし, 1: 左リサイズ, 2: 右リサイズ
        self.drag_start_width = 420
        self.drag_start_pos = QPoint()
        self.drag_start_x = 0
        self._setup_ui()
        self._setup_connections()

    def _setup_ui(self):
        """UIの動的ロードと共通入力欄の差し込み処理"""
        loader = QUiLoader()
        
        # 1. メインポップアップUIのロード
        popup_ui_path = os.path.join(self.base_dir, "ui", "widgets", "search_popup.ui")
        popup_file = QFile(popup_ui_path)
        if popup_file.open(QFile.OpenModeFlag.ReadOnly):
            self.ui = loader.load(popup_file, self)
            popup_file.close()
            
            # ポップアップ全体のスタイルシート（透過を防ぎ、パレットカラーの背景と枠線を定義）
            self.ui.setStyleSheet("""
                #SearchPopUp {
                    background-color: palette(window);  /* システムテーマのウィンドウ背景色 */
                    border: 1px solid palette(dark);    /* システムテーマの境界枠線色 */
                    border-radius: 6px;                /* 角丸 */
                }
                QToolButton#toggleReplaceButton:checked {
                    background-color: palette(button);
                    border: 1px solid palette(dark);
                }
            """)
            
            # 美しい角丸切り抜き（四隅の不要な余白を透明化）のための属性設定
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        else:
            raise FileNotFoundError(f"Cannot open UI file: {popup_ui_path}")

        # メインレイアウトの適用
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.ui)

        # 2. プレースホルダーの取得
        self.searchFieldContainer = self.ui.findChild(QWidget, "searchFieldContainer")
        self.replaceFieldContainer = self.ui.findChild(QWidget, "replaceFieldContainer")
        self.replaceButtonsContainer = self.ui.findChild(QWidget, "replaceButtonsContainer")

        # 3. 共通検索フィールドUIのロードと埋め込み
        search_field_ui_path = os.path.join(self.base_dir, "ui", "widgets", "search_input_field.ui")
        search_field_file = QFile(search_field_ui_path)
        if search_field_file.open(QFile.OpenModeFlag.ReadOnly):
            self.search_field = loader.load(search_field_file, self.searchFieldContainer)
            search_field_file.close()
            
            # コンテナにレイアウトを作成し、ロードしたウィジェットを追加
            layout = QHBoxLayout(self.searchFieldContainer)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.search_field)
        else:
            raise FileNotFoundError(f"Cannot open UI file: {search_field_ui_path}")

        # 4. 共通置換フィールドUIのロードと埋め込み
        replace_field_ui_path = os.path.join(self.base_dir, "ui", "widgets", "replace_input_field.ui")
        replace_field_file = QFile(replace_field_ui_path)
        if replace_field_file.open(QFile.OpenModeFlag.ReadOnly):
            self.replace_field = loader.load(replace_field_file, self.replaceFieldContainer)
            replace_field_file.close()
            
            # コンテナにレイアウトを作成し、ロードしたウィジェットを追加
            layout = QHBoxLayout(self.replaceFieldContainer)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.replace_field)
        else:
            raise FileNotFoundError(f"Cannot open UI file: {replace_field_ui_path}")

        # 5. UI内ウィジェットのバインド
        # 検索入力関連
        self.searchInput = self.search_field.findChild(QLineEdit, "searchInput")
        self.caseSensitiveButton = self.search_field.findChild(QToolButton, "caseSensitiveButton")
        self.wholeWordButton = self.search_field.findChild(QToolButton, "wholeWordButton")
        self.regexButton = self.search_field.findChild(QToolButton, "regexButton")
        
        # 置換入力関連
        self.replaceInput = self.replace_field.findChild(QLineEdit, "replaceInput")
        self.preserveCaseButton = self.replace_field.findChild(QToolButton, "preserveCaseButton")

        # 置換操作ボタン
        self.toggleReplaceButton = self.ui.findChild(QToolButton, "toggleReplaceButton")
        self.replaceButton = self.ui.findChild(QToolButton, "replaceButton")
        self.replaceAllButton = self.ui.findChild(QToolButton, "replaceAllButton")

        # コントロール関連
        self.matchCountLabel = self.ui.findChild(QLabel, "matchCountLabel")
        self.prevButton = self.ui.findChild(QToolButton, "prevButton")
        self.nextButton = self.ui.findChild(QToolButton, "nextButton")
        self.filterButton = self.ui.findChild(QToolButton, "filterButton")
        self.closeButton = self.ui.findChild(QToolButton, "closeButton")

        # 6. 初期表示状態の設定
        # 置換行は最初は非表示にする（検索のみの状態）
        self.replaceFieldContainer.setVisible(False)
        self.replaceButtonsContainer.setVisible(False)
        
        self.toggleReplaceButton.setChecked(False)
        self._update_icons()
        
        # アクティブ枠線QSS連動用のイベントフィルターの適用
        self.searchInput.installEventFilter(self)
        self.replaceInput.installEventFilter(self)
        self.ui.installEventFilter(self) # ポップアップ背景のドラッグ移動検知用
        
        # マウスドラッグリサイズ検知用のマウス追従設定
        self.setMouseTracking(True)
        self.ui.setMouseTracking(True)

        # 7. サイズとレイアウトの調整（フロート時のサイズ崩れを完全に防ぐ）
        self._update_widget_size()

    def _setup_connections(self):
        """各種シグナルとスロットの連携"""
        # 置換表示の切り替え
        self.toggleReplaceButton.toggled.connect(self._on_toggle_replace)

        # 検索キーワード・オプション変更時のイベント
        self.searchInput.textChanged.connect(self._on_query_changed)
        self.caseSensitiveButton.toggled.connect(self._on_query_changed)
        self.wholeWordButton.toggled.connect(self._on_query_changed)
        self.regexButton.toggled.connect(self._on_query_changed)

        # ナビゲーション
        self.prevButton.clicked.connect(self.find_previous.emit)
        self.nextButton.clicked.connect(self.find_next.emit)
        
        # QLineEditのEnterキーによるナビゲーション
        self.searchInput.returnPressed.connect(self.find_next.emit)

        # 置換
        self.replaceButton.clicked.connect(self._on_replace_clicked)
        self.replaceAllButton.clicked.connect(self._on_replace_all_clicked)

        # 閉じる
        self.closeButton.clicked.connect(self.close_requested.emit)

    def _update_widget_size(self):
        """現在のレイアウト（検索のみ・置換あり）に合わせて、Qtの動的推奨サイズ(sizeHint)に自動フィットさせます"""
        # 幅を明示的に確保 (フロート時に潰れるのを防ぐ)
        self.setMinimumWidth(420)
        
        # 一旦固定高さを解除し、レイアウトに推奨サイズを再計算させる
        self.setMaximumHeight(16777215) # QWIDGETSIZE_MAX
        self.setMinimumHeight(0)
        for widget in (self.replaceFieldContainer, self.replaceButtonsContainer, self.ui, self):
            widget.updateGeometry()
        for layout in (self.ui.layout(), self.layout()):
            layout.invalidate()
            layout.activate()
        
        # Qtが現在のDPIやフォントから計算した完璧な「推奨の高さ」を取得して動的に固定
        recommended_height = self.ui.sizeHint().height()
        self.setFixedHeight(recommended_height)
        
        self.resize(self.custom_width, recommended_height)

    def _on_toggle_replace(self, checked: bool):
        """置換欄の表示切り替えと矢印の向きの更新"""
        self.replaceFieldContainer.setVisible(checked)
        self.replaceButtonsContainer.setVisible(checked)
        self.toggleReplaceButton.setIcon(self.chevron_down_icon if checked else self.chevron_right_icon)
        
        # 高さとサイズを動的更新
        self._update_widget_size()
        QTimer.singleShot(0, self._update_widget_size)
        
        if checked:
            self.replaceInput.setFocus()
            self.replaceInput.selectAll()
        else:
            self.searchInput.setFocus()

    def _on_query_changed(self):
        """検索条件の変更を外部に通知"""
        self.query_changed.emit(self.get_query())

    def _on_replace_clicked(self):
        """1箇所置換シグナルを発火"""
        self.replace_requested.emit(self.searchInput.text(), self.replaceInput.text())

    def _on_replace_all_clicked(self):
        """すべて置換シグナルを発火"""
        self.replace_all_requested.emit(self.searchInput.text(), self.replaceInput.text())

    def get_query(self) -> SearchQuery:
        """現在のUI入力値から SearchQuery インスタンスを構築します"""
        return SearchQuery(
            search_text=self.searchInput.text(),
            match_case=self.caseSensitiveButton.isChecked(),
            use_regex=self.regexButton.isChecked(),
            whole_word=self.wholeWordButton.isChecked()
        )

    def set_match_count(self, current: int, total: int):
        """検索一致件数の表示を更新します"""
        if total == 0:
            self.matchCountLabel.setText("結果はありません。")
        else:
            self.matchCountLabel.setText(f"{current} / {total}")

    def show_popup(self):
        """ポップアップを表示し、フォーカスを検索入力にセットします"""
        self.show()
        self.searchInput.setFocus()
        self.searchInput.selectAll()
        self._on_query_changed() # 表示時に初期検索を実行

    def hide_popup(self):
        """ポップアップを非表示にします"""
        self.hide()

    def mousePressEvent(self, event: QMouseEvent):
        """左マウスクリック時にドラッグ用の基準座標を記録します"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        """左マウスドラッグ時に親ウィンドウ内での位置を更新し、手動移動フラグをオンにします"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            self.manually_moved = True # ユーザー自身がドラッグ移動したため自動追従を停止
            event.accept()

    def eventFilter(self, watched, event):
        """フォーカスイン/アウトイベントおよびドラッグ移動イベントを処理するイベントフィルター"""
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

        # ポップアップ背景(self.ui)のドラッグ移動および幅リサイズ処理
        elif watched == self.ui:
            border = 6
            if event.type() == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    local_x = event.position().x()
                    if local_x < border:
                        self.resize_mode = 1 # 左リサイズ
                        self.drag_start_width = self.width()
                        self.drag_start_pos = event.globalPosition().toPoint()
                        self.drag_start_x = self.x()
                    elif local_x > self.width() - border:
                        self.resize_mode = 2 # 右リサイズ
                        self.drag_start_width = self.width()
                        self.drag_start_pos = event.globalPosition().toPoint()
                    else:
                        self.resize_mode = 0 # 通常移動
                        self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    event.accept()
                    return True
            elif event.type() == QEvent.Type.MouseMove:
                if event.buttons() == Qt.MouseButton.LeftButton:
                    if self.resize_mode == 1: # 左リサイズ
                        delta_x = event.globalPosition().toPoint().x() - self.drag_start_pos.x()
                        new_width = self.drag_start_width - delta_x
                        if new_width >= 420:
                            self.custom_width = new_width
                            self.move(self.drag_start_x + delta_x, self.y())
                            self._update_widget_size()
                            self.manually_moved = True
                    elif self.resize_mode == 2: # 右リサイズ
                        delta_x = event.globalPosition().toPoint().x() - self.drag_start_pos.x()
                        new_width = self.drag_start_width + delta_x
                        if new_width >= 420:
                            self.custom_width = new_width
                            self._update_widget_size()
                            self.manually_moved = True
                    else: # 通常移動
                        self.move(event.globalPosition().toPoint() - self.drag_position)
                        self.manually_moved = True
                    event.accept()
                    return True
                else:
                    # ドラッグしていないときのカーソル形状変更
                    local_x = event.position().x()
                    if local_x < border or local_x > self.width() - border:
                        self.setCursor(Qt.CursorShape.SizeHorCursor)
                    else:
                        self.setCursor(Qt.CursorShape.ArrowCursor)
            elif event.type() == QEvent.Type.MouseButtonRelease:
                self.resize_mode = 0
                self.setCursor(Qt.CursorShape.ArrowCursor)
            elif event.type() == QEvent.Type.Leave:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        return False

    def _update_icons(self):
        """現在のパレット色（テーマのテキストカラー）に基づいて、すべてのSVGアイコンを着色して適用します"""
        icons_dir = os.path.join(self.base_dir, "assets", "icons")
        color_hex = self.palette().color(QPalette.ColorRole.WindowText).name()
        
        # アイコンをロード (QIcon)
        self.chevron_down_icon = load_svg_icon(os.path.join(icons_dir, "chevron-down.svg"), color_hex)
        self.chevron_right_icon = load_svg_icon(os.path.join(icons_dir, "chevron-right.svg"), color_hex)
        close_icon = load_svg_icon(os.path.join(icons_dir, "close.svg"), color_hex)
        prev_icon = load_svg_icon(os.path.join(icons_dir, "move-up.svg"), color_hex)
        next_icon = load_svg_icon(os.path.join(icons_dir, "move-down.svg"), color_hex)
        filter_icon = load_svg_icon(os.path.join(icons_dir, "highlighter.svg"), color_hex)
        case_sensitive_icon = load_svg_icon(os.path.join(icons_dir, "case-sensitive.svg"), color_hex)
        whole_word_icon = load_svg_icon(os.path.join(icons_dir, "case-lower.svg"), color_hex)
        regex_icon = load_svg_icon(os.path.join(icons_dir, "regex.svg"), color_hex)
        preserve_case_icon = load_svg_icon(os.path.join(icons_dir, "case-upper.svg"), color_hex)
        replace_icon = load_svg_icon(os.path.join(icons_dir, "replace.svg"), color_hex)
        replace_all_icon = load_svg_icon(os.path.join(icons_dir, "replace-all.svg"), color_hex)
        
        # ボタンへの適用
        self.toggleReplaceButton.setIcon(self.chevron_down_icon if self.toggleReplaceButton.isChecked() else self.chevron_right_icon)
        self.toggleReplaceButton.setText("")
        
        self.closeButton.setIcon(close_icon)
        self.closeButton.setText("")

        self.prevButton.setIcon(prev_icon)
        self.prevButton.setText("")

        self.nextButton.setIcon(next_icon)
        self.nextButton.setText("")

        self.filterButton.setIcon(filter_icon)
        self.filterButton.setText("")

        self.caseSensitiveButton.setIcon(case_sensitive_icon)
        self.caseSensitiveButton.setText("")

        self.wholeWordButton.setIcon(whole_word_icon)
        self.wholeWordButton.setText("")

        self.regexButton.setIcon(regex_icon)
        self.regexButton.setText("")

        self.preserveCaseButton.setIcon(preserve_case_icon)
        self.preserveCaseButton.setText("")

        self.replaceButton.setIcon(replace_icon)
        self.replaceButton.setText("")

        self.replaceAllButton.setIcon(replace_all_icon)
        self.replaceAllButton.setText("")

    def changeEvent(self, event):
        """システムテーマやパレットが変更された際にアイコンの色を再生成・再適用する"""
        if event and event.type() == QEvent.Type.PaletteChange:
            self._update_icons()
        super().changeEvent(event)
