import json
import os

from PySide6.QtCore import QFile, Qt, QEvent, QObject
from PySide6.QtGui import QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QFileDialog,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QLabel,
    QSizePolicy
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


def _setup_preview_view(widget):
    if widget.graphicsTextureView is None:
        return None

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

    def fit_preview_to_view():
        if widget._gfx_preview_scene is None:
            return
        rect = widget._gfx_preview_scene.sceneRect()
        if not rect.isNull() and rect.width() > 0 and rect.height() > 0:
            widget.graphicsTextureView.fitInView(
                rect, Qt.AspectRatioMode.KeepAspectRatio
            )

    class PreviewResizeFilter(QObject):
        def eventFilter(self, watched, event):
            if (
                watched == widget.graphicsTextureView.viewport()
                and event.type() == QEvent.Type.Resize
            ):
                fit_preview_to_view()
            return False

    widget._gfx_preview_resize_filter = PreviewResizeFilter(widget.graphicsTextureView)
    widget.graphicsTextureView.viewport().installEventFilter(
        widget._gfx_preview_resize_filter
    )

    preview_placeholder = QLabel(
        "定義を追加してプレビューを表示",
        widget.graphicsTextureView,
    )
    preview_placeholder.setObjectName("gfxPreviewPlaceholder")
    preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview_placeholder.setWordWrap(True)
    preview_placeholder.setStyleSheet(
        "QLabel { color: #9a9a9a; background: transparent; border: none; font-size: 14px; }"
    )
    preview_placeholder.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    preview_placeholder.setGeometry(widget.graphicsTextureView.viewport().rect())
    preview_placeholder.raise_()
    widget._gfx_preview_placeholder = preview_placeholder

    def sync_preview_placeholder_geometry():
        if widget._gfx_preview_placeholder is None:
            return
        widget._gfx_preview_placeholder.setGeometry(
            widget.graphicsTextureView.viewport().rect()
        )

    class PreviewViewportFilter(QObject):
        def eventFilter(self, watched, event):
            if (
                watched == widget.graphicsTextureView.viewport()
                and event.type() == QEvent.Type.Resize
            ):
                sync_preview_placeholder_geometry()
                _update_preview_placeholder_visibility(widget)
            return False

    widget._gfx_preview_viewport_filter = PreviewViewportFilter(
        widget.graphicsTextureView.viewport()
    )
    widget.graphicsTextureView.viewport().installEventFilter(
        widget._gfx_preview_viewport_filter
    )
    return fit_preview_to_view


def _update_preview_placeholder_visibility(widget):
    preview = getattr(widget, "_gfx_preview_placeholder", None)
    if preview is None:
        return
    show_preview = widget._gfx_selected_definition is None and widget._gfx_preview_item is None
    preview.setVisible(show_preview)
    if show_preview:
        preview.raise_()


def _set_definition_selected(widget, selected):
    widget._gfx_selected_definition = selected
    if widget.widgetCenterPane is not None:
        widget.widgetCenterPane.setCurrentIndex(0 if selected else 1)
    _update_preview_placeholder_visibility(widget)


def _load_preview_image(widget, path, fit_preview_to_view):
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
        fit_preview_to_view()

    _update_preview_placeholder_visibility(widget)
    return True


def _refresh_definition_list(widget, select_index=None):
    tree = widget.listGfxNodes
    if not isinstance(tree, QTreeWidget):
        return

    tree.clear()
    for index, definition in enumerate(widget._gfx_definitions):
        item = QTreeWidgetItem([definition["name"], definition["type"]])
        item.setData(0, Qt.ItemDataRole.UserRole, index)
        tree.addTopLevelItem(item)
        if select_index is not None and index == select_index:
            tree.setCurrentItem(item)


def _get_selected_definition_index(widget):
    tree = widget.listGfxNodes
    if not isinstance(tree, QTreeWidget):
        return None
    item = tree.currentItem()
    if item is None:
        return None
    index = item.data(0, Qt.ItemDataRole.UserRole)
    return index if isinstance(index, int) else None


def _update_definition_state(widget):
    has_selection = _get_selected_definition_index(widget) is not None
    _set_definition_selected(widget, has_selection)
    if widget.btnDuplicateNode is not None:
        widget.btnDuplicateNode.setEnabled(has_selection)
    if widget.btnDeleteNode is not None:
        widget.btnDeleteNode.setEnabled(has_selection)
    return has_selection


def _create_definition(widget, definition_type=None, name=None, source_path=""):
    if not isinstance(widget.listGfxNodes, QTreeWidget):
        return None

    if not name:
        widget._gfx_definition_counter += 1
        name = f"new_gfx_{widget._gfx_definition_counter}"

    if definition_type is None and widget.comboGfxType is not None:
        definition_type = widget.comboGfxType.currentText() or "spriteType"

    definition = {
        "name": name,
        "type": definition_type or "spriteType",
        "source_path": source_path,
    }
    widget._gfx_definitions.append(definition)
    _refresh_definition_list(widget, len(widget._gfx_definitions) - 1)
    _update_definition_state(widget)
    widget.is_dirty = True
    return definition


