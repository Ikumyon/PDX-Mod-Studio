from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any, Callable


def load_plugin_file_map(plugin_root: str | Path, manifest: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    assets_path = manifest.get("assets")
    if not isinstance(assets_path, str) or not assets_path:
        raise ValueError(f"Plugin '{plugin_id}' is missing the required 'assets' manifest entry.")
    target = resolve_plugin_asset_path(plugin_root, assets_path)
    with open(target, "rb") as handle:
        return tomllib.load(handle)


def resolve_plugin_asset_path(plugin_root: str | Path, relative_path: str | Path) -> Path:
    root = Path(plugin_root).resolve()
    target = (root / relative_path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Plugin asset path escapes plugin root: {relative_path}")
    return target


def require_plugin_file(plugin_root: str | Path, relative_path: str | Path, label: str) -> Path:
    target = resolve_plugin_asset_path(plugin_root, relative_path)
    if not target.is_file():
        raise FileNotFoundError(f"Required {label} file not found: {target}")
    return target


def resolve_file_map_path(file_map: dict[str, Any], dotted_key: str) -> str:
    current: Any = file_map
    walked: list[str] = []
    for part in dotted_key.split("."):
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            joined = ".".join(walked)
            raise ValueError(f"Missing '{joined}' in plugin assets.toml.")
        current = current[part]
    if not isinstance(current, str) or not current:
        raise ValueError(f"Invalid path for '{dotted_key}' in plugin assets.toml.")
    return current


def resolve_manifest_display_text(
    manifest: dict[str, Any],
    key_field: str,
    legacy_field: str,
    default: str,
    plugin_id: str,
    translate: Callable[[str, str | None], str],
) -> str:
    translation_key = manifest.get(key_field)
    if translation_key is not None:
        if not isinstance(translation_key, str) or not translation_key:
            raise ValueError(f"Plugin '{plugin_id}' has an invalid '{key_field}' in plugin_manifest.json.")
        return translate(translation_key, translation_key)

    legacy_value = manifest.get(legacy_field)
    if legacy_value is None:
        return default
    if not isinstance(legacy_value, str) or not legacy_value:
        raise ValueError(f"Plugin '{plugin_id}' has an invalid '{legacy_field}' in plugin_manifest.json.")
    return legacy_value


def translate_from_files_map(
    plugin_root: str | Path,
    manifest: dict[str, Any],
    key: str,
    fallback: str | None = None,
    language: str | None = None,
) -> str:
    fallback_text = fallback if fallback is not None else key
    if not key:
        return fallback_text or ""

    assets_path = manifest.get("assets")
    if not isinstance(assets_path, str) or not assets_path:
        raise ValueError("Plugin manifest is missing the required 'assets' entry.")

    file_map_path = require_plugin_file(plugin_root, assets_path, "plugin assets map")
    with open(file_map_path, "rb") as handle:
        file_map = tomllib.load(handle)

    translations_config = file_map.get("translations")
    if not isinstance(translations_config, dict):
        raise ValueError("Missing or invalid 'translations' object in plugin assets.toml.")

    directory_name = translations_config.get("directory")
    if not isinstance(directory_name, str) or not directory_name:
        raise ValueError("Missing or invalid 'translations.directory' in plugin assets.toml.")

    default_locale = translations_config.get("default")
    if default_locale is not None and (not isinstance(default_locale, str) or not default_locale):
        raise ValueError("Invalid 'translations.default' in plugin assets.toml.")

    translations_dir = resolve_plugin_asset_path(plugin_root, directory_name)
    if not translations_dir.is_dir():
        raise FileNotFoundError(f"Required translations directory not found: {translations_dir}")

    locale_entries: dict[str, str] = {}
    for file_path in translations_dir.glob("*.json"):
        locale_key = file_path.stem
        locale_entries[locale_key] = f"{directory_name}/{file_path.name}"

    target_locale = None
    if isinstance(language, str) and language in locale_entries:
        target_locale = language
    else:
        if isinstance(default_locale, str) and default_locale in locale_entries:
            target_locale = default_locale

    if not target_locale:
        requested = language if language else default_locale
        if requested:
            raise FileNotFoundError(f"Required translation locale file not found: {requested}")
        raise FileNotFoundError(f"No translation JSON files found in: {translations_dir}")

    translations = _load_translation_resource(Path(plugin_root), locale_entries[target_locale])
    value = translations.get(key)
    if isinstance(value, str) and value:
        return value
    return fallback_text


def extract_base_directory(glob_path: str) -> str:
    normalized = str(glob_path).replace("\\", "/")
    wildcard_positions = [pos for token in ("*", "?", "[") for pos in [normalized.find(token)] if pos >= 0]
    if wildcard_positions:
        return normalized[:min(wildcard_positions)].rstrip("/")
    normalized = normalized.rstrip("/")
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def _load_translation_resource(plugin_root: Path, relative_path: str) -> dict[str, str]:
    target = (plugin_root / relative_path).resolve()
    if target.is_dir():
        merged: dict[str, str] = {}
        key_sources: dict[str, Path] = {}
        for child in sorted(target.glob("*.json")):
            loaded = _load_translation_json_file(child)
            for key, value in loaded.items():
                existing_source = key_sources.get(key)
                if existing_source is not None:
                    raise ValueError(
                        f"Duplicate translation key '{key}' in '{existing_source}' and '{child}'."
                    )
                merged[key] = value
                key_sources[key] = child
        return merged
    return _load_translation_json_file(target)


def _load_translation_json_file(path: Path) -> dict[str, str]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Translation resource must be a JSON object: {path}")
    result: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result
