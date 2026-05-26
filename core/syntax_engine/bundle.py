from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from .loader import load_toml_file, load_value_types
from .models import FileNode, SyntaxDefinition, ValidationResult, ValueTypeRule
from .parser import GenericTextParser
from .plugin_files import resolve_file_map_path
from .schema import SchemaValidator


class GrammarBundle:
    def __init__(
        self,
        syntax: SyntaxDefinition,
        value_types: dict[str, ValueTypeRule],
        base_path: str | Path | None = None,
    ):
        self.syntax = syntax
        self.value_types = value_types
        self.base_path = Path(base_path) if base_path else None
        self.parser = GenericTextParser(syntax)
        self.validator = SchemaValidator(value_types)

    @classmethod
    def from_paths(
        cls,
        syntax_path: str | Path,
        values_path: str | Path,
    ) -> "GrammarBundle":
        syntax_data = load_toml_file(syntax_path)
        values_data = load_toml_file(values_path)
        base_path = Path(syntax_path).resolve().parent
        return cls(
            syntax=SyntaxDefinition.from_dict(syntax_data),
            value_types=load_value_types(values_data),
            base_path=base_path,
        )

    @classmethod
    def from_plugin(
        cls,
        plugin: Any,
        syntax_key: str = "grammar.syntax",
        values_key: str = "grammar.values",
    ) -> "GrammarBundle":
        file_map = plugin.get_manifest_file_map()
        syntax_path = resolve_file_map_path(file_map, syntax_key)
        values_path = resolve_file_map_path(file_map, values_key)
        syntax_data = plugin.read_toml_asset(syntax_path)
        values_data = plugin.read_toml_asset(values_path)
        return cls(
            syntax=SyntaxDefinition.from_dict(syntax_data),
            value_types=load_value_types(values_data),
            base_path=Path(plugin.resolve_path("grammar")),
        )

    def load_schema(self, schema_path: str | Path) -> dict[str, Any]:
        candidate = Path(schema_path)
        if not candidate.is_absolute():
            if candidate.exists():
                candidate = candidate.resolve()
            elif self.base_path is not None:
                if candidate.parts and candidate.parts[0] == "grammar":
                    candidate = (self.base_path.parent / candidate).resolve()
                else:
                    candidate = (self.base_path / candidate).resolve()
            else:
                raise ValueError("Schema loading requires a base path.")
        with open(candidate, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def parse(self, text: str) -> FileNode:
        return self.parser.parse(text)

    def validate(self, text: str, schema: dict[str, Any]) -> ValidationResult:
        ast = self.parse(text)
        return self.validator.validate(ast, schema)

    def validate_schema_path(self, text: str, schema_path: str | Path) -> ValidationResult:
        return self.validate(text, self.load_schema(schema_path))
