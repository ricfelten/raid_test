"""Inspect vendor captures without confusing diagnostics or schema with inventory."""
import re
from .inventory import parse_json, SchemaError


def diagnostics(text):
    counts = {int(value) for value in re.findall(r"(?mi)^Controllers found:\s*(\d+)\s*$", text)}
    return {
        "reported_controller_count": next(iter(counts)) if len(counts) == 1 else None,
        "conflicting_controller_counts": len(counts) > 1,
        "invalid_arguments": bool(re.search(r"(?mi)^Invalid arguments\.\s*$", text)),
    }


def inspect_capture(text):
    """Classification only; a zero-count banner is never a successful inventory."""
    result = diagnostics(text)
    if result["invalid_arguments"]:
        return {**result, "kind": "command-error", "inventory_valid": False}
    try:
        document = parse_json(text)
    except SchemaError:
        return {**result, "kind": "text-diagnostic", "inventory_valid": False}
    if isinstance(document, dict) and "$schema" in document:
        from .vendor_schema import summarize
        return {**result, "kind": "schema", "inventory_valid": False,
                "schema": summarize(document)}
    return {**result, "kind": "json-candidate", "inventory_valid": False,
            "note": "Requires a validated inventory adapter; JSON syntax alone does not establish inventory validity"}
