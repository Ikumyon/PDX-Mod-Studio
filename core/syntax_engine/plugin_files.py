from __future__ import annotations

import json
from pathlib import Path
import tomllib
from typing import Any, Callable


def load_plugin_file_map(plugin_root: str | Path, manifest: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    files_path = manifest.get("files")
    if not isinstance(files_path, str) or not files_path:
        raise ValueError(f"Plugin '{plugin_id}' is missing the required 'files' manifest entry.")
    target = Path(plugin_root) / files_path
    with open(target, "rb") as handle:
        return tomllib.load(handle)


def resolve_file_map_path(file_map: dict[str, Any], dotted_key: str) -> str:
    current: Any = file_map
    walked: list[str] = []
    for part in dotted_key.split("."):
        walked.append(part)
        if not isinstance(current, dict) or part not in current:
            joined = ".".join(walked)
            raise ValueError(f"Missing '{joined}' in plugin files.toml.")
        current = current[part]
    if not isinstance(current, str) or not current:
        raise ValueError(f"Invalid path for '{dotted_key}' in plugin files.toml.")
    return current


def build_element_definitions_from_files(
    file_map: dict[str, Any],
    translate: Callable[[str, str | None], str],
    plugin_id: str,
) -> list[dict[str, Any]]:
    files = file_map.get("files")
    if not isinstance(files, list):
        raise ValueError(f"Plugin '{plugin_id}' is missing the required 'files' array in files.toml.")

    result: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(f"Plugin '{plugin_id}' has an invalid file entry in files.toml.")

        element_id = entry.get("id")
        name_key = entry.get("name_key")
        path = entry.get("path")
        schema = entry.get("schema")

        if not isinstance(element_id, str) or not element_id:
            raise ValueError(f"Plugin '{plugin_id}' has a file entry without a valid 'id' in files.toml.")
        if not isinstance(name_key, str) or not name_key:
            raise ValueError(f"Plugin '{plugin_id}' has a file entry without a valid 'name_key' in files.toml.")
        if not isinstance(path, str) or not path:
            raise ValueError(f"Plugin '{plugin_id}' has a file entry without a valid 'path' in files.toml.")
        if not isinstance(schema, str) or not schema:
            raise ValueError(f"Plugin '{plugin_id}' has a file entry without a valid 'schema' in files.toml.")

        base_dir = extract_base_directory(path)
        display_name = translate(name_key, name_key)
        result.append(
            {
                **entry,
                "id": element_id,
                "name": display_name,
                "path": base_dir,
                "resolved_name": display_name,
                "match_glob": path,
                "schema_rules": [
                    {
                        "path": base_dir,
                        "schema": schema,
                        "role": entry.get("role"),
                        "exclude": entry.get("exclude", []),
                    }
                ],
            }
        )
    return result


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

    files_path = manifest.get("files")
    if not isinstance(files_path, str) or not files_path:
        return fallback_text

    file_map_path = Path(plugin_root) / files_path
    with open(file_map_path, "rb") as handle:
        file_map = tomllib.load(handle)

    i18n = file_map.get("i18n")
    if not isinstance(i18n, dict):
        return fallback_text

    locale_entries: dict[str, str] = {}
    for locale_key, path_value in i18n.items():
        if locale_key == "default":
            continue
        if isinstance(path_value, str) and path_value:
            locale_entries[locale_key] = path_value

    target_locale = None
    if isinstance(language, str) and language in locale_entries:
        target_locale = language
    else:
        default_locale = i18n.get("default")
        if isinstance(default_locale, str) and default_locale in locale_entries:
            target_locale = default_locale
        elif locale_entries:
            target_locale = next(iter(locale_entries))

    if not target_locale:
        return fallback_text

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
