import os
import math
import core.api
from core import save_result
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget, QScrollBar
)
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtCore import Qt, QSize, QRect, QPoint


DIAGNOSTIC_ERROR_COLOR = QColor("#d83b3b")
DIAGNOSTIC_WARNING_COLOR = QColor("#d8a53b")


def diagnostic_underline_color(diagnostic):
    if getattr(diagnostic, "severity", "error") == "warning":
        return DIAGNOSTIC_WARNING_COLOR
    return DIAGNOSTIC_ERROR_COLOR


class DiagnosticPopup(QFrame):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.diagnostic = None
        self.setObjectName("DiagnosticPopup")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            QFrame#DiagnosticPopup {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 6px;
            }
            QLabel#DiagnosticTitle {
                font-weight: 600;
            }
            QLabel#DiagnosticDescription {
                color: palette(text);
            }
            QLabel#DiagnosticQuickFixTitle {
                font-weight: 600;
                margin-top: 4px;
            }
            QPushButton {
                padding: 4px 8px;
                text-align: left;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        self.title_label = QLabel(self)
        self.title_label.setObjectName("DiagnosticTitle")
        self.title_label.setWordWrap(True)
        layout.addWidget(self.title_label)

        self.description_label = QLabel(self)
        self.description_label.setObjectName("DiagnosticDescription")
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)

        self.quick_fix_label = QLabel(self)
        self.quick_fix_label.setText("クイックフィックス")
        self.quick_fix_label.setObjectName("DiagnosticQuickFixTitle")
        layout.addWidget(self.quick_fix_label)

        self.quick_fix_layout = QHBoxLayout()
        self.quick_fix_layout.setContentsMargins(0, 0, 0, 0)
        self.quick_fix_layout.setSpacing(6)
        layout.addLayout(self.quick_fix_layout)

        self.suggestion_buttons = []

    def set_diagnostic(self, diagnostic, title, description, suggestions):
        self.diagnostic = diagnostic
        self.title_label.setText(title)
        self.description_label.setText(description)
        self.description_label.setVisible(bool(description))

        while self.quick_fix_layout.count():
            item = self.quick_fix_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.suggestion_buttons = []

        for suggestion in suggestions:
            label = str(suggestion.get("label", "")).strip()
            replacement = suggestion.get("replacement")
            if not label or replacement is None:
                continue
            button = QPushButton(label, self)
            button.clicked.connect(lambda checked=False, text=str(replacement): self.editor.apply_diagnostic_replacement(self.diagnostic, text))
            self.quick_fix_layout.addWidget(button)
            self.suggestion_buttons.append(button)

        self.quick_fix_layout.addStretch(1)
        self.quick_fix_label.setVisible(bool(self.suggestion_buttons))

        self.adjustSize()

    def leaveEvent(self, event):
        self.hide()
        super().leaveEvent(event)


