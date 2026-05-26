import os

import core.api
from core import save_result
from PySide6.QtWidgets import (
    QFileDialog, QPlainTextEdit, QTextEdit, QWidget
)
from PySide6.QtGui import QFont, QColor, QPainter, QTextFormat
from PySide6.QtCore import Qt, QSize, QRect


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
                "All Files (*.*)",
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
                    return os.path.join(project_path, clean_name)
        return os.getcwd()

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
