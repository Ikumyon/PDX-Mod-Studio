from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any

from .models import ValueTypeRule


def load_toml_file(path: str | Path) -> dict[str, Any]:
    with open(path, "rb") as handle:
        return tomllib.load(handle)


def load_value_types(raw: dict[str, Any]) -> dict[str, ValueTypeRule]:
    values = raw.get("value")
    if not isinstance(values, dict) or not values:
        raise ValueError("Missing or invalid '[value]' definitions in values TOML.")

    result: dict[str, ValueTypeRule] = {}
    for name, entry in values.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Value type '{name}' must be a TOML table.")

        pattern = entry.get("pattern")
        if pattern is not None and not isinstance(pattern, str):
            raise ValueError(f"Value type '{name}' has an invalid 'pattern'.")

        literals = entry.get("literals", [])
        if not isinstance(literals, list):
            raise ValueError(f"Value type '{name}' has an invalid 'literals'.")

        literals_from = entry.get("literals_from", False)
        if not isinstance(literals_from, bool):
            raise ValueError(f"Value type '{name}' has an invalid 'literals_from'.")

        children = entry.get("children", False)
        if not isinstance(children, bool):
            raise ValueError(f"Value type '{name}' has an invalid 'children'.")

        result[str(name)] = ValueTypeRule(
            name=str(name),
            pattern=pattern,
            literals=[str(item) for item in literals],
            literals_from=literals_from,
            children=children,
        )
    return result
