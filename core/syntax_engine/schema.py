from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from .models import AssignmentNode, ChildrenNode, Diagnostic, FileNode, ValidationResult, ValueNode, ValueTypeRule


PropertyResolver = Callable[[str], dict[str, Any]]


class SchemaValidator:
    def __init__(
        self,
        value_types: dict[str, ValueTypeRule],
        property_resolver: PropertyResolver | None = None,
    ):
        self.value_types = value_types
        self.property_resolver = property_resolver
        self._diagnostics: list[Diagnostic] = []
        self._records: list[dict[str, str]] = []

    def validate(self, ast: FileNode, schema: dict[str, Any]) -> ValidationResult:
        if not isinstance(schema, dict):
            raise ValueError("Schema root must be a JSON object.")

        self._diagnostics = []
        self._records = []
        self._validate_container(ast, schema, "$")
        return ValidationResult(ast=ast, diagnostics=self._diagnostics, records=self._records)

    def _validate_container(self, node: FileNode | ChildrenNode, schema: dict[str, Any], path: str) -> None:
        properties = self._resolve_properties(schema, path)
        if schema.get("$ignore_validation") is True:
            return
        items = schema.get("items")
        rules = self._collect_rules(schema, properties)

        if properties is None and items is None:
            raise ValueError(f"Schema object at '{path}' must define 'properties' or 'items'.")

        assignments: list[AssignmentNode] = []
        item_nodes: list[ValueNode] = []
        for child in node.children:
            if isinstance(child, AssignmentNode):
                assignments.append(child)
            elif isinstance(child, ValueNode):
                item_nodes.append(child)

        property_counts: dict[str, int] = defaultdict(int)
        matched_wildcard = 0

        if properties is not None:
            for assignment in assignments:
                property_name = assignment.left
                definition = properties.get(property_name)
                property_path = f"{path}.{property_name}"
                matched_by_wildcard = False

                if definition is None and "*" in properties:
                    definition = properties["*"]
                    property_path = f"{path}.{property_name}"
                    matched_by_wildcard = True

                if definition is None:
                    self._add_diagnostic(
                        assignment,
                        property_path,
                        "grammar.error.unknown_property",
                    )
                    continue
                if not isinstance(definition, dict):
                    raise ValueError(f"Property definition at '{property_path}' must be an object.")

                property_counts[property_name] += 1
                if matched_by_wildcard:
                    matched_wildcard += 1
                if property_counts[property_name] > 1 and definition.get("multiple") is not True:
                    self._add_diagnostic(
                        assignment,
                        property_path,
                        "grammar.error.duplicate_property",
                    )

                self._validate_assignment(assignment, definition, property_path)

            for property_name, definition in properties.items():
                if property_name == "rules" and isinstance(definition, list):
                    continue
                if not isinstance(definition, dict):
                    raise ValueError(f"Property definition at '{path}.{property_name}' must be an object.")
                usage = self._usage(definition, f"{path}.{property_name}")
                if usage != "required":
                    continue
                if property_name == "*":
                    if matched_wildcard == 0:
                        self._add_diagnostic(node, path, "grammar.error.required_property_missing")
                elif property_counts[property_name] == 0:
                    self._add_diagnostic(node, f"{path}.{property_name}", "grammar.error.required_property_missing")
        elif assignments:
            for assignment in assignments:
                self._add_diagnostic(assignment, f"{path}.{assignment.left}", "grammar.error.unknown_property")

        if items is not None:
            if not isinstance(items, dict):
                raise ValueError(f"'items' at '{path}' must be an object.")
            for index, item in enumerate(item_nodes):
                self._validate_value(item, items, f"{path}[{index}]")
        elif item_nodes:
            for index, item in enumerate(item_nodes):
                self._add_diagnostic(item, f"{path}[{index}]", "grammar.error.unexpected_item")

        self._validate_rules(rules, property_counts, node, path)

    def _validate_assignment(self, assignment: AssignmentNode, definition: dict[str, Any], path: str) -> None:
        select = definition.get("select")
        if select is not None:
            if not isinstance(select, dict):
                raise ValueError(f"'select' at '{path}' must be an object.")
            left = select.get("left")
            right = select.get("right")
            if left is not None:
                if not isinstance(left, dict):
                    raise ValueError(f"'select.left' at '{path}' must be an object.")
                self._validate_scalar(assignment.left, assignment, left, f"{path}.left")
                capture_name = left.get("key_capture")
                if isinstance(capture_name, str) and capture_name:
                    self._records.append({capture_name: assignment.left})
            if right is not None:
                if not isinstance(right, dict):
                    raise ValueError(f"'select.right' at '{path}' must be an object.")
                self._validate_value(assignment.right, right, f"{path}.right")
            return

        self._validate_value(assignment.right, definition, path)

    def _validate_value(self, node: ValueNode | ChildrenNode, definition: dict[str, Any], path: str) -> None:
        if "type" not in definition:
            raise ValueError(f"Missing 'type' at '{path}'.")

        type_specs = self._normalize_type_specs(definition["type"], path)
        for type_spec in type_specs:
            if self._matches_type(node, type_spec, path, collect_diagnostics=False):
                self._matches_type(node, type_spec, path, collect_diagnostics=True)
                return

        self._add_diagnostic(node, path, "grammar.error.type_mismatch")

    def _validate_scalar(self, value: str, node: AssignmentNode | ValueNode, definition: dict[str, Any], path: str) -> None:
        if "type" not in definition:
            raise ValueError(f"Missing 'type' at '{path}'.")

        type_specs = self._normalize_type_specs(definition["type"], path)
        for type_spec in type_specs:
            type_name = self._type_name(type_spec, path)
            if type_name == "block":
                continue
            rule = self._value_type(type_name, path)
            allowed_values = self._allowed_values(type_spec, path) if type_name == "enum" else None
            if rule.matches(value, allowed_values=allowed_values):
                return

        self._add_diagnostic(node, path, "grammar.error.type_mismatch")

    def _matches_type(
        self,
        node: ValueNode | ChildrenNode,
        type_spec: dict[str, Any],
        path: str,
        collect_diagnostics: bool,
    ) -> bool:
        type_name = self._type_name(type_spec, path)
        rule = self._value_type(type_name, path)

        if rule.children:
            if not isinstance(node, ChildrenNode):
                return False
            if collect_diagnostics:
                nested_schema = self._schema_from_block_type(type_spec, path)
                self._validate_container(node, nested_schema, path)
            return True

        if isinstance(node, ChildrenNode):
            return False

        allowed_values = self._allowed_values(type_spec, path) if type_name == "enum" else None
        return rule.matches(node.value, allowed_values=allowed_values)

    def _schema_from_block_type(self, type_spec: dict[str, Any], path: str) -> dict[str, Any]:
        nested_schema: dict[str, Any] = {}
        if "properties" in type_spec:
            nested_schema["properties"] = type_spec["properties"]
        if "items" in type_spec:
            nested_schema["items"] = type_spec["items"]
        if "rules" in type_spec:
            nested_schema["rules"] = type_spec["rules"]
        return nested_schema

    def _resolve_properties(self, schema: dict[str, Any], path: str) -> dict[str, Any] | None:
        if "properties" not in schema:
            return None

        properties = schema["properties"]
        if isinstance(properties, str):
            if self.property_resolver is None:
                raise ValueError(f"Properties reference '{properties}' at '{path}' cannot be resolved.")
            resolved = self.property_resolver(properties)
            if not isinstance(resolved, dict):
                raise ValueError(f"Properties reference '{properties}' at '{path}' must resolve to an object.")
            if resolved.get("$ignore_validation") is True:
                schema["$ignore_validation"] = True
                return None
            if "items" in resolved and "items" not in schema:
                schema["items"] = resolved["items"]
            if "rules" in resolved and "rules" not in schema:
                schema["rules"] = resolved["rules"]
            properties = resolved.get("properties")

        if not isinstance(properties, dict):
            raise ValueError(f"'properties' at '{path}' must be an object or reference string.")
        return properties

    def _collect_rules(self, schema: dict[str, Any], properties: dict[str, Any] | None) -> list[dict[str, Any]]:
        raw_rules: list[Any] = []
        schema_rules = schema.get("rules")
        if schema_rules is not None:
            if not isinstance(schema_rules, list):
                raise ValueError("'rules' must be an array.")
            raw_rules.extend(schema_rules)

        if isinstance(properties, dict):
            embedded_rules = properties.get("rules")
            if embedded_rules is not None:
                if not isinstance(embedded_rules, list):
                    raise ValueError("'properties.rules' must be an array.")
                raw_rules.extend(embedded_rules)

        rules: list[dict[str, Any]] = []
        for rule in raw_rules:
            if not isinstance(rule, dict):
                raise ValueError("Each rule must be an object.")
            rules.append(rule)
        return rules

    def _validate_rules(
        self,
        rules: list[dict[str, Any]],
        property_counts: dict[str, int],
        node: FileNode | ChildrenNode,
        path: str,
    ) -> None:
        for rule in rules:
            rule_name = rule.get("rule")
            if rule_name != "exclusive":
                raise ValueError(f"Unsupported schema rule '{rule_name}'.")

            groups = rule.get("groups")
            if not isinstance(groups, list):
                raise ValueError(f"Exclusive rule at '{path}' must define 'groups'.")

            min_count = 1
            match = rule.get("match")
            if isinstance(match, dict) and "min" in match:
                min_value = match["min"]
                if not isinstance(min_value, int) or min_value < 1:
                    raise ValueError(f"Exclusive rule at '{path}' has an invalid 'match.min'.")
                min_count = min_value

            matched_groups = 0
            for group in groups:
                if not isinstance(group, list):
                    raise ValueError(f"Exclusive rule group at '{path}' must be an array.")
                present = sum(1 for name in group if isinstance(name, str) and property_counts.get(name, 0) > 0)
                if present >= min_count:
                    matched_groups += 1

            if matched_groups > 1:
                message = rule.get("message")
                if not isinstance(message, str) or not message:
                    raise ValueError(f"Exclusive rule at '{path}' must define a message key.")
                severity = rule.get("severity", "error")
                if severity not in {"error", "warning"}:
                    raise ValueError(f"Exclusive rule at '{path}' has an invalid severity.")
                self._add_diagnostic(node, path, message, severity=severity)

    def _normalize_type_specs(self, raw_type: Any, path: str) -> list[dict[str, Any]]:
        raw_specs = raw_type if isinstance(raw_type, list) else [raw_type]
        if not raw_specs:
            raise ValueError(f"'type' at '{path}' must not be empty.")

        specs: list[dict[str, Any]] = []
        for raw_spec in raw_specs:
            if isinstance(raw_spec, str):
                specs.append({"is": raw_spec})
            elif isinstance(raw_spec, dict):
                specs.append(raw_spec)
            else:
                raise ValueError(f"'type' at '{path}' must be a string, object, or array.")
        return specs

    def _type_name(self, type_spec: dict[str, Any], path: str) -> str:
        type_name = type_spec.get("is")
        if not isinstance(type_name, str) or not type_name:
            raise ValueError(f"Type object at '{path}' must define 'is'.")
        return type_name

    def _value_type(self, type_name: str, path: str) -> ValueTypeRule:
        rule = self.value_types.get(type_name)
        if rule is None:
            raise ValueError(f"Undefined value type '{type_name}' at '{path}'.")
        return rule

    def _allowed_values(self, type_spec: dict[str, Any], path: str) -> list[Any]:
        allowed_values = type_spec.get("allowed_values")
        if not isinstance(allowed_values, list) or not allowed_values:
            raise ValueError(f"Enum type at '{path}' must define a non-empty 'allowed_values' array.")
        return allowed_values

    def _usage(self, definition: dict[str, Any], path: str) -> str:
        usage = definition.get("usage")
        if usage not in {"required", "optional"}:
            raise ValueError(f"Property definition at '{path}' must define usage as 'required' or 'optional'.")
        return usage

    def _add_diagnostic(
        self,
        node: FileNode | ChildrenNode | AssignmentNode | ValueNode,
        path: str,
        message: str,
        severity: str = "error",
    ) -> None:
        self._diagnostics.append(
            Diagnostic(
                path=path,
                message=message,
                severity=severity,
                line=getattr(node, "line", 1),
                column=getattr(node, "column", 1),
                length=getattr(node, "length", 1),
            )
        )
