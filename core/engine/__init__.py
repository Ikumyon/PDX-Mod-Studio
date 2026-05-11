"""Profile-driven analysis contracts and project indexing."""

from .profile import (
    DocumentTypeRule,
    EntityRule,
    ProfileDefinition,
    ReferenceSpec,
    ReferenceRule,
    SchemaDefinition,
)
from .runtime import (
    Document,
    EditCommand,
    Entity,
    ProfileAdapter,
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
    "ProfileAdapter",
    "ProfileDefinition",
    "ProjectAnalyzer",
    "ProjectIndex",
    "Property",
    "Reference",
    "ReferenceSpec",
    "ReferenceRule",
    "SchemaDefinition",
    "TextDiff",
]
