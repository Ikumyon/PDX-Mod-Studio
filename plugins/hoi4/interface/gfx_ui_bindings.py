from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox


GFX_SCHEMA_FIELD_BINDINGS = {
    "name": {"kind": "line", "controls": ("edit_name",)},
    "texturefile": {"kind": "line", "controls": ("edit_source_path",)},
    "texturefile1": {"kind": "line", "controls": ("edit_source_path1",)},
    "texturefile2": {"kind": "line", "controls": ("edit_source_path2",)},
    "maskfile": {"kind": "line", "controls": ("edit_mask",)},
    "effectfile": {"kind": "line", "controls": ("edit_effect",)},
    "color": {"kind": "line", "controls": ("edit_color",)},
    "colortwo": {"kind": "line", "controls": ("edit_color_two",)},
    "size": {"kind": "pair", "controls": ("spin_size_w", "spin_size_h")},
    "bordersize": {"kind": "pair", "controls": ("spin_border_x", "spin_border_y")},
    "noofframes": {"kind": "spin", "controls": ("spin_frames",)},
    "animation_rate_fps": {"kind": "spin", "controls": ("spin_rate",)},
    "pause_on_loop": {"kind": "spin", "controls": ("spin_pause_on_loop",)},
    "horizontal": {"kind": "check", "controls": ("check_horizontal",)},
    "allwaystransparent": {"kind": "check", "controls": ("check_transparent",)},
    "legacy_lazy_load": {"kind": "check", "controls": ("check_lazy_load",)},
    "transparencecheck": {"kind": "check", "controls": ("check_transparence",)},
    "looping": {"kind": "check", "controls": ("check_looping",)},
    "play_on_show": {"kind": "check", "controls": ("check_play_on_show",)},
}


GFX_SCHEMA_FIELD_VISIBILITY_BINDINGS = {
    "name": ("lblName", "widgetNameHost"),
    "texturefile": (
        "lblTexture",
        "editSourcePath",
        "btnBrowseSource",
    ),
    "texturefile1": (
        "lblTexture1",
        "editSourcePath1",
        "btnBrowseSource1",
    ),
    "texturefile2": (
        "lblTexture2",
        "editSourcePath2",
        "btnBrowseSource2",
    ),
    "effectfile": ("lblEffect", "editEffect", "btnSelectEffect"),
    "maskfile": ("lblMask", "editMask", "btnSelectMask"),
    "color": ("lblColor", "editColor"),
    "colortwo": ("lblColorTwo", "editColorTwo"),
    "size": ("lblSize", "lblSizeW", "spinSizeW", "lblSizeH", "spinSizeH"),
    "bordersize": ("lblBorderSize", "lblBorderX", "spinBorderX", "lblBorderY", "spinBorderY"),
    "horizontal": ("lblHorizontal", "checkHorizontal"),
    "allwaystransparent": ("lblTransparent", "checkTransparent"),
    "legacy_lazy_load": ("lblLazyLoad", "checkLazyLoad"),
    "transparencecheck": ("lblTransparenceCheck", "checkTransparenceCheck"),
    "noofframes": ("lblFrames", "spinFrames"),
    "animation_rate_fps": ("lblRate", "spinRate"),
    "looping": ("lblLooping", "checkLooping"),
    "play_on_show": ("lblPlayOnShow", "checkPlayOnShow"),
    "pause_on_loop": ("lblPauseOnLoop", "spinPauseOnLoop"),
    "animationmaskfile": ("lblAnimMask", "editAnimMask", "btnSelectAnimMask"),
    "animationtexturefile": ("lblAnimTexture", "editAnimTexture", "btnSelectAnimTexture"),
    "animationrotation": ("lblAnimRotation", "spinAnimRotation"),
    "animationlooping": ("lblAnimLooping", "checkAnimLooping"),
    "animationtime": ("lblAnimTime", "spinAnimTime"),
    "animationdelay": ("lblAnimDelay", "spinAnimDelay"),
    "animationblendmode": ("lblAnimBlend", "comboAnimBlend"),
    "animationrotationoffset": (
        "lblAnimRotOffset",
        "lblAnimRotX",
        "spinAnimRotX",
        "lblAnimRotY",
        "spinAnimRotY",
    ),
    "animationtexturescale": (
        "lblAnimScale",
        "lblAnimScaleX",
        "spinAnimScaleX",
        "lblAnimScaleY",
        "spinAnimScaleY",
    ),
    "animationtype": ("lblAnimType", "editAnimType"),
}


def schema_types(schema: Optional[dict]) -> list[str]:
    if not schema:
        return []
    return list(schema.get("types", {}).keys())


def schema_type_name(schema: Optional[dict], definition_type: str) -> Optional[str]:
    if not schema or not definition_type:
        return None

    types = schema.get("types", {})
    if definition_type in types:
        return definition_type

    normalized = definition_type.lower()
    for type_key in types.keys():
        if type_key.lower() == normalized:
            return type_key
    return None


