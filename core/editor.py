import os

import core.api
from core import save_result
from PySide6.QtWidgets import (
    QFileDialog, QPlainTextEdit, QTextEdit, QWidget, QScrollBar
)
from PySide6.QtGui import QFont, QColor, QPainter, QTextFormat
from PySide6.QtCore import Qt, QSize, QRect


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

        self.setExtraSelections(extra_selections)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

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
