"""Remove empty properties and collections from scoped populated instances."""
from __future__ import annotations

from typing import Any, Iterable

from .paths import ElementPath


def _empty_property(node: dict[str, Any]) -> bool:
    value = node.get("value")
    if node.get("modelType") == "Property":
        return value is None or isinstance(value, str) and not value.strip()
    if node.get("modelType") == "MultiLanguageProperty":
        if value is None or value == []:
            return True
        return isinstance(value, list) and all(
            isinstance(entry, dict) and isinstance(entry.get("text"), str)
            and not entry["text"].strip() for entry in value
        )
    return False


def _prune(client: Any, identifier: str, node: dict[str, Any], path: ElementPath,
           result: dict[str, Any]) -> bool:
    # Reverse positional order prevents list deletions shifting later targets.
    for key in ("submodelElements", "value", "statements", "annotations"):
        children = node.get(key)
        if not isinstance(children, list):
            continue
        for index in range(len(children) - 1, -1, -1):
            child = children[index]
            if not isinstance(child, dict) or not child.get("modelType"):
                continue
            step = index if node.get("modelType") == "SubmodelElementList" else child.get("idShort")
            if step is None:
                continue
            child_path = ElementPath(path.steps + (step,))
            if _prune(client, identifier, child, child_path, result):
                # Reflect only confirmed deletions in this local snapshot. A
                # failed child deletion must prevent removal of its parent.
                children.pop(index)

    empty_collection = (node.get("modelType") == "SubmodelElementCollection"
                        and node.get("value", []) == [])
    if not path.steps or not (_empty_property(node) or empty_collection):
        return False
    record = {"submodel": identifier, "path": str(path)}
    try:
        client.delete_element(identifier, path)
    except Exception as exc:
        result["failed"].append({**record, "error": str(exc)})
        return False
    if empty_collection:
        record["modelType"] = "SubmodelElementCollection"
    result["removed"].append(record)
    return True


def remove_empty_properties(client: Any, submodel_ids: Iterable[str]) -> dict[str, Any]:
    """Re-read after writes; never enumerate the repository or modify templates."""
    result: dict[str, Any] = {"status": "completed", "removed": [], "failed": []}
    for identifier in dict.fromkeys(submodel_ids):
        try:
            submodel = client.get_submodel(identifier)
            if submodel.get("kind") == "Template":
                continue
            _prune(client, identifier, submodel, ElementPath(()), result)
        except Exception as exc:
            result["failed"].append({"submodel": identifier, "path": "", "error": str(exc)})
            continue
    if result["failed"]:
        result["status"] = "incomplete"
    return result
