from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import re
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
                raw_value = getattr(node, "value", None)
                self._matches_type(node, type_spec, path, collect_diagnostics=True)
                self._add_style_diagnostics(node, type_spec, path, raw_value)
                return

        # 適合する型が1つもなかった場合、範囲外エラーがあればそれを報告
        if isinstance(node, ValueNode):
            for type_spec in type_specs:
                type_name = self._type_name(type_spec, path)
                rule = self.value_types.get(type_name)
                if rule and not rule.children:
                    allowed_values = self._allowed_values(type_spec, path) if type_name == "enum" else None
                    is_valid, error_key, severity = rule.validate(node.value, allowed_values=allowed_values)
                    if not is_valid and error_key.startswith("grammar.error.range_out_of_bounds"):
                        self._add_diagnostic(node, path, error_key, severity=severity)
                        return

        self._add_diagnostic(
            node,
            path,
            "grammar.error.type_mismatch",
            suggestions=self._type_mismatch_suggestions(node, type_specs),
        )

    def _validate_scalar(self, value: str, node: AssignmentNode | ValueNode, definition: dict[str, Any], path: str) -> None:
        if "type" not in definition:
            raise ValueError(f"Missing 'type' at '{path}'.")

        type_specs = self._normalize_type_specs(definition["type"], path)
        last_diagnostic = None
        for type_spec in type_specs:
            type_name = self._type_name(type_spec, path)
            if type_name == "block":
                continue
            rule = self._value_type(type_name, path)
            allowed_values = self._allowed_values(type_spec, path) if type_name == "enum" else None
            is_valid, error_key, severity = rule.validate(value, allowed_values=allowed_values)
            if is_valid:
                return
            else:
                last_diagnostic = (error_key, severity)

        if last_diagnostic:
            error_key, severity = last_diagnostic
            self._add_diagnostic(
                node,
                path,
                error_key,
                severity=severity,
                suggestions=self._type_mismatch_suggestions(node, type_specs),
            )
        else:
            self._add_diagnostic(
                node,
                path,
                "grammar.error.type_mismatch",
                suggestions=self._type_mismatch_suggestions(node, type_specs),
            )

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
        is_valid, _, _ = rule.validate(node.value, allowed_values=allowed_values)
        if is_valid and collect_diagnostics:
            node.value = rule.normalize_value(node.value, allowed_values=allowed_values)
        return is_valid

    def _type_mismatch_suggestions(self, node: AssignmentNode | ValueNode | ChildrenNode, type_specs: list[dict[str, Any]]) -> list[dict[str, str]]:
        if not isinstance(node, ValueNode):
            return []
        value = str(node.value)
        if not re.fullmatch(r"[+-]?[0-9]+\.[0-9]+", value):
            return []
        if not any(type_spec.get("is") == "int" for type_spec in type_specs):
            return []
        number = Decimal(value)
        floor_value = str(number.to_integral_value(rounding=ROUND_FLOOR))
        ceil_value = str(number.to_integral_value(rounding=ROUND_CEILING))
        rounded_value = str(number.to_integral_value(rounding=ROUND_HALF_UP))
        suggestions = [
            {"label": f"切り捨て: {floor_value}", "replacement": floor_value},
            {"label": f"切り上げ: {ceil_value}", "replacement": ceil_value},
            {"label": f"四捨五入: {rounded_value}", "replacement": rounded_value},
        ]
        deduplicated = []
        seen = set()
        for suggestion in suggestions:
            key = (suggestion["label"], suggestion["replacement"])
            if key not in seen:
                seen.add(key)
                deduplicated.append(suggestion)
        return deduplicated

    def _add_style_diagnostics(self, node: ValueNode | ChildrenNode, type_spec: dict[str, Any], path: str, raw_value: Any) -> None:
        if not isinstance(node, ValueNode):
            return
        if type_spec.get("is") != "float":
            return
        value = str(raw_value)
        if not re.fullmatch(r"[+-]?[0-9]+", value):
            return
        replacement = f"{value}.0"
        self._add_diagnostic(
            node,
            path,
            "grammar.warning.float_without_decimal",
            severity="warning",
            suggestions=[{"label": f"{replacement} にする", "replacement": replacement}],
        )


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
        suggestions: list[dict[str, str]] | None = None,
    ) -> None:
        self._diagnostics.append(
            Diagnostic(
                path=path,
                message=message,
                severity=severity,
                line=getattr(node, "line", 1),
                column=getattr(node, "column", 1),
                length=getattr(node, "length", 1),
                suggestions=list(suggestions or []),
            )
        )

    def check_schema_integrity(
        self,
        schema: Any,
        path: str = "$",
        _seen_property_refs: set[str] | None = None,
    ) -> None:
        """
        スキーマ定義の整合性（定義ミス）を静的かつ網羅的に検査します。
        ドキュメントに準拠し、以下の定義不備をロード時に早期検出します：
        - usage の指定が required, optional 以外である
        - type に指定された型名が values.toml に定義されていない
        - properties の文字列参照が解決できない
        - type が enum なのに allowed_values が定義されていない、または空配列である
        - children = true (block型) なのに properties も items もない
        - select の中に left, right 以外の無効キーがある、または両方欠落している
        """
        if not isinstance(schema, dict):
            return
        seen_property_refs = set(_seen_property_refs or set())

        # 1. usage の検証
        if "usage" in schema:
            usage = schema["usage"]
            if usage not in {"required", "optional"}:
                raise ValueError(
                    f"Schema definition error at '{path}': "
                    f"Invalid 'usage' value '{usage}'. Must be 'required' or 'optional'."
                )

        properties = schema.get("properties")
        items = schema.get("items")

        # 2. properties 参照解決チェック
        if isinstance(properties, str):
            property_ref = properties
            if self.property_resolver is None:
                raise ValueError(
                    f"Schema definition error at '{path}': "
                    f"Properties reference '{property_ref}' cannot be resolved (no property resolver)."
                )
            try:
                resolved = self.property_resolver(property_ref)
            except Exception as e:
                raise ValueError(
                    f"Schema definition error at '{path}': "
                    f"Properties reference '{property_ref}' failed to resolve: {e}"
                )
            
            if not isinstance(resolved, dict) or (not resolved.get("properties") and not resolved.get("items")):
                raise ValueError(
                    f"Schema definition error at '{path}': "
                    f"Properties reference '{property_ref}' resolved to an invalid or empty definition."
                )
            if property_ref in seen_property_refs:
                properties = None
            else:
                seen_property_refs.add(property_ref)
                properties = resolved.get("properties")
                if "items" in resolved and items is None:
                    items = resolved["items"]

        # 3. select 定義の検査
        select_field = schema.get("select")
        if select_field is not None:
            if not isinstance(select_field, dict):
                raise ValueError(f"Schema definition error at '{path}': 'select' must be a JSON object.")
            
            allowed_keys = {"left", "right"}
            invalid_keys = set(select_field.keys()) - allowed_keys
            if invalid_keys:
                raise ValueError(
                    f"Schema definition error at '{path}': "
                    f"Invalid key(s) {list(invalid_keys)} in 'select'. "
                    f"Only {list(allowed_keys)} are allowed."
                )
            
            left_def = select_field.get("left")
            right_def = select_field.get("right")
            if left_def is None and right_def is None:
                raise ValueError(
                    f"Schema definition error at '{path}': "
                    f"'select' must define at least 'left' or 'right' objects."
                )
                
            if left_def is not None:
                if not isinstance(left_def, dict):
                    raise ValueError(f"Schema definition error at '{path}.select.left': must be a JSON object.")
                self.check_schema_integrity(left_def, f"{path}.select.left", seen_property_refs)
                
            if right_def is not None:
                if not isinstance(right_def, dict):
                    raise ValueError(f"Schema definition error at '{path}.select.right': must be a JSON object.")
                self.check_schema_integrity(right_def, f"{path}.select.right", seen_property_refs)

        # 4. type 定義の検査
        type_field = schema.get("type")
        if type_field is not None:
            try:
                type_specs = self._normalize_type_specs(type_field, path)
            except ValueError as e:
                raise ValueError(f"Schema definition error at '{path}': {e}")
                
            for type_spec in type_specs:
                try:
                    type_name = self._type_name(type_spec, path)
                except ValueError as e:
                    raise ValueError(f"Schema definition error at '{path}': {e}")
                
                # 4.1 未定義の型名チェック
                rule = self.value_types.get(type_name)
                if rule is None:
                    raise ValueError(
                        f"Schema definition error at '{path}': "
                        f"Undefined value type '{type_name}' referenced."
                    )
                
                # 4.2 enum 型の allowed_values チェック
                if type_name == "enum":
                    allowed_values = type_spec.get("allowed_values")
                    if not isinstance(allowed_values, list) or not allowed_values:
                        raise ValueError(
                            f"Schema definition error at '{path}': "
                            f"Enum type must define a non-empty 'allowed_values' array."
                        )
                
                # 4.3 children = true のブロック型チェック
                if rule.children:
                    spec_properties = type_spec.get("properties")
                    spec_items = type_spec.get("items")
                    child_seen_property_refs = seen_property_refs
                    cycle_property_ref = False
                    
                    if isinstance(spec_properties, str):
                        property_ref = spec_properties
                        if self.property_resolver is None:
                            raise ValueError(
                                f"Schema definition error at '{path}': "
                                f"Properties reference '{property_ref}' cannot be resolved."
                            )
                        try:
                            resolved_spec = self.property_resolver(property_ref)
                            if isinstance(resolved_spec, dict):
                                if property_ref in seen_property_refs:
                                    cycle_property_ref = True
                                    spec_properties = None
                                else:
                                    child_seen_property_refs = seen_property_refs | {property_ref}
                                    spec_properties = resolved_spec.get("properties")
                                    if "items" in resolved_spec and spec_items is None:
                                        spec_items = resolved_spec["items"]
                        except Exception as e:
                            raise ValueError(
                                f"Schema definition error at '{path}': "
                                f"Properties reference '{property_ref}' failed to resolve: {e}"
                            )
                    
                    if spec_properties is None and spec_items is None and properties is None and items is None:
                        if cycle_property_ref:
                            continue
                        raise ValueError(
                            f"Schema definition error at '{path}': "
                            f"Type '{type_name}' requires child definitions ('children = true'), "
                            f"but both 'properties' and 'items' are missing."
                        )

                    # 子要素の再帰的検査
                    if isinstance(spec_properties, dict):
                        for prop_name, prop_def in spec_properties.items():
                            self.check_schema_integrity(prop_def, f"{path}.{prop_name}", child_seen_property_refs)
                    if isinstance(spec_items, dict):
                        self.check_schema_integrity(spec_items, f"{path}[]", child_seen_property_refs)

        # 5. 再帰的にすべてのプロパティとアイテムを検査
        if isinstance(properties, dict):
            for prop_name, prop_def in properties.items():
                if prop_name != "rules":
                    self.check_schema_integrity(prop_def, f"{path}.{prop_name}", seen_property_refs)
        if isinstance(items, dict):
            self.check_schema_integrity(items, f"{path}[]", seen_property_refs)
