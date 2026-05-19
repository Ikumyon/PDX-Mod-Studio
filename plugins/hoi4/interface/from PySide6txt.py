from PySide6.QtGui import QImageReader

# サポートされているフォーマットのリストを取得して文字列に変換
formats = [f.data().decode('utf-8') for f in QImageReader.supportedImageFormats()]
print("【読み込み対応フォーマット一覧】")
print(", ".join(sorted(formats)))
