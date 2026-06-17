from __future__ import annotations

from pathlib import Path
from typing import Any

from .bundle import SyntaxBundle


class SyntaxAssetLoader:
    """
    静的な構文アセットのロードを担当するローダー。
    構文資産は必ずプラグイン側の実ファイルから読み込みます。
    """

    def __init__(self) -> None:
        pass

    def load_syntax_manifest(self, plugin_path: str | Path, manifest_data: dict[str, Any]) -> SyntaxBundle:
        """
        マニフェストから構文アセットを読み込む。

        必須ファイルや必須項目が無い場合は、呼び出し元へ例外を返します。
        コア側で既定値を補完しません。
        """
        plugin_id = manifest_data.get("id")
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ValueError("Plugin manifest is missing the required 'id' string.")
        return SyntaxBundle.from_plugin_assets(plugin_path, manifest_data, plugin_id)
