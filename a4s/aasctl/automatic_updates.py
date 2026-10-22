"""Template-led editing: classify families, stage replacements, carry facts to review.

The browser selects standardized templates, never mutation strategies or target
SM IDs. Live changes remain the responsibility of reviewed updates.commit.
"""

from __future__ import annotations

import copy
import json
import re

from . import updates
from .index import concept_map, enrich, walk
from .match import Entity
from .submodel_categories import classify as classify_categories


def _family_id(identifier: str) -> str:
    identifier = identifier.rstrip("/").casefold()
    # SAMM versions and standard URL version segments may change while the
    # named concept remains the same. Do not strip arbitrary digits in names.
    identifier = re.sub(r":\d+\.\d+\.\d+(?=#|$)", ":{version}", identifier)
    identifier = re.sub(r"/(?:v?\d+\.)+\d+(?=/|$)", "/{version}", identifier)
    identifier = re.sub(r"/(?:\d+/)+\d+(?=/|$)", "/{version}", identifier)
    return identifier


def _semantics(model):
    return {
        tuple(_family_id(key["value"]) for key in reference.get("keys", []) if key.get("value"))
        for reference in [model.get("semanticId"), *(model.get("supplementalSemanticIds") or [])]
        if reference and any(key.get("value") for key in reference.get("keys", []))
    }


def same_family(template: dict, other: dict) -> bool:
    origin = (other.get("administration") or {}).get("templateId")
    if origin and _family_id(origin) == _family_id(template["id"]):
        return True
    left, right = _semantics(template), _semantics(other)
    if left and right:
        return bool(left & right)
    # Older instances sometimes omitted semanticId and templateId entirely.
    # Only use an exact readable-name fallback when semantic evidence is absent.
    return (
        bool(template.get("idShort"))
        and template.get("idShort", "").casefold() == other.get("idShort", "").casefold()
    )


def _facts(model: dict, concepts=None):
    nodes = walk(model)
    enrich(nodes, concept_map(concepts or []))
    for node in nodes:
        element = updates._locate(model, node.path)
        kind = node.model_type
        if kind == "Range":
            if element.get("min") is None and element.get("max") is None:
                continue
            value = f"{element.get('min', '')} - {element.get('max', '')}"
        elif kind == "MultiLanguageProperty":
            value = "; ".join(
                f"{entry['text']}@{entry['language']}"
                for entry in element.get("value") or []
                if entry.get("text")
            )
        elif kind in ("Property", "File", "Blob", "ReferenceElement"):
            value = element.get("value")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
        else:
            continue
        if value is None or not str(value).strip():
            continue
        yield {
            "entity": node.id_short or node.path,
            "value": str(value),
            "description": f"{model.get('idShort', '')} / {node.path}. {node.definition or node.description}",
            "unit": node.unit,
            "source": f"existing-aas:{model['id']}#{node.path}",
            "model_type": kind,
            "value_type": element.get("valueType", ""),
            "element": copy.deepcopy(element),
            "submodelId": model["id"],
            "submodelName": model.get("idShort", ""),
            "path": node.path,
        }


def prepare(
    store, client, endpoint, aas_id, template_ids, source_client, source_endpoint, concepts=None
):
    templates = [
        source_client.get_submodel(identifier) for identifier in dict.fromkeys(template_ids)
    ]
    for index, template in enumerate(templates):
        if any(same_family(template, previous) for previous in templates[:index]):
            raise updates.UpdateError("Choose only one template version for each submodel category")
    draft = updates.prepare(
        store,
        client,
        endpoint,
        aas_id,
        [
            {
                "templateId": template["id"],
                "mode": "add",
                "releaseHash": store.release(source_endpoint, template)["hash"],
            }
            for template in templates
        ],
        source_client,
        source_endpoint,
        concepts,
    )
    before = draft["before"]["submodels"]
    assessment = classify_categories(templates, before)
    categories = {row['templateId']: row for row in assessment['replacements']}
    groups, inputs, claimed = [], [], set()
    for template, selection in zip(templates, draft["selections"]):
        matches = categories[template['id']]['replaces']
        if claimed.intersection(matches):
            raise updates.UpdateError(
                "Selected templates overlap in submodel category; choose one version"
            )
        claimed.update(matches)
        for key in matches:
            inputs.extend(_facts(before[key], concepts))
            draft["candidate"]["submodels"].pop(key)
        groups.append(
            {
                "templateId": template["id"],
                "name": template.get("idShort", ""),
                "candidateId": selection["candidateId"],
                "replaces": matches,
                "reason": categories[template['id']]['reason'],
            }
        )
    draft["candidate"]["shell"]["submodels"] = [
        updates._reference(key) for key in draft["candidate"]["submodels"]
    ]
    # Unrelated existing instances are still valid matching destinations.
    draft.update(
        automatic=True,
        replacementGroups=groups,
        legacyInputs=inputs,
        categoryAssessment=assessment,
        activeIds=list(draft["candidate"]["submodels"]),
    )
    store.put(draft)
    return draft


def matching_inputs(draft, entities):
    return [*entities, *(Entity.parse(row) for row in draft.get("legacyInputs", []))]


def review_rows(draft, rows):
    """Expose sources and conflicts; never silently prefer a document or old value."""
    legacy = {row["source"]: row for row in draft.get("legacyInputs", [])}
    grouped, result = {}, []
    for row in rows:
        fact = legacy.get(row.get("source"))
        row = {
            **row,
            "inputOrigin": "Existing data" if fact else "New input",
            "inputLocation": f"{fact['submodelName']} / {fact['path']}"
            if fact
            else row.get("source", ""),
        }
        if row.get("action") not in ("write", "create"):
            result.append(row)
            continue
        path = row.get("apiPath", "")
        if row["action"] == "create":
            path += "/" + row.get("aasProperty", "")
        grouped.setdefault((row["submodelId"], path), []).append(row)
    for (identifier, path), alternatives in grouped.items():
        distinct = {}
        for row in alternatives:
            key = (str(row.get("extractedValue")), row.get("aasType"), row.get("unit"))
            if key in distinct:
                existing = distinct[key]
                existing["inputOrigin"] = (
                    "Existing data + new input"
                    if existing["inputOrigin"] != row["inputOrigin"]
                    else existing["inputOrigin"]
                )
                existing["inputLocation"] += "; " + row["inputLocation"]
                if row.get("source") in legacy:
                    existing["source"] = row["source"]  # Keep typed native payload on equal facts.
            else:
                distinct[key] = row
        for row in distinct.values():
            if len(distinct) > 1:
                row.update(selected=False, valueConflict=True, conflictGroup=f"{identifier}#{path}")
            result.append(row)
    return result
