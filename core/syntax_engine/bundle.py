from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import re

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
        self._property_index: dict[str, dict[str, Any]] | None = None
        self._missing_property_ids: set[str] = set()
        self.validator = SchemaValidator(value_types, property_resolver=self.resolve_properties)

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
            if property_id not in self._missing_property_ids:
                print(f"Properties reference '{property_id}' is not defined by plugin schema assets. Ignored.")
                self._missing_property_ids.add(property_id)
            return {"property_id": property_id, "$ignore_validation": True}
        return schema

    def _load_property_index(self) -> dict[str, dict[str, Any]]:
        if self.base_path is None:
            raise ValueError("Properties references require a grammar base path.")

        result: dict[str, dict[str, Any]] = {}
        properties_root = self.base_path / "schemas" / "properties"
        if not properties_root.exists():
            return result

        for path in sorted(properties_root.rglob("*.json")):
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError(f"Schema asset must be a JSON object: {path}")
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