class HighlightScrollBar(QScrollBar):
    def __init__(self, editor, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.editor = editor
        self.editor.cursorPositionChanged.connect(self.update)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        total_blocks = self.editor.blockCount()
        if total_blocks <= 1:
            return

        cursor_block = self.editor.textCursor().blockNumber()
        
        painter = QPainter(self)
        btn_size = self.width()
        track_height = self.height() - btn_size * 2
        
        if track_height > 0:
            ratio = cursor_block / total_blocks
            y = btn_size + int(ratio * track_height)
            
            painter.fillRect(QRect(0, y - 1, self.width(), 2), QColor(255, 140, 0, 200))


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

class MinimapWidget(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self._lines = []
        self.is_dragging = False
        self.is_viewport_hovered = False
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        
        self.apply_minimap_font()
        
        # 背景色を少し透明にするか変える
        palette = self.palette()
        bg = palette.color(self.backgroundRole())
        bg.setAlpha(150)
        palette.setColor(self.backgroundRole(), bg)
        self.setPalette(palette)
        
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.1); border-left: 1px solid rgba(255, 255, 255, 0.1);")

    def _get_viewport_y_range(self):
        bar = self.editor.verticalScrollBar()
        total_range = bar.maximum() + bar.pageStep()
        if total_range > 0 and self.height() > 0:
            start_ratio = bar.value() / total_range
            end_ratio = (bar.value() + bar.pageStep()) / total_range
            y_start = int(self.height() * start_ratio)
            y_end = int(self.height() * end_ratio)
            h = max(4, y_end - y_start)
            return y_start, h
        return 0, 0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self._scroll_to_pos(event.position().y())

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self._scroll_to_pos(event.position().y())
        else:
            # 白い領域（ビューポート）にホバーしているか判定
            y_start, h = self._get_viewport_y_range()
            my = event.position().y()
            is_hover = (y_start <= my <= y_start + h)
            if is_hover != self.is_viewport_hovered:
                self.is_viewport_hovered = is_hover
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            # リリース時にもう一度ホバー状態を判定し直す
            y_start, h = self._get_viewport_y_range()
            my = event.position().y()
            is_hover = (y_start <= my <= y_start + h)
            if is_hover != self.is_viewport_hovered:
                self.is_viewport_hovered = is_hover
                self.update()

    def leaveEvent(self, event):
        if self.is_viewport_hovered:
            self.is_viewport_hovered = False
            self.update()

    def _scroll_to_pos(self, y):
        bar = self.editor.verticalScrollBar()
        total_range = bar.maximum() + bar.pageStep()
        if total_range > 0 and self.height() > 0:
            ratio = y / self.height()
            target_value = int(ratio * total_range - bar.pageStep() / 2)
            target_value = max(0, min(bar.maximum(), target_value))
            bar.setValue(target_value)

    def apply_minimap_font(self):
        self.update()

    def setPlainText(self, text):
        self._lines = text.splitlines() or [""]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, QColor(0, 0, 0, 25))
        painter.fillRect(QRect(rect.left(), rect.top(), 1, rect.height()), QColor(255, 255, 255, 25))

        if not self._lines or rect.width() <= 2 or rect.height() <= 0:
            return

        line_color = self.editor.palette().color(self.editor.foregroundRole())
        line_color.setAlpha(65)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(line_color)

        rows = [0] * rect.height()
        line_count = len(self._lines)
        draw_width = max(1, rect.width() - 4)
        for index, line in enumerate(self._lines):
            y = min(rect.height() - 1, index * rect.height() // line_count)
            width = min(draw_width, max(1, len(line.expandtabs(4)) // 2))
            if width > rows[y]:
                rows[y] = width

        for y, width in enumerate(rows):
            if width:
                painter.drawRect(2, y, width, 1)

        y_start, h = self._get_viewport_y_range()
        if h > 0:
            # 状態に応じたビジュアルスタイルの決定
            if self.is_dragging:
                fill_color = QColor(255, 255, 255, 40)
                border_color = QColor(255, 255, 255, 130)
            elif self.is_viewport_hovered:
                fill_color = QColor(255, 255, 255, 28)
                border_color = QColor(255, 255, 255, 80)
            else:
                fill_color = QColor(255, 255, 255, 15)
                border_color = QColor(255, 255, 255, 35)

            # 半透明の白い表示領域の描画
            viewport_rect = QRect(0, y_start, rect.width(), h)
            painter.fillRect(viewport_rect, fill_color)

            # 境界線の描画
            painter.setPen(border_color)
            painter.drawRect(0, y_start, rect.width() - 1, h - 1)

class EditorWidget(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_encoding = "utf-8"
        
        # フォントの設定（等幅フォント）
        font = QFont("Consolas")
        if not font.exactMatch():
            font = QFont("Courier New")
        font.setPointSize(11)
        self.setFont(font)
        
        # タブ幅の設定（4スペース分）
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        
        # 行の折り返し
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        
        # 行番号エリアの設定
        self.line_number_area = LineNumberArea(self)

        # 縦スクロールバーをカスタムスクロールバーに差し替え
        self.setVerticalScrollBar(HighlightScrollBar(self))
        
        # ミニマップの設定
        self.minimap = MinimapWidget(self)
        self.textChanged.connect(self.update_minimap_text)
        self.verticalScrollBar().valueChanged.connect(self.sync_minimap_scroll)
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()
        self.save_plan = None
        self._diagnostics = []
        self._diagnostic_popup = DiagnosticPopup(self)
        self._active_diagnostic = None

    def setFont(self, font):
        super().setFont(font)
        self.document().setDefaultFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(' ') * 4)
        if hasattr(self, "minimap"):
            self.minimap.apply_minimap_font()
        if hasattr(self, "line_number_area"):
            self.update_line_number_area_width(0)

    def on_save_triggered(self):
        return self.build_save_plan(save_as=False)

    def on_save_as_triggered(self):
        return self.build_save_plan(save_as=True)

    def on_write_save_plan(self):
        return self.write_save_plan()

    def build_save_plan(self, save_as=False):
        self.save_plan = None
        current_path = getattr(self, "file_path", "")
        requires_dialog = save_as or self.is_virtual_tab_path(current_path)
        target_path = current_path

        if requires_dialog:
            target_path, _ = QFileDialog.getSaveFileName(
                self.window(),
                "名前を付けて保存",
                self.default_save_dialog_path(),
                "Text Files (*.txt);;All Files (*)",
            )
            if not target_path:
                return save_result.save_cancelled()

        self.save_plan = {
            "tab_kind": "text",
            "dialog": "os_standard" if requires_dialog else None,
            "save_as": bool(requires_dialog),
            "targets": [
                {
                    "kind": "text_document",
                    "role": "テキストファイル",
                    "path": target_path,
                    "format": "text",
                }
            ],
        }
        return save_result.save_success()

    def write_save_plan(self):
        plan = getattr(self, "save_plan", None) or {}
        targets = plan.get("targets", [])
        primary_target = targets[0] if targets else None
        target_path = primary_target.get("path", "") if isinstance(primary_target, dict) else ""
        if not target_path:
            return save_result.save_failed(message="保存先が未設定です。")

        try:
            parent = os.path.dirname(target_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            encoding = getattr(self, "file_encoding", "utf-8") or "utf-8"
            with open(target_path, "w", encoding=encoding, newline="") as handle:
                handle.write(self.toPlainText())
        except Exception as error:
            return save_result.save_failed(message=str(error))

        core.api.emit_event("file_saved", target_path)
        return save_result.save_success(primary_path=target_path)

    def is_virtual_tab_path(self, path):
        return not path or str(path).startswith("untitled:")

    def default_save_dialog_path(self):
        current_path = getattr(self, "file_path", "")
        if current_path and not self.is_virtual_tab_path(current_path):
            return current_path

        project_path = core.api.get_project_path()
        if project_path:
            editor_tabs = getattr(self.window(), "editorTabs", None)
            if editor_tabs:
                index = editor_tabs.indexOf(self)
                if index >= 0:
                    tab_name = editor_tabs.tabText(index)
                    clean_name = self.tab_text_without_dirty_marker(tab_name).replace("[E] ", "").strip() or "untitled"
                    if not os.path.splitext(clean_name)[1]:
                        clean_name += ".txt"
                    return os.path.join(project_path, clean_name)
        
        fallback_dir = os.getcwd()
        editor_tabs = getattr(self.window(), "editorTabs", None)
        if editor_tabs:
            index = editor_tabs.indexOf(self)
            if index >= 0:
                tab_name = editor_tabs.tabText(index)
                clean_name = self.tab_text_without_dirty_marker(tab_name).replace("[E] ", "").strip() or "untitled"
                if not os.path.splitext(clean_name)[1]:
                    clean_name += ".txt"
                return os.path.join(fallback_dir, clean_name)
                
        return os.path.join(fallback_dir, "untitled.txt")

    @staticmethod
    def tab_text_without_dirty_marker(text):
        return text[1:] if text.startswith("*") else text


    def lineNumberAreaWidth(self):
        digits = 1
        max_blocks = max(1, self.blockCount())
        while max_blocks >= 10:
            max_blocks //= 10
            digits += 1
        
        space = 10 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, self.minimap_width(), 0)

    def minimap_width(self):
        return 80

    def update_minimap_text(self):
        self.minimap.setPlainText(self.toPlainText())
        self.sync_minimap_scroll()

    def sync_minimap_scroll(self):
        # メインエディタのスクロール位置を割合でミニマップに反映
        self.minimap.update()

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))
        
        m_width = self.minimap_width()
        self.minimap.setGeometry(QRect(cr.right() - m_width, cr.top(), m_width, cr.height()))

        # 横スクロールバーがミニマップまで伸びないように制限
        hbar = self.horizontalScrollBar()
        if hbar and hbar.isVisible():
            geom = hbar.geometry()
            new_width = max(0, geom.width() - m_width)
            hbar.setGeometry(geom.left(), geom.top(), new_width, geom.height())

    def highlight_current_line(self):
        self.update_extra_selections()

    def set_diagnostics(self, diagnostics):
        self._diagnostics = list(diagnostics or [])
        if self._active_diagnostic not in self._diagnostics:
            self._hide_diagnostic_popup()
        self.update_extra_selections()

    def clear_diagnostics(self):
        self.set_diagnostics([])

    def update_extra_selections(self):
        extra_selections = []

        # 1. 現在行のハイライト
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            # パレットのハイライト色をベースにする
            line_color = self.palette().color(self.backgroundRole()).lighter(120)
            
            selection.format.setBackground(line_color)
            selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra_selections.append(selection)

        for diagnostic in getattr(self, "_diagnostics", []):
            selection = self._diagnostic_selection(diagnostic)
            if selection is not None:
                extra_selections.append(selection)

        self.setExtraSelections(extra_selections)
        self.viewport().update()

    def _diagnostic_selection(self, diagnostic):
        diagnostic_range = self._diagnostic_range(diagnostic)
        if diagnostic_range is None:
            return None
        start, end = diagnostic_range

        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        fmt.setUnderlineColor(diagnostic_underline_color(diagnostic))

        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format = fmt
        return selection

    def _diagnostic_range(self, diagnostic):
        line = max(1, int(getattr(diagnostic, "line", 1) or 1))
        column = max(1, int(getattr(diagnostic, "column", 1) or 1))
        length = max(1, int(getattr(diagnostic, "length", 1) or 1))

        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return None

        block_end = block.position() + max(0, block.length() - 1)
        start = block.position() + min(column - 1, max(0, block.length() - 1))
        end = min(start + length, block_end)
        if end <= start:
            end = min(start + 1, block_end)
        return start, end

    def _diagnostic_hover_rect(self, diagnostic):
        diagnostic_range = self._diagnostic_range(diagnostic)
        if diagnostic_range is None:
            return None
        start, end = diagnostic_range

        start_cursor = QTextCursor(self.document())
        start_cursor.setPosition(start)
        end_cursor = QTextCursor(self.document())
        end_cursor.setPosition(end)

        start_rect = self.cursorRect(start_cursor)
        end_rect = self.cursorRect(end_cursor)
        width = max(1, end_rect.left() - start_rect.left())
        hover_rect = QRect(start_rect.left(), start_rect.top(), width, start_rect.height())
        if (
            diagnostic is self._active_diagnostic
            and self._diagnostic_popup.isVisible()
        ):
            popup_rect = self._diagnostic_popup.geometry()
            popup_top_left = self.mapToGlobal(popup_rect.topLeft())
            popup_bottom_right = self.mapToGlobal(popup_rect.bottomRight())
            viewport_top_left = self.viewport().mapFromGlobal(popup_top_left)
            viewport_bottom_right = self.viewport().mapFromGlobal(popup_bottom_right)
            popup_viewport_rect = QRect(viewport_top_left, viewport_bottom_right)
            if popup_viewport_rect.bottom() < hover_rect.top():
                hover_rect.setTop(popup_viewport_rect.bottom())
            elif popup_viewport_rect.top() > hover_rect.bottom():
                hover_rect.setBottom(popup_viewport_rect.top())
        return hover_rect

    def _diagnostic_popup_text(self, diagnostic):
        from core.i18n import tr

        message = str(getattr(diagnostic, "message", "") or "")
        translated = tr(message, "Diagnostic")
        severity = getattr(diagnostic, "severity", "error")

        if message.startswith("grammar.error.range_out_of_bounds"):
            title = tr("範囲外の数値です", "Diagnostic")
            description = translated
        elif message == "grammar.warning.float_without_decimal":
            title = tr("小数点なしで書かれています", "Diagnostic")
            description = tr("この項目は小数値として定義されています。整数表記も扱えますが、小数表記にすると意図が明確になります。", "Diagnostic")
        elif message == "grammar.error.type_mismatch":
            title = tr("型が一致しません", "Diagnostic")
            description = tr("この値は、この項目で期待される型として解釈できません。", "Diagnostic")
        elif message == "grammar.error.unknown_property":
            title = tr("未定義の項目です", "Diagnostic")
            description = tr("この項目は現在の schema では定義されていません。", "Diagnostic")
        elif message == "grammar.error.duplicate_property":
            title = tr("項目が重複しています", "Diagnostic")
            description = tr("この項目は複数回書けない定義です。", "Diagnostic")
        elif message == "grammar.error.required_property_missing":
            title = tr("必須項目がありません", "Diagnostic")
            description = tr("このブロックには必須項目が不足しています。", "Diagnostic")
        else:
            title = tr("警告", "Diagnostic") if severity == "warning" else tr("エラー", "Diagnostic")
            description = translated

        return title, description

    def _diagnostic_suggestions(self, diagnostic):
        suggestions = getattr(diagnostic, "suggestions", None)
        if not isinstance(suggestions, list):
            return []
        return [suggestion for suggestion in suggestions if isinstance(suggestion, dict)]

    def _show_diagnostic_popup(self, diagnostic):
        if self._active_diagnostic is diagnostic and self._diagnostic_popup.isVisible():
            return
        title, description = self._diagnostic_popup_text(diagnostic)
        self._diagnostic_popup.set_diagnostic(
            diagnostic,
            title,
            description,
            self._diagnostic_suggestions(diagnostic),
        )
        self._active_diagnostic = diagnostic

        popup_size = self._diagnostic_popup.sizeHint()
        hover_rect = self._diagnostic_hover_rect(diagnostic)
        if hover_rect is None:
            return
        target_rect = QRect(self.viewport().mapTo(self, hover_rect.topLeft()), hover_rect.size())
        x = target_rect.left()
        y = target_rect.top() - popup_size.height() - 6
        if y < 0:
            y = target_rect.bottom() + 6
        x = min(max(0, x), max(0, self.width() - popup_size.width() - 8))
        y = min(max(0, y), max(0, self.height() - popup_size.height() - 8))
        self._diagnostic_popup.move(x, y)
        self._diagnostic_popup.show()
        self._diagnostic_popup.raise_()

    def _hide_diagnostic_popup(self):
        self._active_diagnostic = None
        self._diagnostic_popup.hide()

    def apply_diagnostic_replacement(self, diagnostic, replacement):
        diagnostic_range = self._diagnostic_range(diagnostic)
        if diagnostic_range is None:
            return
        start, end = diagnostic_range
        cursor = QTextCursor(self.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        self._hide_diagnostic_popup()

    def paintEvent(self, event):
        super().paintEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        
        pos = event.position().toPoint()
        editor_pos = self.viewport().mapTo(self, pos)
        
        active_diag = None
        for diagnostic in getattr(self, "_diagnostics", []):
            hover_rect = self._diagnostic_hover_rect(diagnostic)
            if hover_rect is not None:
                if hover_rect.contains(pos):
                    active_diag = diagnostic
                    break
        
        if active_diag:
            self._show_diagnostic_popup(active_diag)
        else:
            popup_rect = self._diagnostic_popup.geometry()
            if not self._diagnostic_popup.isVisible() or not popup_rect.contains(editor_pos):
                self._hide_diagnostic_popup()

    def leaveEvent(self, event):
        self._hide_diagnostic_popup()
        super().leaveEvent(event)

    def viewportEvent(self, event):
        return super().viewportEvent(event)


    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.line_number_area)
        
        # 背景の塗りつぶし（少し暗め）
        bg_color = self.palette().color(self.backgroundRole()).darker(105)
        painter.fillRect(event.rect(), bg_color)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.setPen(Qt.GlobalColor.gray)
                painter.drawText(0, top, self.line_number_area.width() - 5, self.fontMetrics().height(),
                                 Qt.AlignmentFlag.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    def keyPressEvent(self, event):
        from core.dialog.settings import settings_manager
        
        # 設定が有効かチェック
        if not settings_manager.get("editor_auto_close_brackets", True):
            super().keyPressEvent(event)
            return

        cursor = self.textCursor()
        text = event.text()
        
        # 設定されたペアを取得して解析
        pairs_str = settings_manager.get("editor_auto_close_pairs", "{}()[]\"\"''")
        pairs = {}
        for i in range(0, len(pairs_str) - 1, 2):
            pairs[pairs_str[i]] = pairs_str[i+1]
            
        # 1. 閉じ括弧のオーバースキップ（重ね入力の回避）
        if text in pairs.values():
            if not cursor.hasSelection():
                pos = cursor.position()
                doc_text = self.toPlainText()
                if pos < len(doc_text) and doc_text[pos] == text:
                    # 右隣の文字が入力文字と同じなら、右に1移動
                    cursor.movePosition(QTextCursor.MoveOperation.Right)
                    self.setTextCursor(cursor)
                    event.accept()
                    return

        # 2. 開き括弧の自動補完
        if text in pairs:
            closing_char = pairs[text]
            if cursor.hasSelection():
                # 選択範囲がある場合、その選択範囲をペアで囲む
                selected_text = cursor.selectedText()
                cursor.beginEditBlock()
                cursor.insertText(text + selected_text + closing_char)
                cursor.setPosition(cursor.position() - 1)
                cursor.endEditBlock()
                self.setTextCursor(cursor)
            else:
                # 選択範囲がない場合、開き括弧と閉じ括弧を挿入し、カーソルを間に置く
                cursor.beginEditBlock()
                cursor.insertText(text + closing_char)
                cursor.movePosition(QTextCursor.MoveOperation.Left)
                cursor.endEditBlock()
                self.setTextCursor(cursor)
            event.accept()
            return

        # 3. バックスペースによるペアの同時削除
        if event.key() == Qt.Key.Key_Backspace:
            if not cursor.hasSelection():
                pos = cursor.position()
                doc_text = self.toPlainText()
                if pos > 0 and pos < len(doc_text) + 1:
                    left_char = doc_text[pos - 1] if pos - 1 < len(doc_text) else ""
                    right_char = doc_text[pos] if pos < len(doc_text) else ""
                    # 左右の文字が定義されたペアと一致するかチェック
                    if left_char in pairs and right_char == pairs[left_char]:
                        cursor.beginEditBlock()
                        cursor.deleteChar()  # 右隣の閉じ括弧を削除
                        cursor.deletePreviousChar()  # 左隣の開き括弧を削除
                        cursor.endEditBlock()
                        self.setTextCursor(cursor)
                        event.accept()
                        return

        super().keyPressEvent(event)
