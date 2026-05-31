from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import re
import tomllib
from typing import Any

from .models import ValueTypeRule


def load_toml_file(path: str | Path) -> dict[str, Any]:
    with open(path, "rb") as handle:
        return tomllib.load(handle, parse_float=Decimal)


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

        fixed_point_scale = entry.get("fixed_point_scale")
        if fixed_point_scale is not None:
            if not isinstance(fixed_point_scale, int) or isinstance(fixed_point_scale, bool) or fixed_point_scale <= 1:
                raise ValueError(f"Value type '{name}' has an invalid 'fixed_point_scale'.")
            if str(fixed_point_scale) != "1" + ("0" * (len(str(fixed_point_scale)) - 1)):
                raise ValueError(f"Value type '{name}' must define 'fixed_point_scale' as a power of 10.")

        min_val = entry.get("min")
        if min_val is not None and not isinstance(min_val, (int, float, Decimal)):
            raise ValueError(f"Value type '{name}' has an invalid 'min'.")

        max_val = entry.get("max")
        if max_val is not None and not isinstance(max_val, (int, float, Decimal)):
            raise ValueError(f"Value type '{name}' has an invalid 'max'.")

        if min_val is not None:
            min_val = Decimal(str(min_val))
        if max_val is not None:
            max_val = Decimal(str(max_val))

        if fixed_point_scale is not None:
            if min_val is None or max_val is None:
                raise ValueError(f"Value type '{name}' defines 'fixed_point_scale' but is missing 'min' or 'max'.")
            if not pattern:
                raise ValueError(f"Value type '{name}' defines 'fixed_point_scale' but is missing a 'pattern'.")
            scale_digits = len(str(fixed_point_scale)) - 1
            min_val = _scale_fixed_limit(min_val, fixed_point_scale, scale_digits, name, "min")
            max_val = _scale_fixed_limit(max_val, fixed_point_scale, scale_digits, name, "max")

        if min_val is not None and max_val is not None and min_val > max_val:
            raise ValueError(f"Value type '{name}' has min greater than max.")

        min_max_severity = entry.get("min_max_severity", "warning")
        if min_max_severity not in {"error", "warning"}:
            raise ValueError(f"Value type '{name}' has an invalid 'min_max_severity'.")

        if min_val is not None or max_val is not None or fixed_point_scale is not None:
            if not pattern:
                raise ValueError(f"Value type '{name}' defines numeric bounds but is missing a 'pattern'.")
            
            invalid_tests = ["a", "abc", "yes", "123a"]
            for test_val in invalid_tests:
                if re.fullmatch(pattern, test_val) is not None:
                    raise ValueError(
                        f"Value type '{name}' defines numeric bounds but its 'pattern' allows non-numeric "
                        f"value '{test_val}', which is invalid for numeric range validation."
                    )

        result[str(name)] = ValueTypeRule(
            name=str(name),
            pattern=pattern,
            literals=[str(item) for item in literals],
            literals_from=literals_from,
            children=children,
            min=min_val,
            max=max_val,
            fixed_point_scale=fixed_point_scale,
            min_max_severity=min_max_severity,
        )

    return result


def _scale_fixed_limit(value: Decimal, fixed_scale: int, scale_digits: int, type_name: str, field_name: str) -> int:
    scaled = value * fixed_scale
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"Value type '{type_name}' has '{field_name}' with more than {scale_digits} fixed-point decimal places."
        )
    return int(scaled)
