"""Lossless scalar transport for APIs that truncate string metadata previews."""
PREFIX = "globex.resource.runtime_field."
NULL = "__NULL__"


def runtime_trace_fields(row: dict) -> dict:
    attributes = {}
    def visit(value, path):
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, (*path, key))
        elif value is None or isinstance(value, (str, bool, int, float)):
            attributes[PREFIX + "/".join(path)] = NULL if value is None else value
        else:
            raise ValueError("runtime trace requires scalar-only schema")
    # Span startTime is the authoritative transport timestamp.
    visit({key: value for key, value in row.items() if key != "timestamp"}, ())
    attributes["globex.resource.runtime_field_count"] = len(attributes)
    return attributes


def restore_runtime_trace(attributes: dict, *, timestamp: str) -> dict | None:
    fields = {key[len(PREFIX):]: value for key, value in attributes.items() if key.startswith(PREFIX)}
    if not fields or len(fields) != attributes.get("globex.resource.runtime_field_count"):
        return None  # Never train on a silently truncated attribute set.
    result = {}
    for path, value in fields.items():
        pieces = path.split("/")
        cursor = result
        for piece in pieces[:-1]:
            cursor = cursor.setdefault(piece, {})
        cursor[pieces[-1]] = None if value == NULL else value
    if not isinstance(result.get("after"), dict) or not isinstance(result.get("forecast"), dict):
        return None
    result["timestamp"] = timestamp
    return result
