"""Explicit JSON-pointer adapters: never guess a controller's identity or health."""
import json
import re
from datetime import datetime, timezone


class SchemaError(ValueError):
    pass


def parse_json(text):
    """Accept pure JSON or one JSON object surrounded by ARCCONF status text."""
    if re.search(r"(?mi)^Invalid arguments\.\s*$", text):
        raise SchemaError("ARCCONF reported invalid arguments")
    decoder = json.JSONDecoder()
    candidates = []
    index = 0
    while index < len(text):
        if text[index] not in "[{":
            index += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, index)
        except ValueError:
            index += 1
            continue
        if isinstance(obj, (dict, list)):
            candidates.append(obj)
        index = end
    if len(candidates) != 1:
        raise SchemaError("Expected exactly one JSON document")
    return candidates[0]


def pointer(obj, path):
    if path == "":
        return obj
    if not isinstance(path, str) or not path.startswith("/"):
        raise SchemaError("Adapter paths must be JSON pointers")
    try:
        for part in path[1:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            obj = obj[int(part)] if isinstance(obj, list) else obj[part]
        return obj
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SchemaError("Missing or invalid adapter path: " + path) from exc


def _rows(obj, path):
    rows = pointer(obj, path)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise SchemaError("Expected object array at " + path)
    return rows


def _mapped(obj, mapping):
    return {key: pointer(obj, path) for key, path in mapping.items()}


def _required(row, fields):
    if any(row.get(k) is None or row.get(k) == "" for k in fields):
        raise SchemaError("Missing identity fields: " + ", ".join(fields))


def normalize(raw, adapter):
    """Return versioned, serializable inventory. Raw values stay in memory only.

    Adapter mapping is installed after comparing GETCONFIGJSON SCHEMA with real
    captures. Unknown statuses remain unknown and never qualify as healthy.
    """
    if isinstance(raw, dict) and "$schema" in raw:
        raise SchemaError("A schema document is not an inventory")
    controllers = []
    for source in _rows(raw, adapter["controllers"]):
        c = _mapped(source, adapter["controller_fields"])
        _required(c, ("id", "serial", "model", "status"))
        try:
            c["id"] = int(c["id"])
        except (ValueError, TypeError) as exc:
            raise SchemaError("Controller ID must be numeric") from exc
        if c["id"] < 1:
            raise SchemaError("Controller ID must be positive")
        for kind in ("physical", "logical"):
            c[kind] = [_mapped(r, adapter[kind + "_fields"])
                       for r in _rows(source, adapter[kind])]
        for d in c["physical"]:
            _required(d, ("serial", "channel", "id", "status"))
        for d in c["logical"]:
            _required(d, ("id", "raid", "status"))
        statuses = adapter.get("healthy_statuses", {})
        c["healthy"] = c["status"] in statuses.get("controller", [])
        for kind in ("physical", "logical"):
            for d in c[kind]:
                d["healthy"] = d["status"] in statuses.get(kind, [])
        controllers.append(c)
    for key in ("serial", "id"):
        values = [c[key] for c in controllers]
        if len(values) != len(set(values)):
            raise SchemaError("Duplicate controller " + key)
    for c in controllers:
        serials = [d["serial"] for d in c["physical"]]
        addresses = [(d["channel"], d["id"]) for d in c["physical"]]
        if len(set(serials)) != len(serials) or len(set(addresses)) != len(addresses):
            raise SchemaError("Ambiguous physical device identity")
    return {"schema_version": 1, "observed_at": datetime.now(timezone.utc).isoformat(),
            "adapter": adapter["name"], "controllers": controllers}
