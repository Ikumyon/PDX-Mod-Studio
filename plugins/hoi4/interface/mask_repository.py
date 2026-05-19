from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MaskChoice:
    label: str
    config: dict[str, Any] | None


def load_mask_choices(interface_dir: str, languages: tuple[str, ...] = ("ja-jp", "en-us")) -> list[MaskChoice]:
    masks_dir = os.path.normpath(os.path.join(interface_dir, "masks"))
    loc_data = _load_localisation(masks_dir, languages)

    choices = [MaskChoice(loc_data.get("NO_MASK", "選択なし"), None)]
    if not os.path.exists(masks_dir):
        return choices

    for file_name in sorted(os.listdir(masks_dir)):
        if not file_name.endswith(".json"):
            continue

        file_path = os.path.join(masks_dir, file_name)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                mask_config = json.load(f)

            mask_id = mask_config.get("id")
            name_key = mask_config.get("name_key")
            display_name = loc_data.get(name_key, mask_id or file_name)
            choices.append(MaskChoice(display_name, mask_config))
        except Exception as e:
            print(f"Failed to load mask config {file_name}: {e}")

    return choices


def resolve_mask_image_path(interface_dir: str, mask_config: dict[str, Any]) -> str | None:
    file_name = mask_config.get("file")
    if not file_name:
        return None

    mask_path = os.path.normpath(os.path.join(interface_dir, "masks", file_name))
    return mask_path if os.path.exists(mask_path) else None


def _load_localisation(masks_dir: str, languages: tuple[str, ...]) -> dict[str, str]:
    for lang in languages:
        loc_path = os.path.join(masks_dir, "localisation", f"{lang}.json")
        if not os.path.exists(loc_path):
            continue
        try:
            with open(loc_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Failed to load localization {lang}.json: {e}")
    return {}
