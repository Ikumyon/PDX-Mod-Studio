from dataclasses import dataclass, field
from typing import Any, Optional
import os
import json

from plugins.hoi4.script_parser import (AssignmentNode, ObjectNode, Parser, infer_value_type, 
                                        node_value, value_range, Diagnostic, SourcePosition, SourceRange)

# プロファイル内で使用するデータ保持用クラス
class Document:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)
        self.entities = []
        self.diagnostics = []

class Entity:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)
        self.references = []
        self.relations = []
        self.diagnostics = []
        self.children = []

class Property:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)

class Reference:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)

class Relation:
    def __init__(self, **kwargs):
        for k, v in kwargs.items(): setattr(self, k, v)

# エンジン由来の定義（型ヒント用）
EntityRule = Any
SchemaDefinition = Any


@dataclass
class ParsedEvent:
    key: str
    node: AssignmentNode
    properties: dict[str, list[AssignmentNode]] = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        # id プロパティの値を取得（スカラー値の場合）
        id_nodes = self.properties.get("id", [])
        if not id_nodes: return ""
        val = id_nodes[0].value
        return str(val.value) if hasattr(val, "value") else ""

    @property
    def options(self) -> list[AssignmentNode]:
        return self.properties.get("option", [])

    def first(self, name: str) -> Optional[AssignmentNode]:
        nodes = self.properties.get(name, [])
        return nodes[0] if nodes else None


class EventParser:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.schema = {}
        schema_path = os.path.join(os.path.dirname(__file__), "event_schema.json")
        if os.path.exists(schema_path):
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    self.schema = json.load(f)
            except Exception:
                pass

    def parse_document(self, path: str, text: str, project_root: str = "") -> Document:
        import os
        relative_path = os.path.relpath(path, project_root) if project_root else path
        ast, tokens, diagnostics = Parser(text).parse()
        document_type = self.plugin.classify_document(relative_path) if hasattr(self.plugin, "classify_document") else "unknown"
        
        # イベント構造の抽出
        events = self._extract_events(ast)
        
        # ドキュメントプロパティの抽出
        doc_properties = {}
        doc_props_def = self.schema.get("document_properties", {})
        for item in ast.items:
            if isinstance(item, AssignmentNode) and item.key in doc_props_def:
                if hasattr(item.value, "value"):
                    doc_properties[item.key] = str(item.value.value)
        
        # ネームスペースの抽出 (後方互換性のため個別に保持)
        namespace = doc_properties.get("add_namespace", "")
        
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
            namespace=namespace,
            properties=doc_properties,
        )
        document.events = events # 拡張プロパティとして保持
        document.entities = self.extract_entities(document)
        return document

    def _extract_events(self, ast: Any) -> list[ParsedEvent]:
        events: list[ParsedEvent] = []
        if not hasattr(ast, "items"): return events
        
        for item in ast.items:
            if not isinstance(item, AssignmentNode):
                continue
            if item.key not in {"country_event", "news_event"}:
                continue
            
            parsed = ParsedEvent(item.key, item)
            if isinstance(item.value, ObjectNode):
                for child in item.value.items:
                    if isinstance(child, AssignmentNode):
                        parsed.properties.setdefault(child.key, []).append(child)
            events.append(parsed)
        return events

    def extract_entities(self, document: Document) -> list[Entity]:
        entities: list[Entity] = []
        if not hasattr(self.plugin, "matching_entity_rules"):
            return entities
            
        for rule in self.plugin.matching_entity_rules(document.document_type):
            for assignment in document.ast.items:
                if isinstance(assignment, AssignmentNode) and assignment.key == rule.key:
                    entities.append(self._build_entity(document, assignment, rule, parent_id=""))
        return entities

    def _build_entity(self, document: Document, assignment: AssignmentNode, rule: EntityRule, parent_id: str) -> Entity:
        schema = self.plugin.schemas.get(rule.schema)
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

        for rule in self.plugin.reference_rules:
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
        for rule in self.plugin.relation_rules:
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
