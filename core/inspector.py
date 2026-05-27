import os
from enum import Enum

class FileType(Enum):
    Binary = 1
    Text = 2

class EncodingType(Enum):
    Utf8 = "utf-8"
    Utf8Bom = "utf-8-sig"
    Utf16Le = "utf-16-le"
    Utf16Be = "utf-16-be"
    Cp932 = "cp932"
    Unknown = "unknown"

def inspect_file(file_path: str) -> tuple[FileType, EncodingType]:
    """
    ファイルをスキャンし、バイナリ判定および最適な文字エンコーディングを返します。
    将来的に PyO3 を用いて Rust 側に差し替え可能な設計です。
    """
    if not file_path or not os.path.exists(file_path):
        return FileType.Text, EncodingType.Unknown

    try:
        size = os.path.getsize(file_path)
        if size > 5 * 1024 * 1024:  # 5MBを超える巨大ファイルはテキストエディタで開くのを制限
            return FileType.Binary, EncodingType.Unknown
        if size == 0:
            return FileType.Text, EncodingType.Utf8
    except Exception:
        return FileType.Binary, EncodingType.Unknown

    try:
        # 先頭 8KB のみを読み込んで高速判定
        with open(file_path, "rb") as f:
            raw = f.read(8192)
    except Exception:
        return FileType.Binary, EncodingType.Unknown

    # 1. BOM判定
    if raw.startswith(b"\xef\xbb\xbf"):
        return FileType.Text, EncodingType.Utf8Bom
    if raw.startswith(b"\xff\xfe"):
        return FileType.Text, EncodingType.Utf16Le
    if raw.startswith(b"\xfe\xff"):
        return FileType.Text, EncodingType.Utf16Be

    # 2. バイナリ判定 (ヌルバイトチェック)
    if b"\x00" in raw:
        return FileType.Binary, EncodingType.Unknown

    # 3. UTF-8 バリデーション
    try:
        raw.decode("utf-8")
        return FileType.Text, EncodingType.Utf8
    except UnicodeDecodeError:
        pass

    # 4. CP932 / Shift_JIS 検証
    try:
        raw.decode("cp932")
        return FileType.Text, EncodingType.Cp932
    except UnicodeDecodeError:
        pass

    return FileType.Text, EncodingType.Unknown
