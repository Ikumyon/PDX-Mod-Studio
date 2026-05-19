from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, qAlpha, qBlue, qGreen, qRed, qRgba


def selective_blur(img: QImage, radius: int, threshold: int) -> QImage:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    width = img.width()
    height = img.height()
    out = QImage(width, height, QImage.Format.Format_ARGB32)

    for y in range(height):
        for x in range(width):
            center_pixel = img.pixel(x, y)
            r0 = qRed(center_pixel)
            g0 = qGreen(center_pixel)
            b0 = qBlue(center_pixel)
            a0 = qAlpha(center_pixel)

            sum_r, sum_g, sum_b, sum_a = 0, 0, 0, 0
            total_weight = 0

            for dy in range(-radius, radius + 1):
                ny = y + dy
                if ny < 0 or ny >= height:
                    continue
                for dx in range(-radius, radius + 1):
                    nx = x + dx
                    if nx < 0 or nx >= width:
                        continue

                    dist_sq = dx * dx + dy * dy
                    if dist_sq > radius * radius:
                        continue

                    pixel = img.pixel(nx, ny)
                    r = qRed(pixel)
                    g = qGreen(pixel)
                    b = qBlue(pixel)
                    a = qAlpha(pixel)

                    max_diff = max(abs(r - r0), abs(g - g0), abs(b - b0))

                    if max_diff <= threshold:
                        weight = 1.0 / (1.0 + dist_sq * 0.5)
                        sum_r += r * weight
                        sum_g += g * weight
                        sum_b += b * weight
                        sum_a += a * weight
                        total_weight += weight

            if total_weight > 0:
                new_r = int(sum_r / total_weight)
                new_g = int(sum_g / total_weight)
                new_b = int(sum_b / total_weight)
                new_a = int(sum_a / total_weight)
                out.setPixel(x, y, qRgba(new_r, new_g, new_b, new_a))
            else:
                out.setPixel(x, y, center_pixel)

    return out


def sharpen(img: QImage, strength: float) -> QImage:
    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    width = img.width()
    height = img.height()
    out = QImage(width, height, QImage.Format.Format_ARGB32)
    factor = strength / 100.0

    for y in range(height):
        for x in range(width):
            if x == 0 or x == width - 1 or y == 0 or y == height - 1:
                out.setPixel(x, y, img.pixel(x, y))
                continue

            center = img.pixel(x, y)
            r0 = qRed(center)
            g0 = qGreen(center)
            b0 = qBlue(center)
            a0 = qAlpha(center)

            up = img.pixel(x, y - 1)
            down = img.pixel(x, y + 1)
            left = img.pixel(x - 1, y)
            right = img.pixel(x + 1, y)

            sum_r = 4 * r0 - qRed(up) - qRed(down) - qRed(left) - qRed(right)
            sum_g = 4 * g0 - qGreen(up) - qGreen(down) - qGreen(left) - qGreen(right)
            sum_b = 4 * b0 - qBlue(up) - qBlue(down) - qBlue(left) - qBlue(right)

            new_r = max(0, min(255, int(r0 + sum_r * factor)))
            new_g = max(0, min(255, int(g0 + sum_g * factor)))
            new_b = max(0, min(255, int(b0 + sum_b * factor)))

            out.setPixel(x, y, qRgba(new_r, new_g, new_b, a0))

    return out


def remove_background(img: QImage, key_color: QColor | None, tolerance: int, feather: int) -> QImage:
    if not key_color:
        return img

    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    width = img.width()
    height = img.height()
    out = QImage(width, height, QImage.Format.Format_ARGB32)

    bg_r = key_color.red()
    bg_g = key_color.green()
    bg_b = key_color.blue()

    for y in range(height):
        for x in range(width):
            pixel = img.pixel(x, y)
            r = qRed(pixel)
            g = qGreen(pixel)
            b = qBlue(pixel)
            a = qAlpha(pixel)

            diff = max(abs(r - bg_r), abs(g - bg_g), abs(b - bg_b))

            if diff <= tolerance:
                new_a = 0
            elif feather > 0 and diff <= (tolerance + feather):
                ratio = (diff - tolerance) / feather
                new_a = int(a * ratio)
            else:
                new_a = a

            out.setPixel(x, y, qRgba(r, g, b, new_a))

    return out


def apply_alpha_mask(
    img: QImage,
    mask_img: QImage,
    scale_percent: int,
    offset_x: int,
    offset_y: int,
) -> QImage:
    if mask_img.isNull():
        return img

    mask_w = max(1, int(mask_img.width() * scale_percent / 100.0))
    mask_h = max(1, int(mask_img.height() * scale_percent / 100.0))
    resized_mask = mask_img.scaled(
        mask_w,
        mask_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    x_offset = (img.width() - resized_mask.width()) // 2 + offset_x
    y_offset = (img.height() - resized_mask.height()) // 2 + offset_y

    img = img.convertToFormat(QImage.Format.Format_ARGB32)
    img_w, img_h = img.width(), img.height()

    ptr = img.bits()
    img_np = np.array(ptr).reshape((img_h, img_w, 4))

    resized_mask = resized_mask.convertToFormat(QImage.Format.Format_ARGB32)
    mask_ptr = resized_mask.bits()
    mask_np = np.array(mask_ptr).reshape((resized_mask.height(), resized_mask.width(), 4))
    mask_gray = mask_np[:, :, 2]

    full_mask = np.zeros((img_h, img_w), dtype=np.uint8)

    m_y1 = max(0, -y_offset)
    m_x1 = max(0, -x_offset)
    m_y2 = min(resized_mask.height(), img_h - y_offset)
    m_x2 = min(resized_mask.width(), img_w - x_offset)

    d_y1 = max(0, y_offset)
    d_x1 = max(0, x_offset)
    d_y2 = min(img_h, y_offset + resized_mask.height())
    d_x2 = min(img_w, x_offset + resized_mask.width())

    if m_y2 > m_y1 and m_x2 > m_x1:
        full_mask[d_y1:d_y2, d_x1:d_x2] = mask_gray[m_y1:m_y2, m_x1:m_x2]

    alpha = img_np[:, :, 3].astype(np.float32)
    mask_factor = full_mask.astype(np.float32) / 255.0
    img_np[:, :, 3] = np.clip(alpha * mask_factor, 0, 255).astype(np.uint8)

    return QImage(img_np.data, img_w, img_h, QImage.Format.Format_RGBA8888).copy()


def adjust_hsl(bgr_img, h_shift: int, s_shift: int, l_shift: int) -> np.ndarray:
    import cv2

    hls = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HLS).astype("float32")
    if h_shift != 0:
        hls[:, :, 0] = (hls[:, :, 0] + h_shift) % 180
    if s_shift != 0:
        hls[:, :, 2] = np.clip(hls[:, :, 2] + s_shift, 0, 255)
    if l_shift != 0:
        hls[:, :, 1] = np.clip(hls[:, :, 1] + l_shift, 0, 255)
    return cv2.cvtColor(hls.astype("uint8"), cv2.COLOR_HLS2BGR)
