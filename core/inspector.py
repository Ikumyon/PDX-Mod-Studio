import os
from enum import Enum
import core.pdx_inspector as pdx_inspector

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
    Rust の pdx_inspector を用いて、ファイルのバイナリ判定および最適な文字エンコーディングを返します。
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
        ft_int, enc_str = pdx_inspector.inspect_file(file_path)
        ft = FileType.Binary if ft_int == 1 else FileType.Text
        try:
            enc = EncodingType(enc_str)
        except ValueError:
            enc = EncodingType.Unknown
        return ft, enc
    except Exception:
        return FileType.Binary, EncodingType.Unknown
