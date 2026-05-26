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
    allow_assignment: bool
    allow_bare_values: bool

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SyntaxDefinition":
        syntax = _require_dict(raw, "syntax")
        tokens = _require_dict(syntax, "tokens", parent_name="syntax")
        whitespace = _require_dict(syntax, "whitespace", parent_name="syntax")
        block = _require_dict(syntax, "block", parent_name="syntax")
        statement = _require_dict(syntax, "statement", parent_name="syntax")
        return cls(
            name=_require_str(syntax, "name", parent_name="syntax"),
            assignment=_require_str(syntax, "assignment", parent_name="syntax"),
            block_open=_require_str(syntax, "block_open", parent_name="syntax"),
            block_close=_require_str(syntax, "block_close", parent_name="syntax"),
            comment=_require_str(syntax, "comment", parent_name="syntax"),
            string_quote=_require_str(tokens, "string_quote", parent_name="syntax.tokens"),
            escape=_require_str(tokens, "escape", parent_name="syntax.tokens"),
            newline_significant=_require_bool(whitespace, "newline_significant", parent_name="syntax.whitespace"),
            indent_significant=_require_bool(whitespace, "indent_significant", parent_name="syntax.whitespace"),
            children_by=_require_str(block, "children_by", parent_name="syntax.block"),
            allow_assignment=_require_bool(statement, "allow_assignment", parent_name="syntax.statement"),
            allow_bare_values=_require_bool(statement, "allow_bare_values", parent_name="syntax.statement"),
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

    def matches(self, value: str) -> bool:
        if self.literals:
            return value in self.literals
        if self.pattern:
            return re.fullmatch(self.pattern, value) is not None
        return True


@dataclass(slots=True)
class FileNode:
    kind: str
    children: list[Any]


@dataclass(slots=True)
class ChildrenNode:
    kind: str
    children: list[Any]


@dataclass(slots=True)
class ValueNode:
    kind: str
    value: str


@dataclass(slots=True)
class AssignmentNode:
    kind: str
    left: str
    operator: str
    right: ValueNode | ChildrenNode


@dataclass(slots=True)
class CommentNode:
    kind: str
    value: str


@dataclass(slots=True)
class Diagnostic:
    path: str
    message: str


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
