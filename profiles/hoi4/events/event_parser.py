from __future__ import annotations

import os
from typing import Optional

from core.engine.model import Diagnostic
from core.engine.profile import EntityRule, ProfileDefinition, SchemaDefinition
from core.engine.runtime import Document, Entity, Property, Reference, Relation

from profiles.hoi4.script_parser import AssignmentNode, ObjectNode, Parser, infer_value_type, node_value, value_range


class EventParser:
    def __init__(self, profile: ProfileDefinition):
        self.profile = profile

    def parse_document(self, path: str, text: str, project_root: str = "") -> Document:
        relative_path = os.path.relpath(path, project_root) if project_root else path
        ast, tokens, diagnostics = Parser(text).parse()
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

    def _extract_properties(self, value, schema: Optional[SchemaDefinition]) -> dict[str, list[Property]]:
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
                        source="hoi4-event-schema",
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
        seen = set()
        for props in entity.properties.values():
            for prop in props:
                if prop.value is None or not prop.schema or not prop.schema.reference:
                    continue
                reference = Reference(
                    source_entity=entity,
                    source_property=prop,
                    value=str(prop.value),
                    target_kind=prop.schema.reference.kind,
                    target_id=str(prop.value),
                    state=prop.schema.reference.state_if_missing,
                )
                seen.add((prop.name, reference.target_kind, reference.target_id))
                entity.references.append(reference)

        for rule in self.profile.reference_rules:
            if rule.source_kind != entity.kind:
                continue
            for prop in entity.properties.get(rule.property, []):
                if prop.value is None:
                    continue
                key = (prop.name, rule.target_kind, str(prop.value))
                if key in seen:
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


def first(values: list):
    return values[0] if values else None


PARSER_CLASS = EventParser
