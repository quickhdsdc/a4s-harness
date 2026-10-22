"""Reviewed AAS updates: isolated candidates, immutable releases and durable history.

Repository I/O stays behind the existing client interface. Preparing and reviewing
never writes to that repository. A commit journals intent before external I/O;
it does not pretend multiple REST calls are a transaction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .client import AasHttpError
from .index import walk
from .paths import ElementPath
from .population_cleanup import _empty_property
from .smt import cardinality, instantiate


class UpdateError(ValueError):
    """An update cannot be prepared or executed without an explicit decision."""


class Conflict(UpdateError):
    """The reviewed baseline or state no longer permits this operation."""


def digest(value: Any) -> str:
    # Object key order is irrelevant; array order (especially SMLs) is retained.
    # AAS optional null members and absent members have the same meaning. Java
    # omits some null values when serializing a full SME after replacement.
    def normalized(item):
        if isinstance(item, dict):
            result = {key: normalized(val) for key, val in item.items() if val is not None}
            # Java BaSyx omits an empty optional List value on read-back.
            # Missing/null/[] all mean zero items. Nonempty Lists stay ordered
            # and every element and type declaration still participates.
            if item.get('modelType') == 'SubmodelElementList' and result.get('value') == []:
                result.pop('value')
            if item.get("modelType") == "AssetAdministrationShell" and "submodels" in result:
                result["submodels"] = sorted(
                    result["submodels"], key=lambda ref: json.dumps(ref, sort_keys=True)
                )
            return result
        if isinstance(item, list):
            return [normalized(val) for val in item]
        return item

    return hashlib.sha256(
        json.dumps(
            normalized(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def repository(value: str) -> str:
    parts = urlsplit(value)
    if (
        parts.scheme not in ("http", "https")
        or not parts.netloc
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise UpdateError(
            "Repository must be an HTTP(S) base URL without credentials, query or fragment"
        )
    return value.rstrip("/")


def refs(shell: dict) -> list[str]:
    return list(
        dict.fromkeys(
            k["value"]
            for r in shell.get("submodels", [])
            for k in r.get("keys", [])
            if k.get("type") == "Submodel" and k.get("value")
        )
    )


def snapshot(client, aas_id: str) -> dict:
    shell = client.get_shell(aas_id)
    models = {}
    for identifier in refs(shell):
        models[identifier] = client.get_submodel(identifier)
    return {"shell": shell, "submodels": models}


class Store:
    """Durable drafts/releases/history; never in disposable wizard scratch."""

    def __init__(self, path: Path | None = None):
        home = Path(os.environ.get("A4S_HOME", Path.home() / ".a4s")).expanduser()
        self.path = path or home / "instance-updates.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS updates (
                    id TEXT PRIMARY KEY, endpoint TEXT NOT NULL, aas TEXT NOT NULL,
                    created REAL NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS by_asset ON updates(endpoint, aas, created);
                CREATE TABLE IF NOT EXISTS releases (
                    hash TEXT PRIMARY KEY, source TEXT NOT NULL, template TEXT NOT NULL,
                    payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def asset_lock(self, endpoint: str, aas: str):
        """Cross-process exclusion; OS releases it if a worker crashes."""
        folder = self.path.parent / "instance-update-locks"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / digest([endpoint, aas])
        with path.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            acquired = False
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                yield
            except OSError as exc:
                if not acquired:
                    raise Conflict("Another update for this AAS is running") from exc
                raise
            finally:
                if acquired:
                    handle.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle, fcntl.LOCK_UN)

    def put(self, draft: dict, expected: dict | None = None):
        with self.connect() as db:
            if expected is not None:
                changed = db.execute(
                    "UPDATE updates SET status=?,payload=? WHERE id=? AND payload=?",
                    (
                        draft["status"],
                        json.dumps(draft, ensure_ascii=False),
                        draft["id"],
                        json.dumps(expected, ensure_ascii=False),
                    ),
                )
                if changed.rowcount != 1:
                    raise Conflict("Update changed concurrently; load the current review again")
                return
            db.execute(
                "INSERT INTO updates VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,payload=excluded.payload",
                (
                    draft["id"],
                    draft["endpoint"],
                    draft["aasId"],
                    draft["createdAt"],
                    draft["status"],
                    json.dumps(draft, ensure_ascii=False),
                ),
            )

    def get(self, identifier: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM updates WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise UpdateError("Unknown update")
        return json.loads(row[0])

    def release(self, source: str, template: dict, family: str = "") -> dict:
        value = {"source": repository(source), "template": template}
        key = digest(value)
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO releases VALUES(?,?,?,?)",
                (key, value["source"], template["id"], json.dumps(value, ensure_ascii=False)),
            )
        admin = template.get("administration") or {}
        return {
            "hash": key,
            "id": template["id"],
            "source": value["source"],
            "name": template.get("idShort", ""),
            "family": family,
            "version": admin.get("version", ""),
            "revision": admin.get("revision", ""),
            "semanticId": template.get("semanticId"),
        }

    def releases(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT hash,payload FROM releases ORDER BY rowid DESC").fetchall()
        return [{"hash": key, **json.loads(raw)} for key, raw in rows]

    def retain(self, path: Path) -> dict:
        """Retain source evidence independently of disposable wizard files."""
        contents = path.read_bytes()
        key = hashlib.sha256(contents).hexdigest()
        directory = self.path.parent / "instance-update-artifacts"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / key
        if not target.exists():
            temporary = directory / (key + "." + uuid.uuid4().hex + ".partial")
            temporary.write_bytes(contents)
            os.replace(temporary, target)
        return {"hash": key, "filename": path.name, "bytes": len(contents)}

    def history(self, endpoint: str, aas: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM updates WHERE endpoint=? AND aas=? ORDER BY created DESC",
                (repository(endpoint), aas),
            ).fetchall()
        return [summary(json.loads(row[0])) for row in rows]

    def claim(self, identifier: str, review_hash: str) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM updates WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise UpdateError("Unknown update")
            draft = json.loads(row[0])
            if draft["status"] == "committed":
                if draft.get("reviewHash") != review_hash:
                    raise Conflict("This update was committed with a different review")
                return draft
            if draft["status"] != "reviewed" or draft.get("reviewHash") != review_hash:
                raise Conflict("Review this update again before committing")
            draft["status"] = "applying"
            db.execute(
                "UPDATE updates SET status=?,payload=? WHERE id=?",
                ("applying", json.dumps(draft, ensure_ascii=False), identifier),
            )
        return draft


def summary(draft: dict) -> dict:
    return {
        k: draft.get(k)
        for k in (
            "id",
            "endpoint",
            "aasId",
            "createdAt",
            "status",
            "selections",
            "changes",
            "conflicts",
            "reviewHash",
            "result",
            "restores",
            "validation",
            "automatic",
            "replacementGroups",
            "categoryAssessment",
            "compatibilityRepairs",
        )
    }


class CandidateClient:
    """Read adapter over a candidate. It deliberately has no mutation methods."""

    def __init__(self, state: dict, concepts: list | None = None):
        self.state = copy.deepcopy(state)
        self.concepts = concepts or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get_shell(self, identifier):
        if identifier not in (self.state["shell"]["id"], self.state["shell"].get("idShort")):
            raise UpdateError("Candidate belongs to another AAS")
        return copy.deepcopy(self.state["shell"])

    def list_shells(self, **kwargs):
        return [self.get_shell(self.state["shell"]["id"])]

    def list_submodel_refs(self, identifier):
        return self.get_shell(identifier).get("submodels", [])

    def get_submodel(self, identifier):
        return copy.deepcopy(self.state["submodels"][identifier])

    def list_submodels(self, **kwargs):
        return copy.deepcopy(list(self.state["submodels"].values()))

    def list_concept_descriptions(self, **kwargs):
        return copy.deepcopy(self.concepts)


def _semantic(node: dict):
    return node.get("semanticId") or None


def _declared_unit(node: dict) -> str:
    if node.get("unit"):
        return str(node["unit"]).strip()
    for specification in node.get("embeddedDataSpecifications", []):
        unit = (specification.get("dataSpecificationContent") or {}).get("unit")
        if unit:
            return str(unit).strip()
    for qualifier in node.get("qualifiers", []):
        if qualifier.get("type") in ("unit", "Unit", "unitSymbol", "UnitSymbol") and qualifier.get(
            "value"
        ):
            return str(qualifier["value"]).strip()
    return ""


def _payload(node: dict) -> dict:
    # Only the data carried by an SME; never transplant its old schema metadata.
    fields = {
        "Property": ("value",),
        "MultiLanguageProperty": ("value",),
        "Range": ("min", "max"),
        "File": ("value", "contentType"),
        "Blob": ("value", "contentType"),
        "ReferenceElement": ("value",),
        "RelationshipElement": ("first", "second"),
        "AnnotatedRelationshipElement": ("first", "second"),
        "Entity": ("globalAssetId", "specificAssetIds"),
        "Operation": ("inputVariables", "outputVariables", "inoutputVariables"),
    }.get(node.get("modelType"), ())
    return {key: copy.deepcopy(node[key]) for key in fields if key in node}


def _overlay(target: dict, existing: dict, conflicts: list, path: str = ""):
    """Conservative same-path/exact-semantic mapping, preserving local extensions."""
    target.update(_payload(existing))
    if target.get("modelType") == "AnnotatedRelationshipElement":
        target["annotations"] = copy.deepcopy(existing.get("annotations", []))
    if target.get("modelType") not in (
        "Submodel",
        "SubmodelElementCollection",
        "SubmodelElementList",
        "Entity",
    ):
        return
    key = (
        "submodelElements"
        if target.get("modelType") == "Submodel"
        else ("statements" if target.get("modelType") == "Entity" else "value")
    )
    children, old = target.get(key), existing.get(key)
    if not isinstance(children, list) or not isinstance(old, list):
        return
    if target.get("modelType") == "SubmodelElementList":
        # A list is instance data, not named template slots. Preserve its items.
        target[key] = copy.deepcopy(old)
        return
    used = set()
    for child in list(children):
        name = child.get("idShort")
        here = f"{path}.{name}".strip(".")
        exact = [i for i, node in enumerate(old) if i not in used and node.get("idShort") == name]
        semantic = [
            i
            for i, node in enumerate(old)
            if i not in used and _semantic(child) and _semantic(node) == _semantic(child)
        ]
        choices = exact or semantic
        if len(choices) != 1:
            if choices:
                conflicts.append(
                    {"path": here, "reason": "Several existing elements have this meaning"}
                )
            continue
        index = choices[0]
        node = old[index]
        incompatible = (
            node.get("modelType") != child.get("modelType")
            or node.get("valueType") != child.get("valueType")
            or (_semantic(child) and _semantic(node) and _semantic(child) != _semantic(node))
            or (
                _declared_unit(child)
                and _declared_unit(node)
                and _declared_unit(child) != _declared_unit(node)
            )
        )
        if incompatible:
            conflicts.append(
                {
                    "path": here,
                    "reason": "Type, unit or semantic change requires an explicit mapping",
                    "previous": node,
                }
            )
            continue
        used.add(index)
        _overlay(child, node, conflicts, here)
    for i, node in enumerate(old):
        if i not in used:
            name = node.get("idShort")
            if any(child.get("idShort") == name for child in children):
                continue  # A conflict remains explicit, never silently overwritten.
            children.append(copy.deepcopy(node))


def prepare(
    store: Store,
    client,
    endpoint: str,
    aas_id: str,
    selections: list[dict],
    source_client=None,
    source_endpoint: str | None = None,
    concepts=None,
) -> dict:
    endpoint = repository(endpoint)
    before = snapshot(client, aas_id)
    candidate = copy.deepcopy(before)
    chosen, conflicts = [], []
    used = set()
    for selection in selections:
        mode = selection.get("mode", "enrich")
        if mode not in ("add", "enrich", "migrate", "replace"):
            raise UpdateError("Choose add, enrich, migrate or replace")
        target_id = "" if mode == "add" else selection.get("targetId") or ""
        if mode != "add" and target_id not in before["submodels"]:
            raise UpdateError("Select an existing Submodel belonging to this AAS")
        if target_id and target_id in used:
            raise UpdateError("A Submodel can only have one update intent")
        used.add(target_id) if target_id else None
        if selection.get("releaseHash"):
            archived = next(
                (r for r in store.releases() if r["hash"] == selection["releaseHash"]), None
            )
            if (
                not archived
                or archived["source"] != repository(source_endpoint or endpoint)
                or archived["template"]["id"] != selection["templateId"]
            ):
                raise UpdateError("The pinned template release does not belong to this source")
            template = archived["template"]
        else:
            template = source_client.get_submodel(selection["templateId"])
        if template.get("kind") != "Template":
            raise UpdateError("The selected artifact is not an SMT")
        release = store.release(source_endpoint or endpoint, template, selection.get("family", ""))
        identifier = (
            target_id if mode in ("enrich", "migrate") else f"{aas_id}/sm/{uuid.uuid4().hex}"
        )
        model = instantiate(template, submodel_id=identifier, include_optional=True).submodel
        model.setdefault("administration", {})["templateId"] = template["id"]
        if mode in ("enrich", "migrate"):
            _overlay(model, before["submodels"][target_id], conflicts)
            # Enrichment does not assert migration to the selected template.
            if mode == "enrich":
                model = _enriched(before["submodels"][target_id], model)
        if mode == "replace":
            candidate["submodels"].pop(target_id)
        candidate["submodels"][identifier] = model
        chosen.append(
            {"mode": mode, "targetId": target_id, "candidateId": identifier, "release": release}
        )
    if selections:
        active = {
            item["candidateId"]: candidate["submodels"][item["candidateId"]] for item in chosen
        }
    else:
        active = copy.deepcopy(candidate["submodels"])
        chosen = [
            {"mode": "enrich", "targetId": key, "candidateId": key, "release": None}
            for key in active
        ]
    if not active:
        raise UpdateError("Select a template to add to this empty AAS")
    candidate["shell"]["submodels"] = [_reference(key) for key in candidate["submodels"]]
    draft = {
        "id": uuid.uuid4().hex,
        "endpoint": endpoint,
        "aasId": before["shell"]["id"],
        "createdAt": time.time(),
        "status": "draft",
        "before": before,
        "baselineHash": digest(before),
        "candidate": candidate,
        "activeIds": list(active),
        "selections": chosen,
        "conflicts": conflicts,
        "concepts": concepts or [],
        "changes": [],
        "actor": "web",
        "engine": "a4s-instance-updates/1",
    }
    store.put(draft)
    return draft


def _enriched(existing: dict, candidate: dict) -> dict:
    # Preserve the old schema/metadata and add only genuinely missing slots.
    result = copy.deepcopy(existing)
    if existing.get("modelType") not in (
        "Submodel",
        "SubmodelElementCollection",
        "SubmodelElementList",
        "Entity",
    ):
        return result
    key = (
        "submodelElements"
        if existing.get("modelType") == "Submodel"
        else ("statements" if existing.get("modelType") == "Entity" else "value")
    )
    if isinstance(candidate.get(key), list) and existing.get("modelType") != "SubmodelElementList":
        children = result.setdefault(key, [])
        if isinstance(children, list):
            for child in candidate[key]:
                old = next(
                    (node for node in children if node.get("idShort") == child.get("idShort")), None
                )
                if old is None:
                    children.append(copy.deepcopy(child))
                elif old.get("modelType") == child.get("modelType"):
                    replacement = _enriched(old, child)
                    children[children.index(old)] = replacement
    return result


def _reference(identifier: str) -> dict:
    return {"type": "ModelReference", "keys": [{"type": "Submodel", "value": identifier}]}


def candidate_client(draft: dict) -> CandidateClient:
    state = copy.deepcopy(draft["candidate"])
    state["submodels"] = {
        key: value for key, value in state["submodels"].items() if key in draft["activeIds"]
    }
    state["shell"]["submodels"] = [_reference(key) for key in state["submodels"]]
    return CandidateClient(state, draft.get("concepts"))


def _locate(model: dict, path: str):
    node = model
    for step in ElementPath.parse(path).steps:
        key = _child_key(node)
        values = node.get(key, [])
        node = (
            values[step]
            if isinstance(step, int)
            else next((n for n in values if n.get("idShort") == step), None)
        )
        if node is None:
            raise UpdateError(f"No candidate element at {path}")
    return node


def _child_key(node: dict) -> str:
    return {
        "Submodel": "submodelElements",
        "Entity": "statements",
        "AnnotatedRelationshipElement": "annotations",
    }.get(node.get("modelType"), "value")


def _sdk_validate(model: dict):
    try:
        from basyx.aas.adapter.json import StrictAASFromJsonDecoder
    except ImportError as exc:
        raise UpdateError(
            "Reviewed updates require the pinned aas extra: pip install '.[aas]'"
        ) from exc
    try:
        json.loads(json.dumps(model, ensure_ascii=False), cls=StrictAASFromJsonDecoder)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise UpdateError(f"Candidate does not satisfy AAS SME types: {exc}") from exc


def _repair_legacy_metadata(model: dict) -> list[dict]:
    """Repair two unambiguous legacy encodings in a reviewed copy only.

    AASd-122 requires GlobalReference for a single-key ExternalReference.
    Do not reinterpret ModelReferences, multi-key references or SME payloads.
    An empty optional category is equivalent to omitting that metadata field.
    Strict SDK validation remains the final check after these narrow repairs.
    """
    repairs = []
    def visit(value, path=''):
        if isinstance(value, list):
            for i, child in enumerate(value):
                visit(child, f'{path}/{i}')
        elif isinstance(value, dict):
            if value.get('modelType') and value.get('category') == '':
                value.pop('category')
                repairs.append({'path': path + '/category', 'before': '', 'after': None})
            for key, child in value.items():
                references = ([child] if key == 'semanticId' else child
                              if key == 'supplementalSemanticIds' and isinstance(child, list) else [])
                for reference in references:
                    if not isinstance(reference, dict):
                        continue
                    keys = reference.get('keys') or []
                    if (reference.get('type') == 'ExternalReference' and len(keys) == 1
                            and keys[0].get('type') == 'Submodel'):
                        keys[0]['type'] = 'GlobalReference'
                        repairs.append({'path': path + '/' + key, 'before': 'Submodel',
                                        'after': 'GlobalReference', 'value': keys[0].get('value')})
                visit(child, path + '/' + key)
    visit(model)
    return repairs


def _template_validation(store: Store, draft: dict, state: dict) -> dict:
    issues = []
    evaluated = False
    retained = {r["hash"]: r["template"] for r in store.releases()}
    for selection in draft["selections"]:
        release = selection.get("release")
        if not release:
            continue
        evaluated = True
        template = retained[release["hash"]]
        candidate = state["submodels"][selection["candidateId"]]
        for node in walk(template):
            original = _locate(template, node.path)
            if cardinality(original)[0] < 1:
                continue
            try:
                actual = _locate(candidate, node.path)
            except (UpdateError, IndexError):
                issues.append(
                    {
                        "submodel": candidate["id"],
                        "path": node.path,
                        "reason": "Required template slot absent after blank-value cleanup",
                    }
                )
                continue
            if _empty_property(actual):
                issues.append(
                    {
                        "submodel": candidate["id"],
                        "path": node.path,
                        "reason": "Required value is empty",
                    }
                )
    return {
        "types": "validated",
        "templateConformance": "incomplete"
        if issues
        else "checked"
        if evaluated
        else "not-evaluated",
        "issues": issues,
    }


def _clean(node: dict, path: str = "", removed=None, existing=None):
    removed = removed if removed is not None else []
    for key in ("submodelElements", "value", "statements", "annotations"):
        children = node.get(key)
        if not isinstance(children, list):
            continue
        for i in range(len(children) - 1, -1, -1):
            child = children[i]
            if not isinstance(child, dict) or not child.get("modelType"):
                continue
            segment = (
                f"[{i}]"
                if node.get("modelType") == "SubmodelElementList"
                else child.get("idShort", "")
            )
            here = path + segment if segment.startswith("[") else f"{path}.{segment}".strip(".")
            _clean(child, here, removed, existing)
            # Omit unfilled new data slots; preserve existing non-Property SMEs.
            empty_new_slot = (
                existing is not None
                and here not in existing
                and (
                    (
                        child.get("modelType") in ("File", "Blob", "ReferenceElement")
                        and child.get("value") in (None, "", [])
                    )
                    or (
                        child.get("modelType") == "Range"
                        and child.get("min") is None
                        and child.get("max") is None
                    )
                )
            )
            if (
                _empty_property(child)
                or empty_new_slot
                or (
                    child.get("modelType") == "SubmodelElementCollection"
                    and child.get("value", []) == []
                )
            ):
                children.pop(i)
                removed.append({"path": here, "modelType": child["modelType"]})
    return removed


def difference(before: dict, after: dict) -> list[dict]:
    changes = []
    for identifier in sorted(before["submodels"].keys() | after["submodels"].keys()):
        old, new = before["submodels"].get(identifier), after["submodels"].get(identifier)
        if old is None or new is None:
            changes.append(
                {
                    "submodel": identifier,
                    "path": "",
                    "action": "add-submodel" if old is None else "detach-submodel",
                    "before": old,
                    "after": new,
                }
            )
            continue
        old_nodes, new_nodes = ({n.path: n for n in walk(sm)} for sm in (old, new))
        for path in sorted(old_nodes.keys() | new_nodes.keys()):
            a, b = old_nodes.get(path), new_nodes.get(path)
            av = _locate(old, path) if a else None
            bv = _locate(new, path) if b else None
            if (
                av is None
                or bv is None
                or _payload(av) != _payload(bv)
                or av.get("modelType") != bv.get("modelType")
            ):
                changes.append(
                    {
                        "submodel": identifier,
                        "path": path,
                        "action": "create" if a is None else "remove" if b is None else "update",
                        "before": _payload(av) if av else None,
                        "after": _payload(bv) if bv else None,
                    }
                )
            if av is not None and bv is not None and _metadata(av) != _metadata(bv):
                changes.append(
                    {
                        "submodel": identifier,
                        "path": path,
                        "action": "schema-update",
                        "before": _metadata(av),
                        "after": _metadata(bv),
                    }
                )
        if _metadata(old) != _metadata(new):
            changes.append(
                {
                    "submodel": identifier,
                    "path": "",
                    "action": "schema-update",
                    "before": _metadata(old),
                    "after": _metadata(new),
                }
            )
    return changes


def _metadata(node: dict) -> dict:
    excluded = {"submodelElements", "statements", "annotations"} | set(_payload(node))
    if node.get("modelType") in ("SubmodelElementCollection", "SubmodelElementList"):
        excluded.add("value")
    return {key: value for key, value in node.items() if key not in excluded}


def review(
    store: Store, identifier: str, decisions: list[tuple[str, Any]], evidence: dict | None = None
) -> dict:
    from .match import value_for_write, element_for_create

    draft = store.get(identifier)
    original = copy.deepcopy(draft)
    if draft["status"] not in ("draft", "reviewed"):
        raise Conflict("This update is already being applied or completed")
    if draft["conflicts"]:
        raise Conflict(
            "Resolve the incompatible template mappings by selecting another template or replacement"
        )
    candidate = copy.deepcopy(draft["candidate"])
    applied = []
    seen = set()
    legacy = {row["source"]: row for row in draft.get("legacyInputs", [])}
    for sm_id, decision in decisions:
        if sm_id not in draft["activeIds"]:
            raise UpdateError("Match target is outside the selected update scope")
        if decision.action not in ("write", "create"):
            continue
        if decision.value is None:
            raise UpdateError("No value to write")
        model = candidate["submodels"][sm_id]
        node = _locate(model, decision.path or "")
        original_fact = legacy.get(decision.source)
        native = (
            original_fact["element"]
            if original_fact
            and decision.value == original_fact["value"]
            and decision.model_type == original_fact["element"].get("modelType")
            else None
        )
        if decision.action == "write":
            if decision.model_type != node.get("modelType"):
                raise UpdateError("The selected SME type no longer matches the candidate")
            token = (sm_id, decision.path)
            if token in seen:
                raise Conflict("Several reviewed values target the same element")
            seen.add(token)
            if native is None:
                value_for_write(decision)  # Validate type-specific requirements first.
            value = native if native is not None else element_for_create(decision)
            kind = node.get("modelType")
            if kind == "MultiLanguageProperty":
                languages = {entry["language"]: entry for entry in node.get("value", [])}
                languages.update({entry["language"]: entry for entry in value["value"]})
                node["value"] = list(languages.values())
            else:
                node.update(_payload(value))
        else:
            key = (
                "submodelElements"
                if node.get("modelType") == "Submodel"
                else ("statements" if node.get("modelType") == "Entity" else "value")
            )
            if node.get("modelType") not in (
                "Submodel",
                "SubmodelElementCollection",
                "SubmodelElementList",
                "Entity",
            ):
                raise UpdateError("New SME requires a Submodel or collection/list/entity")
            element = copy.deepcopy(native) if native is not None else element_for_create(decision)
            if native is not None:
                if decision.id_short:
                    element["idShort"] = decision.id_short
                elif node.get("modelType") == "SubmodelElementList":
                    element.pop("idShort", None)
            if node.get("modelType") == "SubmodelElementList":
                if element.get("idShort"):
                    raise UpdateError("List items must not have idShort")
                if element.get("modelType") != node.get("typeValueListElement"):
                    raise UpdateError("New item type does not match the SubmodelElementList")
                if (
                    node.get("valueTypeListElement")
                    and element.get("valueType") != node["valueTypeListElement"]
                ):
                    raise UpdateError("New item valueType does not match the SubmodelElementList")
            children = node.setdefault(key, [])
            if element.get("idShort") and any(
                n.get("idShort") == element["idShort"] for n in children
            ):
                raise Conflict("The new SME name already exists")
            children.append(element)
        applied.append(
            {
                "entity": decision.entity,
                "submodel": sm_id,
                "path": decision.path,
                "action": decision.action,
                "value": decision.value,
            }
        )
    existing_paths = {
        key: {node.path for node in walk(model)}
        for key, model in draft["before"]["submodels"].items()
    }
    removed = []
    compatibility_repairs = []
    for sm_id in draft["activeIds"]:
        removed += [
            {"submodel": sm_id, **row}
            for row in _clean(
                candidate["submodels"][sm_id], existing=existing_paths.get(sm_id, set())
            )
        ]
        compatibility_repairs.extend(
            {'submodel': sm_id, **repair}
            for repair in _repair_legacy_metadata(candidate['submodels'][sm_id])
        )
        _sdk_validate(candidate["submodels"][sm_id])
    omitted = [
        row for row in removed if row["path"] not in existing_paths.get(row["submodel"], set())
    ]
    removed = [row for row in removed if row["path"] in existing_paths.get(row["submodel"], set())]
    draft.update(
        {
            "status": "reviewed",
            "reviewed": candidate,
            "applied": applied,
            "cleanup": {
                "status": "completed",
                "removed": removed,
                "omitted": omitted,
                "failed": [],
            },
            "changes": difference(draft["before"], candidate),
            "compatibilityRepairs": compatibility_repairs,
            "evidence": evidence or {},
        }
    )
    draft["reviewedAt"] = time.time()
    draft["validation"] = _template_validation(store, draft, candidate)
    draft["reviewHash"] = digest(
        {
            "baseline": draft["baselineHash"],
            "after": candidate,
            "evidence": draft["evidence"],
            "applied": applied,
        }
    )
    store.put(draft, expected=original)
    return draft


def commit(store: Store, identifier: str, review_hash: str, client) -> dict:
    draft = store.get(identifier)
    with store.asset_lock(draft["endpoint"], draft["aasId"]):
        return _commit(store, identifier, review_hash, client)


def _commit(store: Store, identifier: str, review_hash: str, client) -> dict:
    draft = store.claim(identifier, review_hash)
    if draft["status"] == "committed":
        return draft
    failures, completed = [], []

    def perform(sm_id, operation, action):
        entry = {"submodel": sm_id, "operation": operation, "status": "pending"}
        completed.append(entry)
        draft["journal"] = completed
        store.put(draft)  # Intent is durable even if the response is lost.
        action()
        entry["status"] = "completed"
        store.put(draft)

    try:
        if digest(snapshot(client, draft["aasId"])) != draft["baselineHash"]:
            raise Conflict("The target AAS changed after preparation; prepare and review again")
        # Check shared instances: modifying one would affect another AAS too.
        changed = {
            key
            for key in draft["activeIds"]
            if key in draft["before"]["submodels"]
            and draft["before"]["submodels"][key] != draft["reviewed"]["submodels"].get(key)
        }
        for shell in client.list_shells(limit=10000):
            if shell["id"] != draft["aasId"] and changed.intersection(refs(shell)):
                raise Conflict(
                    "A selected Submodel is shared by another AAS; use replacement instead"
                )
        for sm_id in draft["activeIds"]:
            model = draft["reviewed"]["submodels"].get(sm_id)
            if model is None:
                continue
            if sm_id in draft["before"]["submodels"]:
                if model == draft["before"]["submodels"][sm_id]:
                    continue
                perform(sm_id, "write-submodel", lambda: client.replace_submodel(sm_id, model))
            else:
                try:
                    existing = client.get_submodel(sm_id)
                except AasHttpError as exc:
                    if exc.status != 404:
                        raise
                else:
                    if draft.get("restores") and existing == model:
                        continue  # Archived resource still exists: only rebind it.
                    raise Conflict("The new Submodel ID already exists or changed; prepare again")
                perform(sm_id, "write-submodel", lambda: client.create_submodel(model))
        old_refs, new_refs = (
            set(refs(draft["before"]["shell"])),
            set(refs(draft["reviewed"]["shell"])),
        )
        # Add before detach; never delete a resource that other shells may use.
        for sm_id in sorted(new_refs - old_refs):
            perform(
                sm_id, "attach", lambda: client.add_submodel_ref(draft["aasId"], _reference(sm_id))
            )
        for sm_id in sorted(old_refs - new_refs):
            perform(sm_id, "detach", lambda: client.remove_submodel_ref(draft["aasId"], sm_id))
        actual = snapshot(client, draft["aasId"])
        if digest(actual) != digest(draft["reviewed"]):
            # Repositories may normalize optional fields; compare separately in
            # integration tests rather than silently claiming identical output.
            raise Conflict(
                "Read-back differs from the reviewed state; inspect history before retrying"
            )
        draft["after"] = actual
        draft["status"] = "committed"
        draft["committedAt"] = time.time()
    except Exception as exc:
        draft["status"] = (
            "uncertain" if completed else "conflicted" if isinstance(exc, Conflict) else "failed"
        )
        failures.append({"error": str(exc)})
        try:
            draft["after"] = snapshot(client, draft["aasId"])
            if completed and (
                any(row["status"] == "completed" for row in completed)
                or digest(draft["after"]) != draft["baselineHash"]
            ):
                draft["status"] = "partial"
        except Exception:
            pass
    applied = draft.get("applied", []) if draft["status"] == "committed" else []
    if draft["status"] == "partial" and draft.get("after"):
        for row in draft.get("applied", []):
            sm_id = row["submodel"]
            if sm_id not in draft["after"]["submodels"]:
                continue
            # A whole selected SM equal to the review proves its values landed,
            # even when the operation response was lost.
            if digest(draft["after"]["submodels"][sm_id]) == digest(
                draft["reviewed"]["submodels"].get(sm_id)
            ):
                applied.append(row)
    draft["result"] = {
        "success": draft["status"] == "committed",
        "revisionId": identifier,
        "status": draft["status"],
        "applied": applied,
        "failed": failures,
        "counts": {
            "applied": len(applied),
            "failed": 0,
            "notAttempted": len(draft.get("applied", [])) - len(applied),
            "total": len(draft.get("applied", [])),
        },
        "cleanup": draft.get("cleanup")
        if draft["status"] == "committed"
        else {"status": "unverified", "removed": [], "failed": []},
        "journal": completed,
    }
    draft["result"]["validation"] = draft.get("validation")
    if completed and draft["status"] != "committed":
        draft["result"]["counts"]["unverified"] = draft["result"]["counts"]["notAttempted"]
        draft["result"]["counts"]["notAttempted"] = 0
    store.put(draft)
    return draft


def reconcile(store: Store, identifier: str, client) -> dict:
    """Observe an interrupted operation. Does not repeat any repository write."""
    previous = store.get(identifier)
    with store.asset_lock(previous["endpoint"], previous["aasId"]):
        draft = store.get(identifier)
        if draft["status"] not in ("applying", "partial", "uncertain"):
            raise Conflict("Only interrupted updates need reconciliation")
        actual = snapshot(client, draft["aasId"])
        draft["after"] = actual
        draft["status"] = "committed" if digest(actual) == digest(draft["reviewed"]) else "partial"
        applied = [
            row
            for row in draft.get("applied", [])
            if row["submodel"] in actual["submodels"]
            and digest(actual["submodels"][row["submodel"]])
            == digest(draft["reviewed"]["submodels"].get(row["submodel"]))
        ]
        draft["result"] = {
            "success": draft["status"] == "committed",
            "status": draft["status"],
            "revisionId": identifier,
            "applied": applied,
            "failed": [],
            "counts": {
                "applied": len(applied),
                "failed": 0,
                "notAttempted": 0,
                "unverified": len(draft.get("applied", [])) - len(applied),
                "total": len(draft.get("applied", [])),
            },
            "cleanup": draft.get("cleanup")
            if draft["status"] == "committed"
            else {"status": "unverified", "removed": [], "failed": []},
            "journal": draft.get("journal", []),
        }
        draft["reconciledAt"] = time.time()
        store.put(draft)
        return draft


def restore(store: Store, identifier: str, client) -> dict:
    previous = store.get(identifier)
    if previous["status"] not in ("committed", "partial", "uncertain"):
        raise UpdateError("Only a completed or partially applied update has a restorable baseline")
    current = snapshot(client, previous["aasId"])
    desired = copy.deepcopy(current)
    old = previous["before"]
    affected = {key for key in previous["activeIds"]} | {
        s["targetId"] for s in previous["selections"] if s["targetId"]
    }
    for key in affected:
        if key in old["submodels"]:
            desired["submodels"][key] = copy.deepcopy(old["submodels"][key])
        else:
            desired["submodels"].pop(key, None)
    desired["shell"]["submodels"] = [_reference(key) for key in desired["submodels"]]
    draft = {
        "id": uuid.uuid4().hex,
        "endpoint": previous["endpoint"],
        "aasId": previous["aasId"],
        "createdAt": time.time(),
        "status": "reviewed",
        "before": current,
        "baselineHash": digest(current),
        "candidate": desired,
        "reviewed": desired,
        "activeIds": list(desired["submodels"]),
        "selections": [],
        "conflicts": [],
        "restores": identifier,
        "changes": difference(current, desired),
        "applied": [],
        "evidence": {"restore": identifier},
        "cleanup": {"status": "not-requested", "removed": [], "failed": []},
    }
    draft["reviewHash"] = digest({"baseline": draft["baselineHash"], "after": desired})
    store.put(draft)
    return draft
