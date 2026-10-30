"""Read ARCCONF's schema-shaped field catalog, not a live inventory.

The supplied document uses vendor entity nesting and enumDescriptions. It is
not sufficient to establish live JSON record layout or hardware capabilities.
"""
from .inventory import SchemaError


def entities(document):
    if not isinstance(document, dict) or "$schema" not in document or "System" not in document:
        raise SchemaError("Expected an ARCCONF field catalog")
    found = {}
    def visit(node, path):
        if not isinstance(node, dict):
            return
        if isinstance(node.get("properties"), dict):
            found[path] = node["properties"]
        for key, child in node.items():
            if key not in ("properties", "$schema"):
                visit(child, path + "/" + key.replace("~", "~0").replace("/", "~1"))
    visit(document, "")
    return found


def enum_value(document, entity, field, value):
    """Decode for display while preserving raw value and vendor inconsistencies.

    Never use the display label alone to authorize operations. In particular,
    RAID code 16 is described as 6 but omitted from the supplied enum list.
    """
    properties = entities(document).get(entity)
    if properties is None or not isinstance(properties.get(field), dict):
        raise SchemaError("Unknown schema entity or field")
    definition = properties[field]
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        key = None
    else:
        key = str(value)
    labels = definition.get("enumDescriptions", {})
    allowed = {str(v) for v in definition.get("enum", [])}
    return {"raw": value, "label": labels.get(key, "Unknown"),
            "described": key in labels, "listed": key in allowed,
            "consistent": key in labels and key in allowed}


def summarize(document):
    catalog = entities(document)
    issues = []
    for entity, properties in catalog.items():
        for field, definition in properties.items():
            if not isinstance(definition, dict):
                continue
            descriptions = definition.get("enumDescriptions")
            if not isinstance(descriptions, dict):
                continue
            allowed = {str(v) for v in definition.get("enum", [])}
            described = set(descriptions)
            if allowed != described:
                issues.append({"entity": entity, "field": field,
                               "described_but_not_listed": sorted(described - allowed),
                               "listed_but_not_described": sorted(allowed - described)})
    return {"declared_schema": document["$schema"],
            "entities": {path: len(fields) for path, fields in catalog.items()},
            "enum_inconsistencies": issues,
            "live_record_layout_verified": False}
