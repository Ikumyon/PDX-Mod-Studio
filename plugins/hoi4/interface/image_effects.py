from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, qAlpha, qBlue, qGreen, qRed, qRgba

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from PIL import Image, ImageFilter
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


PIL_RESAMPLING_MODES = {
    "nearest": Image.Resampling.NEAREST if HAS_PIL else None,
    "bilinear": Image.Resampling.BILINEAR if HAS_PIL else None,
    "bicubic": Image.Resampling.BICUBIC if HAS_PIL else None,
    "lanczos": Image.Resampling.LANCZOS if HAS_PIL else None,
    "area": Image.Resampling.BOX if HAS_PIL else None,
}


def resize_pil(img: Image.Image, width: int, height: int, interpolation: str) -> Image.Image:
    if not HAS_PIL:
        return img

    resample = PIL_RESAMPLING_MODES.get(interpolation) or Image.Resampling.BILINEAR
    return img.convert("RGBA").resize((width, height), resample=resample)


def apply_alpha_mask_pil(
    img: Image.Image,
    mask_img: Image.Image,
    scale_percent: int,
    offset_x: int,
    offset_y: int,
    crop_outside: bool = True,
) -> Image.Image:
    img = img.convert("RGBA")
    mask_img = mask_img.convert("L")

    mask_w = max(1, int(img.width * scale_percent / 100.0))
    mask_h = max(1, int(img.height * scale_percent / 100.0))
    resized_mask = mask_img.resize((mask_w, mask_h), resample=Image.Resampling.BILINEAR)

    x_offset = (img.width - resized_mask.width) // 2 + offset_x
    y_offset = (img.height - resized_mask.height) // 2 + offset_y

    fill = 0 if crop_outside else 255
    full_mask = Image.new("L", img.size, fill)
    full_mask.paste(resized_mask, (x_offset, y_offset))

    rgba = np.array(img)
    mask_factor = np.array(full_mask, dtype=np.float32) / 255.0
    rgba[:, :, 3] = np.clip(rgba[:, :, 3].astype(np.float32) * mask_factor, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def selective_blur_cv2(img: Image.Image, radius: int, threshold: int) -> Image.Image:
    if not HAS_CV2:
        return img

    img = img.convert("RGBA")

    rgba = np.array(img)
    rgb = rgba[:, :, :3]
    d = max(1, radius * 2 + 1)
    if d % 2 == 0:
        d += 1
    blurred = cv2.bilateralFilter(
        rgb,
        d=d,
        sigmaColor=max(1, threshold),
        sigmaSpace=max(1, radius),
    )
    rgba[:, :, :3] = blurred
    return Image.fromarray(rgba, "RGBA")


def sharpen_cv2(img: Image.Image, strength: float) -> Image.Image:
    img = img.convert("RGBA")
    rgba = np.array(img)
    amount = max(0.0, float(strength) / 100.0)

    if HAS_CV2:
        rgb = rgba[:, :, :3]
        blurred = cv2.GaussianBlur(rgb, (0, 0), sigmaX=1.0)
        rgba[:, :, :3] = cv2.addWeighted(rgb, 1.0 + amount, blurred, -amount, 0)
    else:
        blurred = np.array(img.filter(ImageFilter.GaussianBlur(radius=1)))[:, :, :3]
        rgb = rgba[:, :, :3].astype(np.float32)
        rgba[:, :, :3] = np.clip(rgb + (rgb - blurred.astype(np.float32)) * amount, 0, 255).astype(np.uint8)

    return Image.fromarray(rgba, "RGBA")


def remove_background_cv2(img: Image.Image, key_color: QColor | None, tolerance: int, feather: int) -> Image.Image:
    if not key_color:
        return img

    img = img.convert("RGBA")
    rgba = np.array(img)
    key = np.array([key_color.red(), key_color.green(), key_color.blue()], dtype=np.int16)
    diff = np.max(np.abs(rgba[:, :, :3].astype(np.int16) - key), axis=2)

    alpha = rgba[:, :, 3].astype(np.float32)
    alpha[diff <= tolerance] = 0
    if feather > 0:
        feather_mask = (diff > tolerance) & (diff <= tolerance + feather)
        alpha[feather_mask] *= (diff[feather_mask] - tolerance) / feather
    rgba[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


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
    crop_outside: bool = True,
) -> QImage:
    if mask_img.isNull():
        return img

    mask_w = max(1, int(img.width() * scale_percent / 100.0))
    mask_h = max(1, int(img.height() * scale_percent / 100.0))
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

    if crop_outside:
        full_mask = np.zeros((img_h, img_w), dtype=np.uint8)
    else:
        full_mask = np.ones((img_h, img_w), dtype=np.uint8) * 255

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

    return QImage(img_np.data, img_w, img_h, QImage.Format.Format_ARGB32).copy()


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


def edge_enhance_cv2(
    img: Image.Image,
    method: str,
    threshold1: int,
    threshold2: int,
    strength: float,
    edge_color: QColor | None = None,
    edge_width: int = 1,
    edge_smooth: int = 1,
) -> Image.Image:
    if not HAS_CV2:
        return img

    img = img.convert("RGBA")
    rgba = np.array(img)
    rgb = rgba[:, :, :3]

    # グレースケール変換（エッジ検出用）
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    if method == "Canny":
        # Cannyエッジ検出
        edges = cv2.Canny(gray, threshold1, threshold2)
        edge_val = edges.astype(np.float32)

    elif method == "Sobel":
        # Sobelフィルタによるエッジ検出
        sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        sobel = np.sqrt(sobelx**2 + sobely**2)
        edge_val = np.clip(sobel, 0, 255).astype(np.float32)

    elif method == "Laplacian":
        # Laplacianによるエッジ検出
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        edge_val = np.clip(np.abs(laplacian), 0, 255).astype(np.float32)
    else:
        return img

    # エッジの太さ (膨張処理)
    if edge_width > 1:
        # モルフォロジー膨張処理用の構造要素（矩形）を作成
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (edge_width, edge_width))
        edge_val = cv2.dilate(edge_val, kernel)

    # エッジの平滑化（アンチエイリアシング効果）
    # ジャギー（ギザギザ）を軽減し、滑らかなエッジにするためガウシアンぼかしを適用
    if edge_smooth > 0:
        kernel_size = 2 * edge_smooth + 1
        edge_val = cv2.GaussianBlur(edge_val, (kernel_size, kernel_size), 0)

    # エッジの色配列 (R, G, B)
    if edge_color is not None:
        color_arr = np.array([edge_color.red(), edge_color.green(), edge_color.blue()], dtype=np.float32)
    else:
        color_arr = np.array([255, 255, 255], dtype=np.float32)

    # アルファブレンド（通常ブレンド）処理
    # エッジ強度 (0.0 〜 1.0) を計算
    strength_ratio = strength / 100.0
    alpha = (edge_val / 255.0) * strength_ratio
    alpha = np.expand_dims(alpha, axis=2) # 3チャンネルブロードキャスト用 (H, W, 1)

    # 通常ブレンド合成
    blend = rgb.astype(np.float32) * (1.0 - alpha) + color_arr * alpha
    rgba[:, :, :3] = np.clip(blend, 0, 255).astype(np.uint8)

    return Image.fromarray(rgba, "RGBA")

