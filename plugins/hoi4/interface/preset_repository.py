from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PresetChoice:
    label: str
    config: dict[str, Any] | None


def load_preset_choices(interface_dir: str, languages: tuple[str, ...] = ("ja-jp", "en-us")) -> list[PresetChoice]:
    presets_dir = os.path.normpath(os.path.join(interface_dir, "presets"))
    loc_data = _load_localisation(presets_dir, languages)

    choices = [PresetChoice(loc_data.get("PRESET_CUSTOM", "カスタム"), None)]
    if not os.path.exists(presets_dir):
        return choices

    for file_name in sorted(os.listdir(presets_dir)):
        if not file_name.endswith(".json"):
            continue

        file_path = os.path.join(presets_dir, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                preset_config = json.load(f)

            preset_id = preset_config.get("id")
            name_key = preset_config.get("name_key")
            display_name = loc_data.get(name_key, preset_id or file_name)
            choices.append(PresetChoice(display_name, preset_config))
        except Exception as e:
            print(f"Failed to load preset config {file_name}: {e}")

    return choices


def _load_localisation(presets_dir: str, languages: tuple[str, ...]) -> dict[str, str]:
    for lang in languages:
        loc_path = os.path.join(presets_dir, "localisation", f"{lang}.json")
        if not os.path.exists(loc_path):
            continue
        try:
            with open(loc_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load localization {lang}.json: {e}")
    return {}
