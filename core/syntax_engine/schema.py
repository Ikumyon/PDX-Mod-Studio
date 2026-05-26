from __future__ import annotations

from typing import Any

from .models import AssignmentNode, ChildrenNode, Diagnostic, FileNode, ValidationResult, ValueNode, ValueTypeRule


class SchemaValidator:
    def __init__(self, value_types: dict[str, ValueTypeRule]):
        self.value_types = value_types

    def validate(self, ast: FileNode, schema: dict[str, Any]) -> ValidationResult:
        diagnostics: list[Diagnostic] = []
        file_schema = schema.get("file")
        if not isinstance(file_schema, dict):
            diagnostics.append(Diagnostic(path="file", message="Schema root must contain an object at 'file'."))
            return ValidationResult(ast=ast, diagnostics=diagnostics, records=[])

        records = self._validate_scope(ast.children, file_schema, "file", diagnostics)
        filtered_records = [record for record in records if record]
        return ValidationResult(ast=ast, diagnostics=diagnostics, records=filtered_records)

    def _validate_scope(
        self,
        scope_children: list[Any],
        schema_map: dict[str, Any],
        path: str,
        diagnostics: list[Diagnostic],
    ) -> list[dict[str, str]]:
        records: list[dict[str, str]] = [{}]
        assignments = [child for child in scope_children if isinstance(child, AssignmentNode)]
        bare_values = [child for child in scope_children if isinstance(child, ValueNode)]

        if bare_values and "items" not in schema_map:
            diagnostics.append(Diagnostic(path=path, message="Bare values are not allowed here without an items schema."))

        consumed_ids: set[int] = set()
        wildcard_schema = schema_map.get("*")

        for key, entry in schema_map.items():
            if key in {"*", "items"}:
                continue
            if not isinstance(entry, dict):
                diagnostics.append(Diagnostic(path=f"{path}.{key}", message="Schema entry must be an object."))
                continue
            matches = [node for node in assignments if node.left == key]
            if not matches and self._usage(entry) == "required":
                diagnostics.append(Diagnostic(path=f"{path}.{key}", message="Required key is missing."))
                continue
            for node in matches:
                consumed_ids.add(id(node))
                partials = self._validate_assignment(node, entry, key, f"{path}.{key}", diagnostics)
                records = self._merge_records(records, partials)

        remaining = [node for node in assignments if id(node) not in consumed_ids]
        if wildcard_schema is not None:
            if not isinstance(wildcard_schema, dict):
                diagnostics.append(Diagnostic(path=f"{path}.*", message="Wildcard schema entry must be an object."))
            else:
                if not remaining and self._usage(wildcard_schema) == "required":
                    diagnostics.append(Diagnostic(path=f"{path}.*", message="At least one matching entry is required."))
                wildcard_records: list[dict[str, str]] = []
                for node in remaining:
                    partials = self._validate_assignment(node, wildcard_schema, "*", f"{path}.*[{node.left}]", diagnostics)
                    if not partials:
                        partials = [{}]
                    for existing in records:
                        for partial in partials:
                            merged = dict(existing)
                            merged.update(partial)
                            wildcard_records.append(merged)
                if remaining:
                    records = wildcard_records
        elif remaining:
            for node in remaining:
                diagnostics.append(Diagnostic(path=path, message=f"Unexpected key '{node.left}'."))

        items_schema = schema_map.get("items")
        if items_schema is not None:
            if not isinstance(items_schema, dict):
                diagnostics.append(Diagnostic(path=f"{path}.items", message="Items schema must be an object."))
            else:
                for index, item in enumerate(bare_values):
                    self._validate_scalar(item.value, items_schema, f"{path}.items[{index}]", diagnostics)

        return records

    def _validate_assignment(
        self,
        node: AssignmentNode,
        schema_entry: dict[str, Any],
        schema_key: str,
        path: str,
        diagnostics: list[Diagnostic],
    ) -> list[dict[str, str]]:
        selector = self._selector_for(schema_key, schema_entry)
        target = self._resolve_selector(node, selector)
        self._validate_target(target, schema_entry, path, diagnostics)

        partial: dict[str, str] = {}
        field_name = self._field_name(schema_key, schema_entry)
        scalar_value = self._to_scalar_text(target)
        if field_name and scalar_value is not None:
            partial[field_name] = scalar_value

        child_schema = schema_entry.get("children")
        item_schema = schema_entry.get("items")
        child_records: list[dict[str, str]] | None = None

        if child_schema is not None:
            if not isinstance(child_schema, dict):
                diagnostics.append(Diagnostic(path=f"{path}.children", message="children must be an object."))
            else:
                child_nodes = self._extract_children(node.right)
                if child_nodes is None:
                    diagnostics.append(Diagnostic(path=path, message="children was declared but the node has no children."))
                else:
                    scoped_schema = dict(child_schema)
                    if item_schema is not None:
                        scoped_schema["items"] = item_schema
                    child_records = self._validate_scope(child_nodes, scoped_schema, f"{path}.children", diagnostics)
        elif item_schema is not None:
            child_nodes = self._extract_children(node.right)
            if child_nodes is None:
                diagnostics.append(Diagnostic(path=f"{path}.items", message="items requires a children node on the right-hand side."))
            else:
                self._validate_scope(child_nodes, {"items": item_schema}, f"{path}.items", diagnostics)

        if child_records:
            return self._merge_records([partial], child_records)
        return [partial]

    def _validate_target(self, target: Any, schema_entry: dict[str, Any], path: str, diagnostics: list[Diagnostic]) -> None:
        for type_name in self._type_names(schema_entry):
            if self._matches_type(target, type_name):
                break
        else:
            expected = schema_entry.get("type", "value")
            diagnostics.append(Diagnostic(path=path, message=f"Expected type {expected}, but the node did not match."))
            return

        scalar = self._to_scalar_text(target)
        allowed_values = schema_entry.get("allowed_values")
        if scalar is not None and allowed_values is not None and scalar not in allowed_values:
            diagnostics.append(Diagnostic(path=path, message=f"Value '{scalar}' is not in allowed_values."))

    def _validate_scalar(self, value: str, schema_entry: dict[str, Any], path: str, diagnostics: list[Diagnostic]) -> None:
        target = ValueNode(kind="value", value=value)
        self._validate_target(target, schema_entry, path, diagnostics)

    def _matches_type(self, target: Any, type_name: str) -> bool:
        if type_name == "children" or type_name.endswith("_children"):
            return isinstance(target, ChildrenNode) or isinstance(target, list)
        if type_name == "enum":
            return self._to_scalar_text(target) is not None

        scalar = self._to_scalar_text(target)
        if scalar is None:
            return False

        if type_name == "number":
            return self.value_types.get(
                "number",
                ValueTypeRule("number", pattern=r"-?[0-9]+(?:\.[0-9]+)?"),
            ).matches(scalar)

        rule = self.value_types.get(type_name)
        if rule:
            return rule.matches(scalar)
        return True

    def _selector_for(self, schema_key: str, schema_entry: dict[str, Any]) -> str:
        selector = schema_entry.get("selector")
        if selector:
            return str(selector)
        if schema_key == "*":
            return "assignment.left"
        return "assignment.right"

    def _resolve_selector(self, node: AssignmentNode, selector: str) -> Any:
        if selector == "assignment.left":
            return node.left
        if selector == "assignment.right":
            return node.right
        if selector == "children":
            children = self._extract_children(node.right)
            return children if children is not None else node.right
        if selector == "items":
            children = self._extract_children(node.right)
            if children is None:
                return []
            return [child for child in children if isinstance(child, ValueNode)]
        raise ValueError(f"Unsupported selector: {selector}")

    def _extract_children(self, node: Any) -> list[Any] | None:
        if isinstance(node, ChildrenNode):
            return node.children
        if isinstance(node, FileNode):
            return node.children
        if isinstance(node, list):
            return node
        return None

    def _field_name(self, schema_key: str, schema_entry: dict[str, Any]) -> str | None:
        if schema_entry.get("as"):
            return str(schema_entry["as"])
        if schema_key != "*":
            return schema_key
        return None

    def _to_scalar_text(self, target: Any) -> str | None:
        if isinstance(target, str):
            return target
        if isinstance(target, ValueNode):
            return target.value
        return None

    def _type_names(self, schema_entry: dict[str, Any]) -> list[str]:
        raw = schema_entry.get("type")
        if isinstance(raw, list):
            return [str(item) for item in raw]
        if raw is None:
            return ["value"]
        return [str(raw)]

    def _usage(self, schema_entry: dict[str, Any]) -> str:
        return str(schema_entry.get("usage", "optional"))

    def _merge_records(
        self,
        base_records: list[dict[str, str]],
        partial_records: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        if not partial_records:
            return base_records
        merged: list[dict[str, str]] = []
        for base in base_records:
            for partial in partial_records:
                item = dict(base)
                item.update(partial)
                merged.append(item)
        return merged
