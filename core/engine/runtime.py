from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from .model import Diagnostic, SourceRange
from .profile import SchemaDefinition, SchemaProperty


class ProfileAdapter(Protocol):
    """A profile-owned parser/extractor entry point."""

    def parse_document(self, path: str, text: str, project_root: str = "") -> "Document":
        ...


@dataclass
class Property:
    name: str
    type: str
    value: Any
    source_node: Any
    range: SourceRange
    schema: Optional[SchemaProperty] = None
    editable: bool = True
    diagnostics: list[Diagnostic] = field(default_factory=list)
    unknown: bool = False


@dataclass
class Reference:
    source_entity: "Entity"
    source_property: Property
    value: str
    target_kind: str
    target_id: str
    state: str = "unknown"
    target_entity: Optional["Entity"] = None
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class Relation:
    source_entity: "Entity"
    target_entity: Optional["Entity"]
    relation_type: str
    label: str = ""
    source_property: Optional[Property] = None
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class Entity:
    internal_id: str
    kind: str
    subtype: str
    external_id: str
    display_name: str
    properties: dict[str, list[Property]]
    children: list["Entity"]
    source_node: Any
    range: SourceRange
    document: "Document"
    schema: Optional[SchemaDefinition] = None
    references: list[Reference] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    dirty: bool = False

    def first_property(self, name: str) -> Optional[Property]:
        values = self.properties.get(name, [])
        return values[0] if values else None


@dataclass
class Document:
    id: str
    path: str
    relative_path: str
    text: str
    document_type: str
    ast: Any
    tokens: list[Any]
    diagnostics: list[Diagnostic]
    entities: list[Entity] = field(default_factory=list)
    encoding: str = "utf-8"
    newline: str = "\n"
    opaque_state: Any = None


@dataclass
class ProjectIndex:
    entities_by_kind: dict[str, list[Entity]] = field(default_factory=dict)
    entities_by_kind_id: dict[tuple[str, str], list[Entity]] = field(default_factory=dict)
    entities_by_document: dict[str, list[Entity]] = field(default_factory=dict)
    references: list[Reference] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def add_document(self, document: Document) -> None:
        self.entities_by_document[document.id] = document.entities
        for entity in walk_entities(document.entities):
            self.entities_by_kind.setdefault(entity.kind, []).append(entity)
            if entity.external_id:
                self.entities_by_kind_id.setdefault((entity.kind, entity.external_id), []).append(entity)
            self.references.extend(entity.references)
            self.relations.extend(entity.relations)
            self.diagnostics.extend(entity.diagnostics)
        self.diagnostics.extend(document.diagnostics)

    def resolve_references(self) -> None:
        for reference in self.references:
            matches = self.entities_by_kind_id.get((reference.target_kind, reference.target_id), [])
            if len(matches) == 1:
                reference.state = "resolved"
                reference.target_entity = matches[0]
            elif len(matches) > 1:
                reference.state = "duplicate"
                reference.diagnostics.append(
                    Diagnostic(
                        "warning",
                        f"Reference is ambiguous: {reference.target_kind}:{reference.target_id}",
                        reference.source_property.range,
                        code="ambiguous-reference",
                        source="reference",
                        target=reference,
                    )
                )
            else:
                reference.state = reference.state if reference.state != "unknown" else "unresolved"
                severity = "info" if reference.state == "external_possible" else "warning"
                reference.diagnostics.append(
                    Diagnostic(
                        severity,
                        f"Unresolved reference: {reference.target_kind}:{reference.target_id}",
                        reference.source_property.range,
                        code="unresolved-reference",
                        source="reference",
                        target=reference,
                    )
                )
            self.diagnostics.extend(reference.diagnostics)


@dataclass
class EditCommand:
    entity: Entity
    property_name: str
    old_value: Any
    new_value: Any
    range: SourceRange
    label: str = ""


@dataclass
class TextDiff:
    start_offset: int
    end_offset: int
    replacement: str

    @staticmethod
    def for_scalar_property(command: EditCommand) -> "TextDiff":
        return TextDiff(command.range.start_offset, command.range.end_offset, serialize_scalar(command.new_value))

    @staticmethod
    def apply_all(text: str, diffs: list["TextDiff"]) -> str:
        result = text
        for diff in sorted(diffs, key=lambda item: item.start_offset, reverse=True):
            result = result[:diff.start_offset] + diff.replacement + result[diff.end_offset:]
        return result


class ProjectAnalyzer:
    """Project-level orchestration that delegates parsing to the selected profile."""

    def __init__(self, adapter: ProfileAdapter):
        self.adapter = adapter

    def parse_document(self, path: str, text: str, project_root: str = "") -> Document:
        return self.adapter.parse_document(path, text, project_root)

    def analyze_project(self, files: dict[str, str], project_root: str = "") -> tuple[list[Document], ProjectIndex]:
        documents = [
            self.parse_document(path, text, project_root)
            for path, text in files.items()
        ]
        index = ProjectIndex()
        for document in documents:
            index.add_document(document)
        index.resolve_references()
        return documents, index


def walk_entities(entities: list[Entity]) -> list[Entity]:
    result: list[Entity] = []
    for entity in entities:
        result.append(entity)
        result.extend(walk_entities(entity.children))
    return result


def serialize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if any(ch.isspace() for ch in text) or text == "":
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text
