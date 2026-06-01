from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import re

from .loader import load_toml_file, load_value_types
from .models import FileNode, SyntaxDefinition, ValidationResult, ValueTypeRule
from .parser import GenericTextParser
from .plugin_files import load_plugin_file_map, require_plugin_file, resolve_file_map_path
from .schema import SchemaValidator


class GrammarBundle:
    def __init__(
        self,
        syntax: SyntaxDefinition,
        value_types: dict[str, ValueTypeRule],
        asset_root: str | Path | None = None,
        property_search_roots: list[str | Path] | None = None,
    ):
        self.syntax = syntax
        self.value_types = value_types
        self.asset_root = Path(asset_root).resolve() if asset_root else None
        self.property_search_roots = [
            Path(path).resolve() for path in (property_search_roots or ([] if self.asset_root is None else [self.asset_root]))
        ]
        self.parser = GenericTextParser(syntax)
        self._property_index: dict[str, dict[str, Any]] | None = None
        self.validator = SchemaValidator(value_types, property_resolver=self.resolve_properties)

    @classmethod
    def from_paths(
        cls,
        syntax_path: str | Path,
        values_path: str | Path,
    ) -> "GrammarBundle":
        syntax_data = load_toml_file(syntax_path)
        values_data = load_toml_file(values_path)
        asset_root = Path(syntax_path).resolve().parent
        return cls(
            syntax=SyntaxDefinition.from_dict(syntax_data),
            value_types=load_value_types(values_data),
            asset_root=asset_root,
        )

    @classmethod
    def from_plugin_assets(
        cls,
        plugin_root: str | Path,
        manifest: dict[str, Any],
        plugin_id: str,
        syntax_key: str = "grammar.syntax",
        values_key: str = "grammar.values",
    ) -> "GrammarBundle":
        file_map = load_plugin_file_map(plugin_root, manifest, plugin_id)
        syntax_path = resolve_file_map_path(file_map, syntax_key)
        values_path = resolve_file_map_path(file_map, values_key)
        syntax_data = load_toml_file(require_plugin_file(plugin_root, syntax_path, "syntax"))
        values_data = load_toml_file(require_plugin_file(plugin_root, values_path, "values"))
        return cls(
            syntax=SyntaxDefinition.from_dict(syntax_data),
            value_types=load_value_types(values_data),
            asset_root=plugin_root,
        )

    def load_schema(self, schema_path: str | Path) -> dict[str, Any]:
        candidate = Path(schema_path)
        if not candidate.is_absolute():
            if self.asset_root is None:
                raise ValueError("Schema loading requires a base path.")
            candidate = (self.asset_root / candidate).resolve()
        with open(candidate, "r", encoding="utf-8") as handle:
            schema_text = handle.read()
        schema = json.loads(schema_text)
        
        try:
            self.validator.check_schema_integrity(schema)
        except ValueError as error:
            raise ValueError(self._format_schema_error(error, candidate, schema_text)) from error
        return schema

    def _format_schema_error(self, error: ValueError, schema_path: Path, schema_text: str) -> str:
        message = str(error)
        path = self._schema_error_path(message)
        line = self._schema_path_line(schema_text, path)
        location = str(schema_path)
        if line is not None:
            location = f"{location}:{line}"
        return f"{message}\nFile: {location}"

    def _schema_error_path(self, message: str) -> str | None:
        match = re.search(r"Schema definition error at '([^']+)'", message)
        if not match:
            return None
        return match.group(1)

    def _schema_path_line(self, schema_text: str, path: str | None) -> int | None:
        if not path:
            return None
        keys = [part for part in path.replace("[]", "").split(".") if part and part != "$"]
        search_keys = [key for key in keys if key not in {"select", "left", "right"}]
        if not search_keys:
            search_keys = keys
        for key in reversed(search_keys):
            line = self._json_key_line(schema_text, key)
            if line is not None:
                return line
        return None

    def _json_key_line(self, schema_text: str, key: str) -> int | None:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:')
        for index, line in enumerate(schema_text.splitlines(), start=1):
            if pattern.search(line):
                return index
        return None

    def resolve_properties(self, property_id: str) -> dict[str, Any]:
        if self._property_index is None:
            self._property_index = self._load_property_index()
        schema = self._property_index.get(property_id)
        if schema is None:
            raise ValueError(f"Properties reference '{property_id}' is not defined by plugin schema assets.")
        return schema

    def _load_property_index(self) -> dict[str, dict[str, Any]]:
        if not self.property_search_roots:
            raise ValueError("Properties references require a grammar base path.")

        result: dict[str, dict[str, Any]] = {}
        for root in self.property_search_roots:
            if not root.exists():
                raise FileNotFoundError(f"Property search root not found: {root}")
            for path in sorted(root.rglob("*.json")):
                with open(path, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if not isinstance(data, dict):
                    continue
                property_id = data.get("property_id")
                if property_id is None:
                    continue
                if not isinstance(property_id, str) or not property_id:
                    raise ValueError(f"Invalid property_id in schema asset: {path}")
                if property_id in result:
                    raise ValueError(f"Duplicate property_id '{property_id}' in schema assets.")
                result[property_id] = data
        return result

    def parse(self, text: str) -> FileNode:
        return self.parser.parse(text)

    def validate(self, text: str, schema: dict[str, Any]) -> ValidationResult:
        ast = self.parse(text)
        return self.validator.validate(ast, schema)

    def validate_schema_path(self, text: str, schema_path: str | Path) -> ValidationResult:
        return self.validate(text, self.load_schema(schema_path))
