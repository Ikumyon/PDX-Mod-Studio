import core.pdx_inspector as pdx_inspector

def autodetect_encoding(raw: bytes) -> str:
    """バイト列から Rust を用いてエンコーディングを判定します"""
    try:
        return pdx_inspector.detect_encoding(raw)
    except Exception:
        return "unknown"

def decode_with_encoding(raw: bytes, encoding: str) -> tuple[str, str]:
    """指定されたエンコーディングで Rust を用いてデコードします。結果の文字列と、実際に使用されたエンコーディング名を返します"""
    try:
        content = pdx_inspector.decode(raw, encoding)
        return content, encoding
    except Exception:
        # 万が一失敗した場合は UTF-8 デコードを試みる
        try:
            return pdx_inspector.decode(raw, "utf-8"), "utf-8"
        except Exception:
            return raw.decode("latin-1", errors="ignore"), "latin-1"

def detect_text_encoding(raw: bytes) -> tuple[str, str]:
    """バイト列から Rust を用いて自動判定し、デコードしたテキストとエンコーディング名を返します"""
    enc = autodetect_encoding(raw)
    if enc == "unknown":
        enc = "utf-8"
    return decode_with_encoding(raw, enc)

def read_text_with_detected_encoding(file_path: str) -> tuple[str, str]:
    """ファイルをバイナリで読み込み、Rust を用いてデコードします"""
    with open(file_path, "rb") as handle:
        raw = handle.read()
    return detect_text_encoding(raw)

def reopen_text_widget_with_encoding(widget, encoding: str) -> bool:
    """エディタウィジェットの内容を指定のエンコーディングで Rust を用いて再読み込みします"""
    file_path = getattr(widget, "file_path", "")
    if not file_path or str(file_path).startswith("untitled:"):
        widget.file_encoding = encoding
        return True

    with open(file_path, "rb") as handle:
        raw = handle.read()

    text, normalized_encoding = decode_with_encoding(raw, encoding)
    widget.blockSignals(True)
    try:
        widget.setPlainText(text)
    finally:
        widget.blockSignals(False)
    widget.file_encoding = normalized_encoding
    return True
