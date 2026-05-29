from PySide6.QtCore import QObject, Qt, QEvent
from PySide6.QtGui import QShortcut, QKeySequence, QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
from core.search_popup import SearchPopUpWidget
from core.search_engine import TextDocumentSearcher

class SearchController(QObject):
    def __init__(self, window, editor_tabs):
        super().__init__(window)
        self.window = window
        self.editor_tabs = editor_tabs
        
        # ポップアップウィジェットの作成とメインウィンドウへの配置
        self.search_popup = SearchPopUpWidget(window)
        self.search_popup.hide()
        
        # 検索結果のキャッシュ保持用 {editor_widget: {"occurrences": [...], "current_index": -1, "query": SearchQuery}}
        self.search_cache = {}
        
        # シグナルの接続
        self.search_popup.query_changed.connect(self.on_query_changed)
        self.search_popup.find_next.connect(self.on_find_next)
        self.search_popup.find_previous.connect(self.on_find_previous)
        self.search_popup.replace_requested.connect(self.on_replace_requested)
        self.search_popup.replace_all_requested.connect(self.on_replace_all_requested)
        self.search_popup.close_requested.connect(self.hide_search_popup)
        
        # ショートカットキー Ctrl+F の登録
        self.find_shortcut = QShortcut(QKeySequence("Ctrl+F"), window)
        self.find_shortcut.activated.connect(self.show_search_popup)
        
        # タブ切り替えの接続
        if self.editor_tabs:
            self.editor_tabs.currentChanged.connect(self.on_tab_changed)

    def get_current_text_editor(self):
        """現在のアクティブなエディタがテキストエディタ(QPlainTextEdit)であればそれを返す"""
        if not self.editor_tabs:
            return None
        widget = self.editor_tabs.currentWidget()
        if widget and isinstance(widget, QPlainTextEdit):
            return widget
        return None

    def update_search_popup_position(self):
        """エディタの右上角にポップアップが吸い付くように位置合わせする"""
        editor = self.get_current_text_editor()
        if not editor or self.search_popup.isHidden():
            return
            
        # ユーザーによって手動ドラッグ移動された場合は、自動配置（追従）をスキップ
        if self.search_popup.manually_moved:
            return
            
        # ポップアップのサイズを明示的に最新化（フロート時のサイズ崩れ防止）
        self.search_popup._update_widget_size()
        
        # エディタの右上端から少しマージンをあけた位置に配置
        editor_rect = editor.rect()
        global_pos = editor.mapTo(self.window, editor_rect.topRight())
        
        # ポップアップのサイズに基づいてX座標を調整
        popup_width = self.search_popup.width()
        x = global_pos.x() - popup_width - 30 # 右側のマージン
        y = global_pos.y() + 10                # 上側のマージン
        
        self.search_popup.move(x, y)
        self.search_popup.raise_()

    def clear_search_highlights(self, editor):
        """指定したエディタの検索ハイライトをクリアする"""
        if editor:
            try:
                editor.setExtraSelections([])
            except Exception:
                pass
        if editor in self.search_cache:
            self.search_cache.pop(editor)

    def on_query_changed(self, query):
        editor = self.get_current_text_editor()
        if not editor:
            self.search_popup.set_match_count(0, 0)
            return

        if query.is_empty():
            self.clear_search_highlights(editor)
            self.search_popup.set_match_count(0, 0)
            return

        # QTextDocumentに対する検索実行
        occurrences = TextDocumentSearcher.search(editor.document(), query)
        total = len(occurrences)
        
        # 現在位置の選定（現在のカーソル位置より後ろにある最初の一致を探す）
        cursor_pos = editor.textCursor().position()
        current_idx = -1
        for idx, occ in enumerate(occurrences):
            if occ.position >= cursor_pos:
                current_idx = idx
                break
        if current_idx == -1 and total > 0:
            current_idx = 0  # なければ最初に戻る

        self.search_cache[editor] = {
            "occurrences": occurrences,
            "current_index": current_idx,
            "query": query
        }

        self.apply_highlights(editor)

    def apply_highlights(self, editor):
        if editor not in self.search_cache:
            return

        cache = self.search_cache[editor]
        occurrences = cache["occurrences"]
        current_idx = cache["current_index"]
        
        selections = []
        
        # 通常の一致箇所のハイライト (薄い暗黄色)
        normal_format = QTextCharFormat()
        normal_format.setBackground(QColor(85, 85, 0, 150))
        normal_format.setForeground(QColor("#ffffff"))

        # 現在選択されている箇所 (明るいオレンジ)
        active_format = QTextCharFormat()
        active_format.setBackground(QColor(216, 108, 0, 200))
        active_format.setForeground(QColor("#ffffff"))

        for idx, occ in enumerate(occurrences):
            selection = QTextEdit.ExtraSelection()
            
            cursor = editor.textCursor()
            cursor.setPosition(occ.position)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, occ.length)
            
            selection.cursor = cursor
            selection.format = active_format if idx == current_idx else normal_format
            selections.append(selection)

        try:
            editor.setExtraSelections(selections)
        except Exception:
            pass
        self.search_popup.set_match_count(current_idx + 1 if current_idx >= 0 else 0, len(occurrences))

    def on_find_next(self):
        editor = self.get_current_text_editor()
        if not editor or editor not in self.search_cache:
            return
            
        cache = self.search_cache[editor]
        occurrences = cache["occurrences"]
        if not occurrences:
            return

        # インデックスを進める
        current_idx = (cache["current_index"] + 1) % len(occurrences)
        cache["current_index"] = current_idx
        
        # カーソル移動とスクロール
        occ = occurrences[current_idx]
        cursor = editor.textCursor()
        cursor.setPosition(occ.position)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, occ.length)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()

        self.apply_highlights(editor)

    def on_find_previous(self):
        editor = self.get_current_text_editor()
        if not editor or editor not in self.search_cache:
            return
            
        cache = self.search_cache[editor]
        occurrences = cache["occurrences"]
        if not occurrences:
            return

        # インデックスを戻す
        current_idx = (cache["current_index"] - 1) % len(occurrences)
        cache["current_index"] = current_idx
        
        # カーソル移動とスクロール
        occ = occurrences[current_idx]
        cursor = editor.textCursor()
        cursor.setPosition(occ.position)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, occ.length)
        editor.setTextCursor(cursor)
        editor.ensureCursorVisible()

        self.apply_highlights(editor)

    def on_replace_requested(self, search_text, replace_text):
        editor = self.get_current_text_editor()
        if not editor or editor not in self.search_cache:
            return
            
        cache = self.search_cache[editor]
        occurrences = cache["occurrences"]
        current_idx = cache["current_index"]
        
        if current_idx < 0 or current_idx >= len(occurrences):
            return
            
        occ = occurrences[current_idx]
        
        cursor = editor.textCursor()
        cursor.setPosition(occ.position)
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, occ.length)
        
        # 選択部分のテキストを取得して検証
        if cursor.selectedText() == search_text or not cache["query"].match_case:
            cursor.insertText(replace_text)
            
            # 再検索して結果とハイライトを更新
            self.on_query_changed(cache["query"])

    def on_replace_all_requested(self, search_text, replace_text):
        editor = self.get_current_text_editor()
        if not editor or editor not in self.search_cache:
            return
            
        cache = self.search_cache[editor]
        occurrences = cache["occurrences"]
        if not occurrences:
            return
            
        # 逆順から置換して位置ズレを防ぐ
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        try:
            for occ in reversed(occurrences):
                cursor.setPosition(occ.position)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, occ.length)
                cursor.insertText(replace_text)
        finally:
            cursor.endEditBlock()
            
        # 再検索してUIを更新
        self.on_query_changed(cache["query"])

    def show_search_popup(self):
        editor = self.get_current_text_editor()
        if not editor:
            return
        
        # 既に表示されている場合はトグルで非表示にする
        if not self.search_popup.isHidden():
            self.hide_search_popup()
            return
            
        # 新規オープン時は手動移動フラグをリセットし、初期位置（右上）から開始
        self.search_popup.manually_moved = False
        self.search_popup.show_popup()
        self.update_search_popup_position()

    def hide_search_popup(self):
        editor = self.get_current_text_editor()
        self.clear_search_highlights(editor)
        self.search_popup.hide_popup()
        if editor:
            editor.setFocus()

    def on_tab_changed(self, idx):
        if self.editor_tabs:
            widget = self.editor_tabs.widget(idx)
            self.clear_search_highlights(widget)
            if not self.search_popup.isHidden():
                self.update_search_popup_position()
                self.on_query_changed(self.search_popup.get_query())
