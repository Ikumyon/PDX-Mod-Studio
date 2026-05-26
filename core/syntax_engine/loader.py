from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

from .models import ValueTypeRule


def load_toml_file(path: str | Path) -> dict[str, Any]:
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def load_value_types(raw: dict[str, Any]) -> dict[str, ValueTypeRule]:
    values = raw.get("value") or {}
    result: dict[str, ValueTypeRule] = {}
    for name, entry in values.items():
        if not isinstance(entry, dict):
            continue
        result[str(name)] = ValueTypeRule(
            name=str(name),
            pattern=entry.get("pattern"),
            literals=[str(item) for item in entry.get("literals", [])],
        )
    if "number" not in result:
        result["number"] = ValueTypeRule(name="number", pattern=r"-?[0-9]+(?:\.[0-9]+)?")
    return result
