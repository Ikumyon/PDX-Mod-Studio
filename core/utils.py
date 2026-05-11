from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QByteArray, QSize

def load_svg_icon(path, color_hex):
    """
    SVGファイル内の currentColor を指定した色に置換して QIcon を返す。
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            svg_data = f.read()
            
        # currentColor を置換
        svg_data = svg_data.replace('currentColor', color_hex)
        
        # QSvgRenderer を使用して描画
        renderer = QSvgRenderer(QByteArray(svg_data.encode('utf-8')))
        if not renderer.isValid():
            return QIcon(path) # 失敗した場合は元のファイルをそのまま返す
            
        # 標準的なアイコンサイズ（16x16 or 24x24）で Pixmap を作成
        size = QSize(24, 24)
        pixmap = QPixmap(size)
        pixmap.fill(QColor(0, 0, 0, 0)) # 透明で塗りつぶし
        
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        
        return QIcon(pixmap)
    except Exception as e:
        print(f"SVGアイコンのロードに失敗しました: {e}")
        return QIcon(path)
