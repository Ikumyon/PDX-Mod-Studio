from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .plugin_files import require_plugin_file, resolve_file_map_path


class GrammarAssetLoader:
    """
    静的な文法アセットのロードを担当するローダー。
    TOML構造の読み込みと言語モード定義のパース処理を行います。
    """

    def __init__(self) -> None:
        pass

    def load_grammar_manifest(self, plugin_path: str | Path, manifest_data: dict[str, Any]) -> dict[str, Any]:
        """
        マニフェストから 'grammar_modes' の定義を取得し、実ファイル (TOML) を読み込みます。
        各 grammar_modes の要素について id, name_key, path の必須キーを検証し、
        ロード結果の辞書構造を返します。
        """
        grammar_modes_path = manifest_data.get("grammar_modes")
        if not grammar_modes_path:
            return {}

        if not isinstance(grammar_modes_path, str):
            raise ValueError(
                f"Invalid 'grammar_modes' in plugin manifest. Expected string, got {type(grammar_modes_path).__name__}."
            )

        full_path = require_plugin_file(plugin_path, grammar_modes_path, "grammar modes")

        # TOMLファイルのパース
        with open(full_path, "rb") as handle:
            try:
                data = tomllib.load(handle)
            except Exception as e:
                raise ValueError(f"Failed to parse TOML at '{full_path}': {e}")

        # 必須セクションおよび構造の検証
        grammar = data.get("grammar")
        if not isinstance(grammar, dict):
            raise ValueError(f"Missing or invalid '[grammar]' section in '{full_path}'.")
        syntax_path = resolve_file_map_path(data, "grammar.syntax")
        values_path = resolve_file_map_path(data, "grammar.values")
        require_plugin_file(plugin_path, syntax_path, "syntax")
        require_plugin_file(plugin_path, values_path, "values")

        # grammar_modes リストの検証
        modes = data.get("grammar_modes")
        if not isinstance(modes, list):
            raise ValueError(f"Missing or invalid '[[grammar_modes]]' list in '{full_path}'.")

        validated_modes = []
        for index, mode in enumerate(modes):
            if not isinstance(mode, dict):
                raise ValueError(f"Grammar mode at index {index} in '{full_path}' must be an object.")
            
            # 必須属性の存在チェック
            mode_id = mode.get("id")
            name_key = mode.get("name_key")
            path_pattern = mode.get("path")
            schema_path = mode.get("schema")
            extension = mode.get("extension")
            encoding = mode.get("encoding")

            if not isinstance(mode_id, str) or not mode_id:
                raise ValueError(f"Grammar mode at index {index} in '{full_path}' is missing a valid 'id'.")
            if not isinstance(name_key, str) or not name_key:
                raise ValueError(f"Grammar mode '{mode_id}' is missing a valid 'name_key'.")
            if not isinstance(path_pattern, str) or not path_pattern:
                raise ValueError(f"Grammar mode '{mode_id}' is missing a valid 'path'.")
            if not isinstance(schema_path, str) or not schema_path:
                raise ValueError(f"Grammar mode '{mode_id}' is missing a valid 'schema'.")
            if not isinstance(extension, str) or not extension:
                raise ValueError(f"Grammar mode '{mode_id}' is missing a valid 'extension'.")
            if not isinstance(encoding, str) or not encoding:
                raise ValueError(f"Grammar mode '{mode_id}' is missing a valid 'encoding'.")
            require_plugin_file(plugin_path, schema_path, f"schema for grammar mode '{mode_id}'")

            validated_modes.append(mode)

        return {
            "grammar_modes_path": str(full_path),
            "loaded": True,
            "grammar": grammar,
            "i18n": data.get("i18n") or {},
            "modes": validated_modes,
        }
