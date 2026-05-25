from __future__ import annotations

import json
import os
import tomllib
from typing import Any, Optional

import core.api


_data_cache: dict[tuple[str, float], Any] = {}


def _structure_fields(columns: Any) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    if not isinstance(columns, list):
        return fields

    for column in columns:
        if not isinstance(column, dict):
            continue
        key = str(column.get("key", "")).strip()
        value_type = column.get("value")
        if not key or not value_type:
            continue

        field_def: dict[str, Any] = {"type": value_type}
        if "required" in column:
            field_def["required"] = column["required"]
        if "multiple" in column:
            field_def["multiple"] = column["multiple"]
        if "schema" in column:
            field_def["schema"] = column["schema"]
        if "allowed_values" in column:
            field_def["allowed_values"] = column["allowed_values"]
        if "context" in column:
            field_def["context"] = column["context"]
        if "reference" in column:
            field_def["reference"] = column["reference"]
        fields[key] = field_def

    return fields


def _find_structure(data: Any, name: str) -> Optional[dict[str, Any]]:
    structures = data.get("structure", []) if isinstance(data, dict) else []
    if not isinstance(structures, list):
        return None
    for item in structures:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def _map_structure_value(value_type: Any) -> Any:
    mapping = {
        "gfx": "sprite_id",
        "decimal": "float",
        "country_tag": "tag",
        "country_scope_ref": "identifier",
        "state_target": "identifier",
        "on_map_mode": "identifier",
        "array_id": "identifier",
    }
    if isinstance(value_type, list):
        return [_map_structure_value(item) for item in value_type]
    return mapping.get(value_type, value_type)


