from __future__ import annotations

import json
import os

from plugins.hoi4.base_editor import prop_text

TEXTURE_PROPERTIES = ("texturefile", "textureFile1", "textureFile2")


def first_texture_property(gfx_item) -> tuple[str | None, str]:
    for property_name in TEXTURE_PROPERTIES:
        actual_name = _actual_property_name(gfx_item, property_name)
        value = prop_text(gfx_item, actual_name) if actual_name else ""
        if value:
            return actual_name, value
    return None, ""


def _actual_property_name(gfx_item, property_name: str) -> str | None:
    if not gfx_item:
        return None
    if hasattr(gfx_item, "actual_key"):
        return gfx_item.actual_key(property_name)
    return property_name if gfx_item.first(property_name) else None


def active_plugin_path(widget) -> str | None:
    active_plugin = getattr(widget, "active_plugin", None)
    return getattr(active_plugin, "path", None)


def resolve_texture_path(
    texture_rel: str,
    project_path: str | None,
    plugin_path: str | None,
    *,
    allow_project_fallback: bool = True,
) -> str | None:
    if not texture_rel:
        return None

    if project_path:
        project_texture = os.path.normpath(os.path.join(project_path, texture_rel))
        if os.path.exists(project_texture):
            return project_texture

    game_path = _load_game_path(plugin_path)
    if game_path:
        game_texture = os.path.normpath(os.path.join(game_path, texture_rel))
        if os.path.exists(game_texture):
            return game_texture

    if project_path and allow_project_fallback:
        return os.path.normpath(os.path.join(project_path, texture_rel))

    return None


def _load_game_path(plugin_path: str | None) -> str | None:
    if not plugin_path:
        return None

    settings_file = os.path.join(plugin_path, "settings.json")
    if not os.path.exists(settings_file):
        return None

    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return settings.get("game_path")
    except Exception:
        return None
