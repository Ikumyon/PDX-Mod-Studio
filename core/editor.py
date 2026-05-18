from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QTextEdit, QToolButton, QVBoxLayout, QWidget
)
from PySide6.QtGui import QFont, QColor, QPainter, QTextFormat, QTextCharFormat, QTextCursor
from PySide6.QtCore import Qt, QSize, QRect, QTimer, QEvent, QPoint


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

class MinimapWidget(QPlainTextEdit):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setReadOnly(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) # とりあえずクリック無効
        
        # 極小フォントの設定
        font = QFont(self.editor.font())
        font.setPointSize(2)
        self.setFont(font)
        
        # 背景色を少し透明にするか変える
        palette = self.palette()
        bg = palette.color(self.backgroundRole())
        bg.setAlpha(150)
        palette.setColor(self.backgroundRole(), bg)
        self.setPalette(palette)
        
        self.setStyleSheet("background-color: rgba(0, 0, 0, 0.1); border-left: 1px solid rgba(255, 255, 255, 0.1);")

class DiagnosticPopup(QFrame):
    def __init__(self, editor):
        super().__init__(editor, Qt.WindowType.Popup)
        self.editor = editor
        self.diagnostic = None
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)

        self.message_label = QLabel(self)
        self.message_label.setTextFormat(Qt.TextFormat.RichText)
        self.message_label.setWordWrap(True)
        self.message_label.setMinimumWidth(320)
        self.message_label.setMaximumWidth(560)

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message_label)
        layout.addLayout(self.actions_layout)

    def show_diagnostic(self, global_pos, diagnostic):
        self.diagnostic = diagnostic
        self.message_label.setText(diagnostic.message)
        self._set_actions(getattr(diagnostic, "actions", []))
        self.adjustSize()
        self.move(global_pos + QPoint(0, 18))
        self.show()

    def _set_actions(self, actions):
        while self.actions_layout.count():
            item = self.actions_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for action in actions:
            button = QToolButton(self)
            button.setText(action.title)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, action=action: self._apply_action(action))
            self.actions_layout.addWidget(button)
        if actions:
            self.actions_layout.addStretch(1)

    def _apply_action(self, action):
        self.hide()
        self.editor.apply_diagnostic_action(action)

class EditorWidget(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        
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
        
        # ミニマップの設定
        self.minimap = MinimapWidget(self)
        self.textChanged.connect(self.update_minimap_text)
        self.verticalScrollBar().valueChanged.connect(self.sync_minimap_scroll)
        
        # 診断情報（エラー波線用）の初期化
        self.diagnostics = []
        self.diagnostic_timer = QTimer(self)
        self.diagnostic_timer.setSingleShot(True)
        self.diagnostic_timer.timeout.connect(self.run_diagnostics)
        self.textChanged.connect(self.trigger_diagnostics)
        self.diagnostic_popup = DiagnosticPopup(self)
        
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()


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
        return 80 # 固定幅

    def update_minimap_text(self):
        self.minimap.setPlainText(self.toPlainText())
        self.sync_minimap_scroll()

    def sync_minimap_scroll(self):
        # メインエディタのスクロール位置を割合でミニマップに反映
        main_bar = self.verticalScrollBar()
        if main_bar.maximum() > 0:
            ratio = main_bar.value() / main_bar.maximum()
            mini_bar = self.minimap.verticalScrollBar()
            mini_bar.setValue(int(ratio * mini_bar.maximum()))

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

    def highlight_current_line(self):
        self.update_extra_selections()

    def update_extra_selections(self):
        extra_selections = []
        content = self.toPlainText()

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

        # 2. エラー・警告波線の描画
        for diag in getattr(self, "diagnostics", []):
            selection = QTextEdit.ExtraSelection()
            
            # エラー範囲を指す QTextCursor を作成
            cursor = self.textCursor()
            cursor.setPosition(self._to_qtext_position(content, diag.range.start_offset))
            # end_offset までの範囲を選択状態にする
            cursor.setPosition(self._to_qtext_position(content, diag.range.end_offset), QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            
            # 波線書式の設定
            char_format = QTextCharFormat()
            char_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
            
            # 重要度に応じた色分け (Error: 赤, Warning: 黄)
            if diag.severity == "error":
                char_format.setUnderlineColor(QColor("#FF5555")) # 赤色
            else:
                char_format.setUnderlineColor(QColor("#FFAA00")) # 黄色
                
            char_format.setToolTip(diag.message) # ツールチップ（HTML）表示
            selection.format = char_format
            
            extra_selections.append(selection)


        self.setExtraSelections(extra_selections)

    def _to_qtext_position(self, content, offset):
        offset = max(0, min(offset, len(content)))
        return len(content[:offset].encode("utf-16-le")) // 2

    def _diagnostic_at_viewport_pos(self, pos):
        cursor = self.cursorForPosition(pos)
        qtext_position = cursor.position()
        content = self.toPlainText()

        for diag in getattr(self, "diagnostics", []):
            start = self._to_qtext_position(content, diag.range.start_offset)
            end = self._to_qtext_position(content, diag.range.end_offset)
            if start <= qtext_position < end:
                return diag
        return None

    def _show_diagnostic_popup(self, pos, global_pos):
        diag = self._diagnostic_at_viewport_pos(pos)
        if diag:
            self.diagnostic_popup.show_diagnostic(global_pos, diag)
            return True

        if not self.diagnostic_popup.geometry().contains(global_pos):
            self.diagnostic_popup.hide()
        return False

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        self._show_diagnostic_popup(pos, self.viewport().mapToGlobal(pos))

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            pos = event.pos()
            if self._show_diagnostic_popup(pos, event.globalPos()):
                return True

            event.ignore()
            return True

        return super().viewportEvent(event)

    def apply_diagnostic_action(self, action):
        content = self.toPlainText()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(self._to_qtext_position(content, action.range.start_offset))
        cursor.setPosition(self._to_qtext_position(content, action.range.end_offset), QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(action.replacement)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        self.run_diagnostics()

    def trigger_diagnostics(self):
        self.diagnostic_timer.start(500) # 500msの遅延実行

    def run_diagnostics(self):
        if not hasattr(self, "file_path") or not self.file_path:
            return
        content = self.toPlainText()
        import core.api
        diagnostics = core.api.get_diagnostics(self.file_path, content)
        self.show_diagnostics(diagnostics)

    def show_diagnostics(self, diagnostics):
        self.diagnostics = diagnostics
        self.diagnostic_popup.hide()
        self.update_extra_selections()


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