def _runtime_fields_from_structure(
    columns: Any,
    *,
    usage_mode: bool = False,
    object_schemas: Optional[set[str]] = None,
    passthrough_objects: Optional[set[str]] = None,
) -> dict[str, dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    object_schemas = object_schemas or set()
    passthrough_objects = passthrough_objects or set()

    if not isinstance(columns, list):
        return fields

    for column in columns:
        if not isinstance(column, dict):
            continue

        key = str(column.get("key", "")).strip()
        raw_value = column.get("value")
        if not key or not raw_value:
            continue

        field_def: dict[str, Any] = {}
        if raw_value in object_schemas:
            field_def["type"] = "object"
            field_def["schema"] = raw_value
        elif raw_value in passthrough_objects:
            field_def["type"] = "object"
        else:
            field_def["type"] = _map_structure_value(raw_value)

        if usage_mode:
            required = bool(column.get("required", False))
            field_def["usage"] = "required" if required else "optional"
        else:
            if "required" in column:
                field_def["required"] = column["required"]

        if "multiple" in column:
            field_def["multiple"] = column["multiple"]
        if "allowed_values" in column:
            field_def["allowed_values"] = column["allowed_values"]
        if "context" in column:
            field_def["context"] = column["context"]
        if raw_value == "gfx":
            field_def["reference"] = "interface_gfx_sprite"
        fields[key] = field_def

    return fields


def _build_event_runtime_schema(data: dict[str, Any]) -> dict[str, Any]:
    event_structure = _find_structure(data, "event")
    option_structure = _find_structure(data, "event_option")
    if not event_structure:
        raise KeyError("Structure 'event' was not found in 'event_schema.toml'.")

    return {
        "schema_name": "hoi4_event",
        "file_scope": "events",
        "root_pattern": "named_block",
        "unknown_keys": "warn",
        "document_properties": data.get("document_properties", {}),
        "fields": _runtime_fields_from_structure(
            event_structure.get("column", []),
            object_schemas={"event_option"},
        ),
        "sub_schemas": {
            "event_option": {
                "fields": _runtime_fields_from_structure(option_structure.get("column", []) if option_structure else []),
            }
        },
    }


def _build_achievement_runtime_schema(data: dict[str, Any]) -> dict[str, Any]:
    achievement_structure = _find_structure(data, "achievement")
    ribbon_structure = _find_structure(data, "achievement_ribbon")
    if not achievement_structure:
        raise KeyError("Structure 'achievement' was not found in 'achievement_schema.toml'.")

    sub_fields = _runtime_fields_from_structure(ribbon_structure.get("column", []) if ribbon_structure else [])
    if "frame" in sub_fields:
        sub_fields["frame"] = {"type": "array", "item_type": "integer", "size": 3, "required": False}
    if "colors" in sub_fields:
        sub_fields["colors"] = {"type": "array", "item_type": "color_block", "required": False}

    return {
        "schema_name": "hoi4_achievement",
        "file_scope": "common/achievements",
        "root_pattern": "named_block",
        "document_properties": data.get("document_properties", {}),
        "fields": _runtime_fields_from_structure(
            achievement_structure.get("column", []),
            object_schemas={"achievement_ribbon"},
        ),
        "sub_schemas": {
            "achievement_ribbon": {
                "fields": sub_fields,
            }
        },
    }


def _build_decision_category_runtime_schema(data: dict[str, Any]) -> dict[str, Any]:
    category_structure = _find_structure(data, "decision_category")
    highlight_structure = _find_structure(data, "decision_category_highlight_states")
    target_structure = _find_structure(data, "highlight_state_targets")
    fixed_state_structure = _find_structure(data, "decision_category_on_map_area_fixed_state")
    target_array_structure = _find_structure(data, "decision_category_on_map_area_target_array")
    if not category_structure:
        raise KeyError("Structure 'decision_category' was not found in 'decision_category_schema.toml'.")

    return {
        "schema_name": "hoi4_decision_category",
        "file_scope": "common/decisions/categories",
        "root_pattern": "named_block",
        "unknown_keys": "warn",
        "fields": _runtime_fields_from_structure(
            category_structure.get("column", []),
            object_schemas={"decision_category_highlight_states", "decision_category_on_map_area"},
        ),
        "sub_schemas": {
            "decision_category_highlight_states": {
                "fields": _runtime_fields_from_structure(
                    highlight_structure.get("column", []) if highlight_structure else [],
                    object_schemas={"highlight_state_targets"},
                )
            },
            "highlight_state_targets": {
                "fields": _runtime_fields_from_structure(target_structure.get("column", []) if target_structure else [])
            },
            "decision_category_on_map_area": {
                "variants": {
                    "fixed_state": {
                        "fields": _runtime_fields_from_structure(fixed_state_structure.get("column", []) if fixed_state_structure else [])
                    },
                    "target_array": {
                        "fields": _runtime_fields_from_structure(target_array_structure.get("column", []) if target_array_structure else [])
                    },
                }
            },
        },
    }


def _build_decision_runtime_schema(data: dict[str, Any], file_path: str = "") -> dict[str, Any]:
    decision_structure = _find_structure(data, "decision")
    ai_structure = _find_structure(data, "ai_will_do")
    ai_modifier_structure = _find_structure(data, "ai_weight_modifier")
    highlight_structure = _find_structure(data, "highlight_states")
    target_structure = _find_structure(data, "highlight_state_targets")
    targeted_modifier_structure = _find_structure(data, "targeted_modifier")
    if not decision_structure:
        raise KeyError("Structure 'decision' was not found in 'decision_schema.toml'.")

    file_scope = "common/decisions"
    if file_path:
        project_path = core.api.get_project_path()
        if project_path:
            try:
                rel_path = os.path.relpath(file_path, project_path).replace("\\", "/")
                file_scope = os.path.dirname(rel_path) or file_scope
            except Exception:
                pass

    return {
        "schema_name": "hoi4_decision",
        "file_scope": file_scope,
        "root_pattern": "nested_named_block",
        "unknown_keys": "warn",
        "fields": _runtime_fields_from_structure(
            decision_structure.get("column", []),
            object_schemas={"ai_will_do", "highlight_states", "targeted_modifier"},
            passthrough_objects={"country_tag_list"},
        ),
        "sub_schemas": {
            "ai_will_do": {
                "fields": _runtime_fields_from_structure(
                    ai_structure.get("column", []) if ai_structure else [],
                    object_schemas={"ai_weight_modifier"},
                )
            },
            "ai_weight_modifier": {
                "fields": _runtime_fields_from_structure(ai_modifier_structure.get("column", []) if ai_modifier_structure else [])
            },
            "highlight_states": {
                "fields": _runtime_fields_from_structure(
                    highlight_structure.get("column", []) if highlight_structure else [],
                    object_schemas={"highlight_state_targets"},
                    passthrough_objects={"province_id_list"},
                )
            },
            "highlight_state_targets": {
                "fields": _runtime_fields_from_structure(target_structure.get("column", []) if target_structure else [])
            },
            "targeted_modifier": {
                "fields": _runtime_fields_from_structure(targeted_modifier_structure.get("column", []) if targeted_modifier_structure else [])
            },
        },
    }


def _build_gfx_runtime_schema(data: dict[str, Any]) -> dict[str, Any]:
    structures = data.get("structure", [])
    if not isinstance(structures, list):
        raise KeyError("Structure list was not found in 'gfx_schema.toml'.")

    gfx_animation = _find_structure(data, "gfx_animation")
    types: dict[str, Any] = {}
    for structure in structures:
        if not isinstance(structure, dict):
            continue
        name = structure.get("name", "")
        if not name or name == "gfx_animation":
            continue
        types[name] = {
            "validate_fields": True,
            "fields": _runtime_fields_from_structure(
                structure.get("column", []),
                usage_mode=True,
                object_schemas={"gfx_animation"},
            ),
        }

    return {
        "schema_name": "hoi4_gfx",
        "file_scope": "interface",
        "root_pattern": "nested_named_block",
        "unknown_keys": "warn",
        "case_insensitive_keys": True,
        "types": types,
        "sub_schemas": {
            "gfx_animation": {
                "validate_fields": True,
                "fields": _runtime_fields_from_structure(gfx_animation.get("column", []) if gfx_animation else [], usage_mode=True),
            }
        },
    }


def _select_structure_schema(data: Any, filename: str, role: str = "", file_path: str = "") -> Any:
    if not isinstance(data, dict) or "structure" not in data:
        return data

    basename = os.path.basename(filename).lower()
    if basename == "event_schema.toml":
        return _build_event_runtime_schema(data)
    if basename == "achievement_schema.toml":
        return _build_achievement_runtime_schema(data)
    if basename == "decision_category_schema.toml":
        return _build_decision_category_runtime_schema(data)
    if basename == "decision_schema.toml":
        return _build_decision_runtime_schema(data, file_path=file_path)
    if basename == "gfx_schema.toml":
        return _build_gfx_runtime_schema(data)
    return data


def _normalise_rule_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.replace("/", os.sep)))