def schema_type_definition(schema: Optional[dict], definition_type: str) -> Optional[dict]:
    if not schema or not definition_type:
        return None

    type_name = schema_type_name(schema, definition_type)
    if not type_name:
        return None

    type_schema = schema.get("types", {}).get(type_name)

    result = dict(type_schema)
    result["case_insensitive_keys"] = bool(schema.get("case_insensitive_keys"))
    result["sub_schemas"] = schema.get("sub_schemas", {})
    return result


def required_fields_tooltip(required_fields: list[str]) -> str:
    if not required_fields:
        return "必須項目はありません"
    return "必須項目: " + ", ".join(required_fields)


def missing_required_tooltip(missing_fields: list[str]) -> str:
    if not missing_fields:
        return "必須項目がそろっています"
    return "不足している必須項目: " + ", ".join(missing_fields)


def apply_type_tooltip(combo: QComboBox, index: int, type_name: str, required_fields: list[str]) -> None:
    tooltip = f"{type_name}\n{required_fields_tooltip(required_fields)}"
    combo.setItemData(index, tooltip, Qt.ItemDataRole.ToolTipRole)


def populate_type_combo(combo: Optional[QComboBox], schema: Optional[dict], current_type: str = "") -> str:
    if not combo:
        return ""

    type_names = schema_types(schema)
    match_name = schema_type_name(schema, current_type) or current_type

    was_blocked = combo.blockSignals(True)
    combo.clear()
    for type_name in type_names:
        combo.addItem(type_name, type_name)
        apply_type_tooltip(combo, combo.count() - 1, type_name, schema_required_fields(schema, type_name))

    if match_name and combo.findText(match_name) < 0:
        combo.addItem(match_name, match_name)
        apply_type_tooltip(combo, combo.count() - 1, match_name, [])

    selected = ""
    if match_name:
        index = combo.findText(match_name)
        if index >= 0:
            combo.setCurrentIndex(index)
            selected = combo.currentText()
    elif combo.count() > 0:
        combo.setCurrentIndex(0)
        selected = combo.currentText()

    combo.blockSignals(was_blocked)
    return selected


def schema_required_fields(
    schema: Optional[dict],
    definition_type: str,
    bindings: Optional[dict[str, dict]] = None,
) -> list[str]:
    type_schema = schema_type_definition(schema, definition_type)
    if not type_schema:
        return []

    field_bindings = bindings or GFX_SCHEMA_FIELD_BINDINGS
    fields = type_schema.get("fields", {})
    required = []
    for field_name, field_def in fields.items():
        if field_def.get("usage") != "required":
            continue
        if field_name.lower() not in field_bindings:
            continue
        required.append(field_name)
    return required


def schema_fields_with_usage(
    schema: Optional[dict],
    definition_type: str,
) -> list[tuple[str, str]]:
    type_schema = schema_type_definition(schema, definition_type)
    if not type_schema:
        return []

    result = []
    for field_name, field_def in type_schema.get("fields", {}).items():
        result.append((field_name, field_def.get("usage", "optional")))
    return result


def schema_sub_fields_with_usage(
    schema: Optional[dict],
    definition_type: str,
    field_name: str,
) -> list[tuple[str, str]]:
    type_schema = schema_type_definition(schema, definition_type)
    if not type_schema:
        return []

    field_def = None
    normalized = field_name.lower()
    for candidate_name, candidate_def in type_schema.get("fields", {}).items():
        if candidate_name.lower() == normalized:
            field_def = candidate_def
            break
    if not field_def:
        return []

    sub_schema_name = field_def.get("schema")
    if not sub_schema_name:
        return []

    sub_schema = type_schema.get("sub_schemas", {}).get(sub_schema_name, {})
    result = []
    for sub_field_name, sub_field_def in sub_schema.get("fields", {}).items():
        result.append((sub_field_name, sub_field_def.get("usage", "optional")))
    return result


def schema_visible_fields(
    schema: Optional[dict],
    definition_type: str,
) -> list[str]:
    type_schema = schema_type_definition(schema, definition_type)
    if not type_schema:
        return []

    visible = []
    seen = set()
    fields = type_schema.get("fields", {})
    sub_schemas = type_schema.get("sub_schemas", {})

    def add_field(field_name: str) -> None:
        normalized = field_name.lower()
        if normalized in seen:
            return
        seen.add(normalized)
        visible.append(field_name)

    for field_name, field_def in fields.items():
        add_field(field_name)
        sub_schema_name = field_def.get("schema")
        if not sub_schema_name:
            continue
        sub_schema = sub_schemas.get(sub_schema_name, {})
        for sub_field_name in sub_schema.get("fields", {}).keys():
            add_field(sub_field_name)

    return visible
