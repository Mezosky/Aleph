from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aleph.core.errors import SchemaMismatchError


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    return value


def validate_json(value: Any, schema_name: str, schema_dir: str | Path = "schemas") -> None:
    from jsonschema import Draft202012Validator, RefResolver

    root = Path(schema_dir).resolve()
    path = root / schema_name
    schema = json.loads(path.read_text(encoding="utf-8"))
    store: dict[str, Any] = {}
    for candidate in root.glob("*.json"):
        loaded = json.loads(candidate.read_text(encoding="utf-8"))
        store[loaded["$id"]] = loaded
        store[candidate.name] = loaded
    resolver = RefResolver(base_uri=root.as_uri() + "/", referrer=schema, store=store)
    errors = sorted(
        Draft202012Validator(schema, resolver=resolver).iter_errors(_jsonable(value)),
        key=lambda error: list(error.path),
    )
    if errors:
        error = errors[0]
        pointer = "/" + "/".join(str(part) for part in error.path)
        raise SchemaMismatchError(error.message, schema_name=schema_name, pointer=pointer)


def export_json(
    value: Any,
    path: str | Path,
    *,
    schema_name: str | None = None,
    schema_dir: str | Path = "schemas",
) -> bool:
    """Write stable JSON only when bytes changed; return whether it changed."""
    if schema_name:
        validate_json(value, schema_name, schema_dir)
    target = Path(path)
    rendered = json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target.exists() and target.read_text(encoding="utf-8") == rendered:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8")
    return True
