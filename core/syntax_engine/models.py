from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any


@dataclass(slots=True)
class SyntaxDefinition:
    name: str
    assignment: str
    block_open: str
    block_close: str
    comment: str
    string_quotes: list[str]
    escape: str
    comparison_operators: list[str]
    newline_significant: bool
    children_by: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SyntaxDefinition":
        syntax = _require_dict(raw, "syntax")
        tokens = _require_dict(syntax, "tokens", parent_name="syntax")
        whitespace = _require_dict(syntax, "whitespace", parent_name="syntax")
        children = _require_dict(syntax, "children", parent_name="syntax.children")
        return cls(
            name=_require_str(syntax, "name", parent_name="syntax"),
            assignment=_require_str(syntax, "assignment", parent_name="syntax"),
            block_open=_require_str(children, "open", parent_name="syntax.children"),
            block_close=_require_str(children, "close", parent_name="syntax.children"),
            comment=_require_str(syntax, "comment", parent_name="syntax"),
            string_quotes=_require_list_str(tokens, "string_quotes", parent_name="syntax.tokens"),
            escape=_require_str(tokens, "escape", parent_name="syntax.tokens"),
            comparison_operators=_require_list_str(tokens, "comparison_operators", parent_name="syntax.tokens"),
            newline_significant=_require_bool(whitespace, "newline_significant", parent_name="syntax.whitespace"),
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


def _require_list_str(container: dict[str, Any], key: str, parent_name: str) -> list[str]:
    value = container.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Missing or invalid '{parent_name}.{key}' list of strings in syntax definition.")
    return value


@dataclass(slots=True)
class ValueTypeRule:
    name: str
    pattern: str | None = None
    literals: list[str] = field(default_factory=list)
    literals_from: bool = False
    children: bool = False
    min: int | float | Decimal | None = None
    max: int | float | Decimal | None = None
    fixed_point_scale: int | None = None
    min_max_severity: str = "warning"

    def normalize_value(self, value: Any, allowed_values: list[Any] | None = None) -> Any:
        value_text = str(value)
        if self.children:
            return value
        if self.fixed_point_scale is not None:
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            return self._parse_fixed_point(value_text)
        if self.min is not None or self.max is not None:
            return Decimal(value_text)
        return value_text

    def validate(self, value: Any, allowed_values: list[Any] | None = None) -> tuple[bool, str | None, str]:
        value_text = str(value)
        normalized_fixed_value = self.fixed_point_scale is not None and isinstance(value, int) and not isinstance(value, bool)
        if self.children:
            return False, "grammar.error.type_mismatch", "error"
        if self.literals_from:
            if allowed_values is None:
                return True, None, "error"
            if value_text in {str(item) for item in allowed_values}:
                return True, None, "error"
            return False, "grammar.error.type_mismatch", "error"
        if self.literals:
            if value_text in self.literals:
                return True, None, "error"
            return False, "grammar.error.type_mismatch", "error"
        
        # 1. 正規表現パターンマッチング
        if self.pattern and not normalized_fixed_value:
            if re.fullmatch(self.pattern, value_text) is None:
                return False, "grammar.error.type_mismatch", "error"
        
        # 2. 数値範囲（min / max）チェック
        if self.fixed_point_scale is not None:
            try:
                num = self.normalize_value(value, allowed_values=allowed_values)
            except (InvalidOperation, ValueError):
                return False, "grammar.error.type_mismatch", "error"

        elif self.min is not None or self.max is not None:
            try:
                num = self.normalize_value(value, allowed_values=allowed_values)
            except (InvalidOperation, ValueError):
                return False, "grammar.error.type_mismatch", "error"
        else:
            return True, None, "error"

        if (self.min is not None and num < self.min) or (self.max is not None and num > self.max):
            limits = []
            if self.min is not None:
                limits.append(f"min={self._format_limit(self.min)}")
            if self.max is not None:
                limits.append(f"max={self._format_limit(self.max)}")
            limits_str = ", ".join(limits)
            error_msg = f"grammar.error.range_out_of_bounds({limits_str})"
            return False, error_msg, self.min_max_severity

        return True, None, "error"

    def _parse_fixed_point(self, value_text: str) -> int:
        if self.fixed_point_scale is None:
            raise ValueError("Fixed-point scale is not defined.")
        scale_digits = self._fixed_scale_digits()
        text = value_text.strip()
        sign = -1 if text.startswith("-") else 1
        if text[:1] in {"-", "+"}:
            text = text[1:]
        whole_text, dot, fraction_text = text.partition(".")
        if not whole_text:
            raise ValueError("Fixed-point value is missing a whole part.")
        whole = int(whole_text)
        fraction = 0
        if dot:
            if len(fraction_text) > scale_digits:
                raise ValueError(f"Fixed-point value has more than {scale_digits} decimal places.")
            padded = fraction_text.ljust(scale_digits, "0")
            fraction = int(padded) if padded else 0
        return sign * ((whole * self.fixed_point_scale) + fraction)

    def _format_fixed_point(self, value: int) -> str:
        if self.fixed_point_scale is None:
            return str(value)
        scale_digits = self._fixed_scale_digits()
        sign = "-" if value < 0 else ""
        abs_value = abs(value)
        whole, fraction = divmod(abs_value, self.fixed_point_scale)
        if fraction == 0:
            return f"{sign}{whole}"
        return f"{sign}{whole}.{fraction:0{scale_digits}d}"

    def _format_limit(self, value: Any) -> str:
        if self.fixed_point_scale is not None and isinstance(value, int) and not isinstance(value, bool):
            return self._format_fixed_point(value)
        return str(value)

    def _fixed_scale_digits(self) -> int:
        if self.fixed_point_scale is None:
            raise ValueError("Fixed-point scale is not defined.")
        return len(str(self.fixed_point_scale)) - 1



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
    value: Any
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
    suggestions: list[dict[str, str]] = field(default_factory=list)


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
