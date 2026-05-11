from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .model import SourceRange


@dataclass
class AstNode:
    range: SourceRange


@dataclass
class DocumentAst(AstNode):
    items: list[AstNode] = field(default_factory=list)


@dataclass
class AssignmentNode(AstNode):
    key: str
    value: AstNode
    key_range: SourceRange
    operator_range: SourceRange


@dataclass
class ObjectNode(AstNode):
    items: list[AstNode] = field(default_factory=list)
    open_range: Optional[SourceRange] = None
    close_range: Optional[SourceRange] = None

    def assignments(self, key: Optional[str] = None) -> list[AssignmentNode]:
        result = [item for item in self.items if isinstance(item, AssignmentNode)]
        if key is not None:
            result = [item for item in result if item.key == key]
        return result

    def first_assignment(self, key: str) -> Optional[AssignmentNode]:
        matches = self.assignments(key)
        return matches[0] if matches else None


@dataclass
class ScalarNode(AstNode):
    value: Any
    raw: str
    value_type: str


@dataclass
class ComparisonNode(AstNode):
    left: ScalarNode
    operator: str
    right: AstNode
    operator_range: SourceRange


@dataclass
class MissingValueNode(AstNode):
    pass


@dataclass
class ErrorNode(AstNode):
    message: str
    raw: str = ""
