from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class SourcePosition:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceRange:
    start: SourcePosition
    end: SourcePosition

    @property
    def start_offset(self) -> int:
        return self.start.offset

    @property
    def end_offset(self) -> int:
        return self.end.offset

    @staticmethod
    def between(start: "SourceRange", end: "SourceRange") -> "SourceRange":
        return SourceRange(start.start, end.end)


@dataclass
class Diagnostic:
    severity: str
    message: str
    range: Optional[SourceRange] = None
    code: str = ""
    source: str = "engine"
    target: Any = None
    fixes: list[Any] = field(default_factory=list)
