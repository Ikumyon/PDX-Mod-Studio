"""Profile-driven Paradox script analysis engine."""

from .lexer import Lexer, Token, TokenKind
from .parser import Parser
from .profile import (
    DocumentTypeRule,
    EntityRule,
    ProfileDefinition,
    ReferenceRule,
    SchemaDefinition,
)
from .runtime import (
    Document,
    EditCommand,
    Entity,
    ProjectAnalyzer,
    ProjectIndex,
    Property,
    Reference,
    TextDiff,
)

__all__ = [
    "Document",
    "DocumentTypeRule",
    "EditCommand",
    "Entity",
    "EntityRule",
    "Lexer",
    "Parser",
    "ProfileDefinition",
    "ProjectAnalyzer",
    "ProjectIndex",
    "Property",
    "Reference",
    "ReferenceRule",
    "SchemaDefinition",
    "TextDiff",
    "Token",
    "TokenKind",
]
