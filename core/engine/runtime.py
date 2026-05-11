from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from .ast import AssignmentNode, AstNode, DocumentAst, ObjectNode, ScalarNode
from .lexer import Token
from .model import Diagnostic, SourceRange
from .parser import Parser
from .profile import EntityRule, ProfileDefinition, ReferenceRule, SchemaDefinition, SchemaProperty


@dataclass
class Property:
    name: str
    type: str
    value: Any
    source_node: AstNode
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
    source_node: AssignmentNode
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
    ast: DocumentAst
    tokens: list[Token]
    diagnostics: list[Diagnostic]
    entities: list[Entity] = field(default_factory=list)
    encoding: str = "utf-8"
    newline: str = "\n"


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
    def __init__(self, profile: ProfileDefinition):
        self.profile = profile

    def parse_document(self, path: str, text: str, project_root: str = "") -> Document:
        relative_path = os.path.relpath(path, project_root) if project_root else path
        parser = Parser(text)
        ast, tokens, diagnostics = parser.parse()
        document_type = self.profile.classify_document(relative_path)
        document = Document(
            id=relative_path.replace("\\", "/"),
            path=path,
            relative_path=relative_path.replace("\\", "/"),
            text=text,
            document_type=document_type,
            ast=ast,
            tokens=tokens,
            diagnostics=diagnostics,
            newline="\r\n" if "\r\n" in text else "\n",
        )
        document.entities = self.extract_entities(document)
        return document

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

    def extract_entities(self, document: Document) -> list[Entity]:
        entities: list[Entity] = []
        for rule in self.profile.matching_entity_rules(document.document_type):
            for assignment in document.ast.items:
                if isinstance(assignment, AssignmentNode) and assignment.key == rule.key:
                    entities.append(self._build_entity(document, assignment, rule, parent_id=""))
        return entities

    def _build_entity(self, document: Document, assignment: AssignmentNode, rule: EntityRule, parent_id: str) -> Entity:
        schema = self.profile.schemas.get(rule.schema)
        properties = self._extract_properties(assignment.value, schema)
        external_id = self._resolve_entity_id(document, assignment, properties, rule)
        internal_id = f"{document.id}:{assignment.range.start_offset}:{rule.kind}:{external_id or assignment.key}"
        if parent_id:
            internal_id = f"{parent_id}/{internal_id}"

        entity = Entity(
            internal_id=internal_id,
            kind=rule.kind,
            subtype=rule.subtype,
            external_id=external_id,
            display_name=external_id or assignment.key,
            properties=properties,
            children=[],
            source_node=assignment,
            range=assignment.range,
            document=document,
            schema=schema,
        )
        self._validate_required_properties(entity)
        self._extract_child_entities(entity, rule)
        self._extract_references(entity)
        self._extract_relations(entity)
        return entity

    def _extract_properties(self, value: AstNode, schema: Optional[SchemaDefinition]) -> dict[str, list[Property]]:
        properties: dict[str, list[Property]] = {}
        if not isinstance(value, ObjectNode):
            return properties

        for item in value.items:
            if not isinstance(item, AssignmentNode):
                continue
            schema_property = schema.properties.get(item.key) if schema else None
            inferred_type = schema_property.type if schema_property else infer_value_type(item.value)
            prop = Property(
                name=item.key,
                type=inferred_type,
                value=node_value(item.value),
                source_node=item,
                range=value_range(item.value),
                schema=schema_property,
                editable=schema_property.editable if schema_property else False,
                unknown=schema_property is None,
            )
            properties.setdefault(item.key, []).append(prop)
        return properties

    def _resolve_entity_id(
        self,
        document: Document,
        assignment: AssignmentNode,
        properties: dict[str, list[Property]],
        rule: EntityRule,
    ) -> str:
        if rule.id_rule.source == "key":
            return assignment.key
        if rule.id_rule.source == "path":
            return document.relative_path
        if rule.id_rule.source == "property":
            prop = first(properties.get(rule.id_rule.property, []))
            return str(prop.value) if prop and prop.value is not None else ""
        return ""

    def _validate_required_properties(self, entity: Entity) -> None:
        if not entity.schema:
            return
        for name, schema_property in entity.schema.properties.items():
            if schema_property.required and name not in entity.properties:
                entity.diagnostics.append(
                    Diagnostic(
                        "warning",
                        f"Missing required property: {name}",
                        entity.range,
                        code="missing-required-property",
                        source="schema",
                        target=entity,
                    )
                )

    def _extract_child_entities(self, entity: Entity, rule: EntityRule) -> None:
        if not rule.child_rules or not isinstance(entity.source_node.value, ObjectNode):
            return
        for child_rule in rule.child_rules:
            for assignment in entity.source_node.value.assignments(child_rule.key):
                child = self._build_entity(entity.document, assignment, child_rule, parent_id=entity.internal_id)
                entity.children.append(child)

    def _extract_references(self, entity: Entity) -> None:
        for rule in self.profile.reference_rules:
            if rule.source_kind != entity.kind:
                continue
            for prop in entity.properties.get(rule.property, []):
                if prop.value is None:
                    continue
                entity.references.append(
                    Reference(
                        source_entity=entity,
                        source_property=prop,
                        value=str(prop.value),
                        target_kind=rule.target_kind,
                        target_id=str(prop.value),
                        state=rule.state_if_missing,
                    )
                )

    def _extract_relations(self, entity: Entity) -> None:
        for rule in self.profile.relation_rules:
            if rule.source_kind != entity.kind:
                continue
            for prop in entity.properties.get(rule.property, []):
                entity.relations.append(
                    Relation(
                        source_entity=entity,
                        target_entity=None,
                        relation_type=rule.relation_type,
                        label=rule.label,
                        source_property=prop,
                    )
                )


def walk_entities(entities: list[Entity]) -> list[Entity]:
    result: list[Entity] = []
    for entity in entities:
        result.append(entity)
        result.extend(walk_entities(entity.children))
    return result


def node_value(node: AstNode) -> Any:
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, ObjectNode):
        return node
    return None


def value_range(node: AstNode) -> SourceRange:
    return node.range


def infer_value_type(node: AstNode) -> str:
    if isinstance(node, ScalarNode):
        return node.value_type
    if isinstance(node, ObjectNode):
        return "object"
    return "raw"


def serialize_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if any(ch.isspace() for ch in text) or text == "":
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def first(values: list[Any]) -> Any:
    return values[0] if values else None
