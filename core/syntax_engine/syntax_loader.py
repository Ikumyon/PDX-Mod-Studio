from __future__ import annotations

from pathlib import Path
from typing import Any


class SyntaxAssetLoader:
    """
    静的な構文アセットのロードを担当するローダー。
    旧 TOML 形式の読み込み処理は完全に廃止されています。
    """

    def __init__(self) -> None:
        pass

    def load_syntax_manifest(self, plugin_path: str | Path, manifest_data: dict[str, Any]) -> dict[str, Any]:
        """
        マニフェストからの構文アセットロード処理。
        旧方式の廃止に伴い、現在は空のロード結果を返します。
        """
        return {}
