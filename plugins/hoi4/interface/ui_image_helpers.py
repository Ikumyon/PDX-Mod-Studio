from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap, QPen
from PySide6.QtWidgets import QGraphicsRectItem

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def load_pil_image(path: str):
    if not HAS_PIL:
        return None

    try:
        return Image.open(path).convert("RGBA")
    except Exception as e:
        print(f"Pillow failed to load image ({path}): {e}.")
        return None


def pil_to_qimage(pil_img) -> QImage:
    pil_img = pil_img.convert("RGBA")
    data = pil_img.tobytes("raw", "RGBA")
    qimg = QImage(data, pil_img.size[0], pil_img.size[1], QImage.Format.Format_RGBA8888)
    return qimg.copy()


def qimage_to_pil(qimg: QImage):
    if not HAS_PIL:
        return None

    qimg = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    width = qimg.width()
    height = qimg.height()
    ptr = qimg.bits()
    data = bytes(ptr[: qimg.sizeInBytes()])
    return Image.frombytes("RGBA", (width, height), data)


def load_qimage(path: str) -> QImage:
    if HAS_PIL:
        pil_img = load_pil_image(path)
        if pil_img:
            return pil_to_qimage(pil_img)
    return QImage(path)


def create_checker_pixmap(tile_size: int = 8) -> QPixmap:
    checker_pixmap = QPixmap(tile_size * 2, tile_size * 2)
    checker_pixmap.fill(Qt.GlobalColor.white)

    painter = QPainter(checker_pixmap)
    gray_color = QColor(180, 180, 180)
    painter.fillRect(0, 0, tile_size, tile_size, gray_color)
    painter.fillRect(tile_size, tile_size, tile_size, tile_size, gray_color)
    painter.end()

    return checker_pixmap


def create_checker_item(tile_size: int = 8) -> QGraphicsRectItem:
    item = QGraphicsRectItem()
    item.setPen(QPen(Qt.PenStyle.NoPen))
    item.setBrush(QBrush(create_checker_pixmap(tile_size)))
    item.setZValue(-1)
    item.setVisible(False)
    return item


def clear_preview(pixmap_item, checker_item) -> None:
    if pixmap_item:
        pixmap_item.setPixmap(QPixmap())
    if checker_item:
        checker_item.setVisible(False)
