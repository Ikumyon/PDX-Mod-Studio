from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(slots=True)
class SyntaxDefinition:
    name: str
    assignment: str
    block_open: str
    block_close: str
    comment: str
    string_quote: str
    escape: str
    newline_significant: bool
    indent_significant: bool
    children_by: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SyntaxDefinition":
        syntax = _require_dict(raw, "syntax")
        tokens = _require_dict(syntax, "tokens", parent_name="syntax")
        whitespace = _require_dict(syntax, "whitespace", parent_name="syntax")
        children = _require_dict(syntax, "children", parent_name="syntax")
        return cls(
            name=_require_str(syntax, "name", parent_name="syntax"),
            assignment=_require_str(syntax, "assignment", parent_name="syntax"),
            block_open=_require_str(children, "open", parent_name="syntax.children"),
            block_close=_require_str(children, "close", parent_name="syntax.children"),
            comment=_require_str(syntax, "comment", parent_name="syntax"),
            string_quote=_require_str(tokens, "string_quote", parent_name="syntax.tokens"),
            escape=_require_str(tokens, "escape", parent_name="syntax.tokens"),
            newline_significant=_require_bool(whitespace, "newline_significant", parent_name="syntax.whitespace"),
            indent_significant=_require_bool(whitespace, "indent_significant", parent_name="syntax.whitespace"),
            children_by=_require_str(children, "children_by", parent_name="syntax.children"),
        )


def _require_dict(container: dict[str, Any], key: str, parent_name: str = "root") -> dict[str, Any]:
    value = container.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Missing or invalid '{parent_name}.{key}' object in syntax definition.")
    return value


def _require_str(container: dict[str, Any], key: str, parent_name: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing or invalid '{parent_name}.{key}' string in syntax definition.")
    return value


def _require_bool(container: dict[str, Any], key: str, parent_name: str) -> bool:
    value = container.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Missing or invalid '{parent_name}.{key}' boolean in syntax definition.")
    return value


@dataclass(slots=True)
class ValueTypeRule:
    name: str
    pattern: str | None = None
    literals: list[str] = field(default_factory=list)
    literals_from: bool = False
    children: bool = False

    def matches(self, value: str, allowed_values: list[Any] | None = None) -> bool:
        if self.children:
            return False
        if self.literals_from:
            if allowed_values is None:
                return True
            return value in {str(item) for item in allowed_values}
        if self.literals:
            return value in self.literals
        if self.pattern:
            return re.fullmatch(self.pattern, value) is not None
        return True


@dataclass(slots=True)
class FileNode:
    kind: str
    children: list[Any]
    line: int = 1
    column: int = 1
    length: int = 1


@dataclass(slots=True)
class ChildrenNode:
    kind: str
    children: list[Any]
    line: int = 1
    column: int = 1
    length: int = 1


@dataclass(slots=True)
class ValueNode:
    kind: str
    value: str
    line: int = 1
    column: int = 1
    length: int = 1


@dataclass(slots=True)
class AssignmentNode:
    kind: str
    left: str
    operator: str
    right: ValueNode | ChildrenNode
    line: int = 1
    column: int = 1
    length: int = 1


@dataclass(slots=True)
class CommentNode:
    kind: str
    value: str
    line: int = 1
    column: int = 1
    length: int = 1


@dataclass(slots=True)
class Diagnostic:
    path: str
    message: str
    severity: str = "error"
    line: int = 1
    column: int = 1
    length: int = 1


@dataclass(slots=True)
class ValidationResult:
    ast: FileNode
    diagnostics: list[Diagnostic]
    records: list[dict[str, str]]

    @property
    def is_valid(self) -> bool:
        return not self.diagnostics


@dataclass(slots=True)
class Token:
    kind: str
    value: str
    line: int
    column: int