def _create_definition_from_image(widget, load_preview):
    start_dir = ""
    if widget.editSourcePath is not None:
        current_value = widget.editSourcePath.text().strip()
        if current_value:
            start_dir = os.path.dirname(current_value) or current_value

    path, _ = QFileDialog.getOpenFileName(
        widget,
        "Select texture image for new definition",
        start_dir or os.path.dirname(widget.file_path or "") or "",
        "Images (*.png *.jpg *.jpeg *.bmp *.tga *.dds);;All Files (*.*)",
    )
    if not path:
        return

    file_name = os.path.splitext(os.path.basename(path))[0] or "new_gfx"
    widget._gfx_definition_counter += 1
    definition = _create_definition(
        widget,
        definition_type=widget.comboGfxType.currentText() if widget.comboGfxType is not None else None,
        source_path=path,
    )
    if definition is None:
        return

    if widget.editSourcePath is not None:
        widget.editSourcePath.setText(path)
    widget.raw_gfx_content = path
    _set_definition_selected(widget, True)
    load_preview(path)


def _duplicate_selected_definition(widget):
    index = _get_selected_definition_index(widget)
    if index is None:
        return
    source = widget._gfx_definitions[index]
    copy_index = len(widget._gfx_definitions) + 1
    _create_definition(
        widget,
        name=f"{source['name']}_copy{copy_index}",
        definition_type=source.get("type", "spriteType"),
        source_path=source.get("source_path", ""),
    )


def _delete_selected_definition(widget):
    index = _get_selected_definition_index(widget)
    if index is None:
        return

    del widget._gfx_definitions[index]
    _refresh_definition_list(widget)
    widget._gfx_selected_definition = None

    if widget._gfx_preview_scene is not None:
        widget._gfx_preview_scene.clear()
        widget._gfx_preview_item = None

    preview = getattr(widget, "_gfx_preview_placeholder", None)
    if preview is not None:
        preview.show()
        preview.raise_()

    _update_definition_state(widget)
    widget.is_dirty = True


def _browse_source(widget, file_path, load_preview):
    start_dir = ""
    if widget.editSourcePath is not None:
        current_value = widget.editSourcePath.text().strip()
        if current_value:
            start_dir = os.path.dirname(current_value) or current_value

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
    _set_definition_selected(widget, True)
    load_preview(path)


def _wire_definition_buttons(widget, load_preview):
    if isinstance(widget.listGfxNodes, QTreeWidget):
        widget.listGfxNodes.currentItemChanged.connect(
            lambda *_: _on_definition_selection_changed(widget, load_preview)
        )

    if widget.btnDuplicateNode is not None:
        widget.btnDuplicateNode.clicked.connect(
            lambda: _duplicate_selected_definition(widget)
        )
        widget.btnDuplicateNode.setEnabled(False)
    if widget.btnDeleteNode is not None:
        widget.btnDeleteNode.clicked.connect(
            lambda: _delete_selected_definition(widget)
        )
        widget.btnDeleteNode.setEnabled(False)
    if widget.btnNewNode is not None:
        widget.btnNewNode.clicked.connect(
            lambda: _create_definition_from_image(widget, load_preview)
        )
    if widget.btnBrowseSource is not None:
        widget.btnBrowseSource.clicked.connect(
            lambda: _browse_source(widget, widget.file_path, load_preview)
        )


def _on_definition_selection_changed(widget, load_preview):
    _update_definition_state(widget)
    index = _get_selected_definition_index(widget)
    if index is None:
        return
    definition = widget._gfx_definitions[index]
    widget._gfx_selected_definition = definition
    if widget.editSourcePath is not None:
        widget.editSourcePath.setText(definition.get("source_path", ""))
    _set_definition_selected(widget, True)
    if definition.get("source_path"):
        load_preview(definition["source_path"])


def setup(widget, file_path, content):
    widget.file_path = file_path
    widget.content = content
    widget.is_dirty = False
    widget.editor_id = "gfx_editor"
    widget.gfx_ui = widget
    widget.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    widget.setVisible(True)

    title = "GFX Editor"
    if file_path:
        title = file_path.split("/")[-1].split("\\")[-1]
    widget.setWindowTitle(title)

    widget.listGfxNodes = widget.findChild(QWidget, "listGfxNodes")
    if isinstance(widget.listGfxNodes, QTreeWidget):
        widget.listGfxNodes.setColumnCount(2)
        widget.listGfxNodes.setHeaderLabels(["定義名 / 画像名", "定義タイプ"])
    widget.comboGfxType = widget.findChild(QWidget, "comboGfxType")
    widget.editSourcePath = widget.findChild(QWidget, "editSourcePath")
    widget.btnBrowseSource = widget.findChild(QWidget, "btnBrowseSource")
    widget.btnNewNode = widget.findChild(QWidget, "btnNewNode")
    widget.btnDuplicateNode = widget.findChild(QWidget, "btnDuplicateNode")
    widget.btnDeleteNode = widget.findChild(QWidget, "btnDeleteNode")
    widget.graphicsTextureView = widget.findChild(QWidget, "graphicsTextureView")
    widget.widgetCenterPane = widget.findChild(QWidget, "widgetCenterPane")
    widget.widgetRightPane = widget.findChild(QWidget, "widgetRightPane")
    widget._gfx_preview_scene = None
    widget._gfx_preview_item = None
    widget._gfx_selected_definition = None
    widget._gfx_definitions = []
    widget._gfx_definition_counter = 0

    fit_preview_to_view = _setup_preview_view(widget)

    def load_preview(path):
        return _load_preview_image(widget, path, fit_preview_to_view or (lambda: None))

    _wire_definition_buttons(widget, load_preview)
    _set_definition_selected(widget, False)

    if widget.editSourcePath is not None:
        initial_path = widget.editSourcePath.text().strip()
        if initial_path:
            _set_definition_selected(widget, True)
            load_preview(initial_path)

    widget.raw_gfx_content = content
