from __future__ import annotations

from typing import Any

from .models import FileNode, ValidationResult, ValueTypeRule


class SchemaValidator:
    def __init__(self, value_types: dict[str, ValueTypeRule]):
        self.value_types = value_types

    def validate(self, ast: FileNode, schema: dict[str, Any]) -> ValidationResult:
        return ValidationResult(ast=ast, diagnostics=[], records=[])

