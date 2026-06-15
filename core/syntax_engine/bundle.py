from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import FileNode, SyntaxDefinition, ValidationResult
from .parser import GenericTextParser
from .plugin_files import load_plugin_file_map, resolve_file_map_path, require_plugin_file


class SyntaxBundle:
    def __init__(
        self,
        syntax: SyntaxDefinition | None = None,
        asset_root: str | Path | None = None,
        rules_dir: Path | None = None,
    ):
        self.syntax = syntax
        self.asset_root = Path(asset_root).resolve() if asset_root else None
        self.rules_dir = rules_dir
        if syntax:
            self.parser = GenericTextParser(syntax)
        else:
            self.parser = None

    @classmethod
    def from_plugin_assets(
        cls,
        plugin_root: str | Path,
        manifest: dict[str, Any],
        plugin_id: str,
    ) -> "SyntaxBundle":
        file_map = load_plugin_file_map(plugin_root, manifest, plugin_id)

        # syntax.toml のロード
        syntax_rel_path = resolve_file_map_path(file_map, "syntax.syntax")
        syntax_file = require_plugin_file(plugin_root, syntax_rel_path, "syntax definition")
        
        with open(syntax_file, "rb") as handle:
            import tomllib
            syntax_data = tomllib.load(handle)
        syntax_def = SyntaxDefinition.from_dict(syntax_data)

        # rules フォルダパスの解決
        directory_rel_path = resolve_file_map_path(file_map, "syntax.directory")
        rules_dir = (Path(plugin_root) / directory_rel_path).resolve()
        if not rules_dir.is_dir():
            raise FileNotFoundError(f"Required rules directory not found: {rules_dir}")

        return cls(
            syntax=syntax_def,
            asset_root=plugin_root,
            rules_dir=rules_dir,
        )

    def parse(self, text: str) -> FileNode:
        if self.parser:
            return self.parser.parse(text)
        return FileNode(kind="file", children=[])

    def validate(self, text: str, schema: dict[str, Any]) -> ValidationResult:
        ast = self.parse(text)
        return ValidationResult(ast=ast, diagnostics=[], records=[])

    def validate_schema_path(self, text: str, schema_path: str | Path) -> ValidationResult:
        return self.validate(text, {})
