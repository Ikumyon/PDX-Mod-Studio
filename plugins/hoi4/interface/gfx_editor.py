import os

from PySide6.QtCore import QFile, Qt, QEvent, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QWidget,
)


EDITOR_NAME = "GFX Editor"


def _load_ui_widget(ui_path, parent=None):
    loader = QUiLoader()
    ui_file = QFile(ui_path)
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        raise FileNotFoundError(ui_path)

    try:
        widget = loader.load(ui_file, parent)
    finally:
        ui_file.close()

    if widget is None:
        raise RuntimeError(loader.errorString())

    return widget


def setup(widget, file_path, content):
    """
    Minimal gfx editor bootstrap.

    This phase only loads and shows the .ui layout so the editor can be opened
    safely while the rest of the editor logic is being rebuilt.
    """

    widget.file_path = file_path
    widget.content = content
    widget.is_dirty = False
    widget.editor_id = "gfx_editor"

    # Keep a direct reference to the loaded UI so the layout stays alive.
    widget.gfx_ui = widget

    # Make the loaded widget behave like a normal top-level editor surface when
    # embedded inside the host application.
    widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    widget.setVisible(True)

    # Provide a small amount of metadata to help the host show the tab.
    title = "GFX Editor"
    if file_path:
        title = file_path.split("/")[-1].split("\\")[-1]
    widget.setWindowTitle(title)

    # Collect a few useful child references when they exist. We do not wire the
    # full editor yet; the goal for this milestone is showing the loaded UI.
    widget.listGfxNodes = widget.findChild(QWidget, "listGfxNodes")
    widget.comboGfxType = widget.findChild(QWidget, "comboGfxType")
    widget.editSourcePath = widget.findChild(QWidget, "editSourcePath")
    widget.btnBrowseSource = widget.findChild(QWidget, "btnBrowseSource")
    widget.graphicsTextureView = widget.findChild(QWidget, "graphicsTextureView")
    widget._gfx_preview_scene = None
    widget._gfx_preview_item = None

    if widget.graphicsTextureView is not None:
        scene = QGraphicsScene(widget.graphicsTextureView)
        widget.graphicsTextureView.setScene(scene)
        widget.graphicsTextureView.setAlignment(Qt.AlignmentFlag.AlignCenter)
        widget.graphicsTextureView.setResizeAnchor(
            widget.graphicsTextureView.ViewportAnchor.AnchorViewCenter
        )
        widget.graphicsTextureView.setTransformationAnchor(
            widget.graphicsTextureView.ViewportAnchor.AnchorViewCenter
        )
        widget._gfx_preview_scene = scene

        def _fit_preview_to_view():
            if widget._gfx_preview_scene is None:
                return
            rect = widget._gfx_preview_scene.sceneRect()
            if not rect.isNull() and rect.width() > 0 and rect.height() > 0:
                widget.graphicsTextureView.fitInView(
                    rect, Qt.AspectRatioMode.KeepAspectRatio
                )

        class _PreviewResizeFilter(QObject):
            def eventFilter(self, watched, event):
                if (
                    watched == widget.graphicsTextureView.viewport()
                    and event.type() == QEvent.Type.Resize
                ):
                    _fit_preview_to_view()
                return False

        widget._gfx_preview_resize_filter = _PreviewResizeFilter(widget.graphicsTextureView)
        widget.graphicsTextureView.viewport().installEventFilter(
            widget._gfx_preview_resize_filter
        )

    def load_image(path):
        if not path:
            return False
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False

        if widget._gfx_preview_scene is not None:
            widget._gfx_preview_scene.clear()
            item = QGraphicsPixmapItem(pixmap)
            widget._gfx_preview_scene.addItem(item)
            widget._gfx_preview_scene.setSceneRect(item.boundingRect())
            widget._gfx_preview_item = item
            _fit_preview_to_view()
        return True

    def browse_source():
        start_dir = ""
        if widget.editSourcePath is not None:
            current_value = widget.editSourcePath.text().strip()
            if current_value:
                start_dir = os.path.dirname(current_value)
                if not start_dir:
                    start_dir = current_value

        path, _ = QFileDialog.getOpenFileName(
            widget,
            "Select texture image",
            start_dir or os.path.dirname(file_path or "") or "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.dds);;All Files (*.*)",
        )
        if not path:
            return

        if widget.editSourcePath is not None:
            widget.editSourcePath.setText(path)
        widget.raw_gfx_content = path
        widget.is_dirty = True
        load_image(path)

    if widget.btnBrowseSource is not None:
        widget.btnBrowseSource.clicked.connect(browse_source)

    if widget.editSourcePath is not None:
        initial_path = widget.editSourcePath.text().strip()
        if initial_path:
            load_image(initial_path)
            if widget._gfx_preview_scene is not None:
                _fit_preview_to_view()

    # Store the original file content for later parser work.
    widget.raw_gfx_content = content
