from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DocumentTypeRule:
    id: str
    path_globs: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)

    def matches(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/")
        if self.extensions and os.path.splitext(normalized)[1] not in self.extensions:
            return False
        if not self.path_globs:
            return True
        return any(fnmatch.fnmatch(normalized, pattern) for pattern in self.path_globs)


@dataclass
class IdRule:
    source: str = "property"
    property: str = "id"

    @staticmethod
    def from_dict(data: dict[str, Any] | None) -> "IdRule":
        data = data or {}
        return IdRule(source=data.get("from", data.get("source", "property")), property=data.get("property", "id"))


@dataclass
class EntityRule:
    document_type: Optional[str]
    key: str
    kind: str
    subtype: str = ""
    schema: str = ""
    id_rule: IdRule = field(default_factory=IdRule)
    child_rules: list["EntityRule"] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "EntityRule":
        return EntityRule(
            document_type=data.get("document_type"),
            key=data["key"],
            kind=data["kind"],
            subtype=data.get("subtype", data.get("key", "")),
            schema=data.get("schema", ""),
            id_rule=IdRule.from_dict(data.get("id")),
            child_rules=[EntityRule.from_dict(item) for item in data.get("children", [])],
        )


@dataclass
class SchemaProperty:
    name: str
    type: str = "raw"
    display_name: str = ""
    required: bool = False
    multiple: bool = False
    reference_kind: str = ""
    editable: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(name: str, data: dict[str, Any]) -> "SchemaProperty":
        return SchemaProperty(
            name=name,
            type=data.get("type", "raw"),
            display_name=data.get("display_name", name),
            required=data.get("required", False),
            multiple=data.get("multiple", False),
            reference_kind=data.get("reference_kind", ""),
            editable=data.get("editable", True),
            metadata={key: value for key, value in data.items() if key not in {
                "type",
                "display_name",
                "required",
                "multiple",
                "reference_kind",
                "editable",
            }},
        )


@dataclass
class SchemaDefinition:
    id: str
    properties: dict[str, SchemaProperty] = field(default_factory=dict)

    @staticmethod
    def from_dict(schema_id: str, data: dict[str, Any]) -> "SchemaDefinition":
        return SchemaDefinition(
            id=schema_id,
            properties={
                name: SchemaProperty.from_dict(name, prop)
                for name, prop in data.get("properties", {}).items()
            },
        )


@dataclass
class ReferenceRule:
    source_kind: str
    property: str
    target_kind: str
    state_if_missing: str = "unresolved"

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ReferenceRule":
        return ReferenceRule(
            source_kind=data["source_kind"],
            property=data["property"],
            target_kind=data["target_kind"],
            state_if_missing=data.get("state_if_missing", "unresolved"),
        )


@dataclass
class RelationRule:
    source_kind: str
    property: str
    target_kind: str
    relation_type: str
    label: str = ""

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "RelationRule":
        return RelationRule(
            source_kind=data["source_kind"],
            property=data["property"],
            target_kind=data["target_kind"],
            relation_type=data["type"],
            label=data.get("label", data["type"]),
        )


@dataclass
class ProfileDefinition:
    id: str
    name: str
    version: str = "unknown"
    format_version: str = "1"
    document_types: list[DocumentTypeRule] = field(default_factory=list)
    entity_rules: list[EntityRule] = field(default_factory=list)
    schemas: dict[str, SchemaDefinition] = field(default_factory=dict)
    reference_rules: list[ReferenceRule] = field(default_factory=list)
    relation_rules: list[RelationRule] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def load(path: str) -> "ProfileDefinition":
        with open(path, "r", encoding="utf-8") as handle:
            return ProfileDefinition.from_dict(json.load(handle))

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ProfileDefinition":
        return ProfileDefinition(
            id=data.get("id", ""),
            name=data.get("name", data.get("id", "")),
            version=data.get("version", "unknown"),
            format_version=str(data.get("format_version", "1")),
            document_types=[
                DocumentTypeRule(
                    id=item["id"],
                    path_globs=item.get("path_globs", []),
                    extensions=item.get("extensions", []),
                )
                for item in data.get("document_types", [])
            ],
            entity_rules=[EntityRule.from_dict(item) for item in data.get("entity_rules", [])],
            schemas={
                schema_id: SchemaDefinition.from_dict(schema_id, schema)
                for schema_id, schema in data.get("schemas", {}).items()
            },
            reference_rules=[ReferenceRule.from_dict(item) for item in data.get("references", [])],
            relation_rules=[RelationRule.from_dict(item) for item in data.get("relations", [])],
            raw=data,
        )

    def classify_document(self, relative_path: str) -> str:
        for rule in self.document_types:
            if rule.matches(relative_path):
                return rule.id
        return "unknown"

    def matching_entity_rules(self, document_type: str) -> list[EntityRule]:
        return [
            rule for rule in self.entity_rules
            if rule.document_type in (None, "", document_type)
        ]