def _load_data(path: str) -> Any:
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None

    cache_key = (os.path.abspath(path), mtime)
    if cache_key in _data_cache:
        return _data_cache[cache_key]

    ext = os.path.splitext(path)[1].lower()
    if ext == ".toml":
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    else:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

    _data_cache[cache_key] = data
    return data


def plugin_element(plugin, element_id: str):
    if not plugin:
        raise ValueError("Plugin is required for syntax asset resolution.")
    if not element_id:
        raise ValueError("Element id is required for syntax asset resolution.")
    for element in getattr(plugin, "elements", []):
        if getattr(element, "id", None) == element_id:
            return element
    raise KeyError(f"Element '{element_id}' was not found in plugin '{getattr(plugin, 'id', '')}'.")


def _rule_matches_file(rule: dict[str, str], file_path: str) -> bool:
    rule_path = _normalise_rule_path(rule.get("path", ""))
    file_dir = _normalise_rule_path(os.path.dirname(file_path))
    return (
        file_dir == rule_path
        or file_dir.startswith(rule_path + os.sep)
        or file_dir.endswith(os.sep + rule_path)
        or (os.sep + rule_path + os.sep) in (os.sep + file_dir + os.sep)
    )


def schema_rule_for_element(element, file_path: str = "") -> Optional[dict[str, str]]:
    if not element:
        return None
    configured_rules = getattr(element, "raw", {}).get("schema_rules", [])
    if not isinstance(configured_rules, list) or not file_path:
        return None

    candidates = []
    for rule in configured_rules:
        if not isinstance(rule, dict) or not rule.get("path") or not rule.get("schema"):
            continue
        candidates.append(rule)

    candidates.sort(key=lambda rule: len(_normalise_rule_path(rule["path"])), reverse=True)
    for rule in candidates:
        if _rule_matches_file(rule, file_path):
            return rule
    return None


def _element_asset_path(element, filename: str) -> str:
    element_dir = getattr(element, "element_dir", "")
    return os.path.join(element_dir, filename)


def load_element_schema(element, file_path: str = "") -> Optional[dict]:
    rule = schema_rule_for_element(element, file_path)
    if rule:
        filename = rule.get("schema", "")
        role = rule.get("role", "")
    else:
        filename = getattr(element, "raw", {}).get("schema", "")
        role = ""

    if not filename:
        raise KeyError(f"Schema is not defined for element '{getattr(element, 'id', '')}'.")
    path = _element_asset_path(element, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    data = _load_data(path)
    return _select_structure_schema(data, filename, role=role, file_path=file_path)


def load_named_element_asset(element, filename: str, role: str = "", file_path: str = "") -> Optional[dict]:
    if not element:
        raise ValueError("Element is required to load an element asset.")
    if not filename:
        raise ValueError("Filename is required to load an element asset.")
    path = _element_asset_path(element, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    data = _load_data(path)
    return _select_structure_schema(data, filename, role=role, file_path=file_path)


def load_plugin_rule_data(plugin, rule_name: str) -> dict:
    if not plugin:
        raise ValueError("Plugin is required to load rule data.")
    if not rule_name:
        raise ValueError("Rule name is required to load rule data.")
    path = os.path.join(plugin.path, "grammar", "statements", f"{rule_name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    data = _load_data(path)
    if not isinstance(data, dict):
        raise TypeError(f"Rule data must be a JSON object: {path}")
    return data


def element_for_project_file(plugin, file_path: str):
    if not plugin:
        raise ValueError("Plugin is required to resolve element for a file.")
    if not file_path or str(file_path).startswith("untitled:"):
        raise ValueError("A concrete file path is required to resolve its element.")

    project_path = core.api.get_project_path()
    if not project_path:
        raise RuntimeError("Project path is not available.")

    try:
        rel_path = os.path.relpath(file_path, project_path)
        norm_rel_dir = os.path.normpath(os.path.dirname(rel_path))
        for element in getattr(plugin, "elements", []):
            element_path = os.path.normpath(getattr(element, "path", ""))
            if norm_rel_dir == element_path or norm_rel_dir.startswith(element_path + os.sep):
                return element
    except Exception as error:
        raise RuntimeError(f"Failed to resolve element for '{file_path}': {error}") from error
    raise KeyError(f"No element matched file '{file_path}'.")
