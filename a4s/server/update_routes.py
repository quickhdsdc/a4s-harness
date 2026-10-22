"""Browser adapter for reviewed instance updates; template/target stay separate."""

import hashlib
import os

from fastapi import APIRouter, Body, HTTPException

from ..aasctl import automatic_updates, updates
from ..aasctl.client import AasHttpError, Endpoint
from . import aas_routes, wizard_routes, workspace

router = APIRouter(prefix="/api/instance-updates")


def _store():
    return updates.Store()


def _draft(identifier, endpoint=None, aas=None):
    try:
        draft = _store().get(identifier)
        if endpoint and updates.repository(endpoint) != draft["endpoint"]:
            raise updates.Conflict("This update belongs to another repository")
        if aas and aas not in (draft["aasId"], draft["before"]["shell"].get("idShort")):
            raise updates.Conflict("This update belongs to another AAS")
        return draft
    except updates.UpdateError as exc:
        raise HTTPException(409 if isinstance(exc, updates.Conflict) else 422, str(exc)) from exc


def _call(operation):
    try:
        return operation()
    except updates.UpdateError as exc:
        raise HTTPException(409 if isinstance(exc, updates.Conflict) else 422, str(exc)) from exc
    except AasHttpError as exc:
        raise aas_routes._fail(exc, "Cannot read AAS update resource") from exc
    except (KeyError, TypeError) as exc:
        raise HTTPException(422, f"Invalid update input: {exc}") from exc


@router.get("/discover")
def discover(aas: str, endpoint: str):
    def run():
        with aas_routes._client(endpoint) as client:
            shell = aas_routes._resolve_shell(client, aas)
            state = updates.snapshot(client, shell["id"])
        templates = aas_routes.templates()
        source = Endpoint.from_env(os.getenv("A4S_SMT_ENDPOINT") or None).base_url
        entries = []
        with aas_routes._client(source) as client:
            for row in templates:
                template = client.get_submodel(row["id"])
                release = _store().release(source, template)
                candidates = []
                for identifier, model in state["submodels"].items():
                    origin = (model.get("administration") or {}).get("templateId")
                    semantic = template.get("semanticId")
                    reason = (
                        "Recorded template origin"
                        if origin == template["id"]
                        else "Exact semantic ID"
                        if semantic and model.get("semanticId") == semantic
                        else "Same name; select explicitly"
                        if model.get("idShort") == template.get("idShort")
                        else ""
                    )
                    if reason:
                        candidates.append(
                            {
                                "id": identifier,
                                "name": model.get("idShort"),
                                "version": (model.get("administration") or {}).get("version", ""),
                                "revision": (model.get("administration") or {}).get("revision", ""),
                                "reason": reason,
                                "exact": reason != "Same name; select explicitly",
                            }
                        )
                entries.append({**release, "candidates": candidates})
        current = {entry["hash"] for entry in entries}
        allowed = {row["id"] for row in templates}
        for archived in _store().releases():
            if (
                archived["source"] != source.rstrip("/")
                or archived["hash"] in current
                or archived["template"]["id"] not in allowed
            ):
                continue
            template = archived["template"]
            release = _store().release(source, template)
            matches = [
                {
                    "id": key,
                    "name": model.get("idShort"),
                    "reason": "Archived release; select the target explicitly",
                    "exact": False,
                }
                for key, model in state["submodels"].items()
                if model.get("idShort") == template.get("idShort")
            ]
            entries.append({**release, "archived": True, "candidates": matches})
        return {
            "aasId": shell["id"],
            "endpoint": updates.repository(endpoint),
            "source": source,
            "templates": entries,
            "submodels": [
                {
                    "id": key,
                    "name": value.get("idShort"),
                    "version": (value.get("administration") or {}).get("version", ""),
                }
                for key, value in state["submodels"].items()
            ],
            "history": _store().history(endpoint, shell["id"]),
        }

    return _call(run)


@router.get("/catalog")
def catalog():
    source = Endpoint.from_env(os.getenv("A4S_SMT_ENDPOINT") or None).base_url.rstrip("/")
    allowed = {row["id"] for row in aas_routes.templates()}
    return [
        {
            "hash": row["hash"],
            "source": row["source"],
            "templateId": row["template"]["id"],
            "name": row["template"].get("idShort"),
            "administration": row["template"].get("administration", {}),
            "semanticId": row["template"].get("semanticId"),
        }
        for row in _store().releases()
        if row["source"] == source and row["template"]["id"] in allowed
    ]


@router.post("/prepare")
def prepare(body: dict = Body(...)):
    def run():
        endpoint = Endpoint.from_env(body.get("endpoint")).base_url
        source = Endpoint.from_env(os.getenv("A4S_SMT_ENDPOINT") or None).base_url
        selections = body.get("selections", [])
        automatic = "templateIds" in body
        template_ids = body.get("templateIds", [])
        if not isinstance(template_ids, list) or any(
            not isinstance(key, str) for key in template_ids
        ):
            raise updates.UpdateError("Select standardized submodel templates")
        # The picker reads the configured Collection AAS. Do not revalidate
        # membership here: editing that catalog does not invalidate an existing
        # template resource. Preparation still checks the template's actual kind
        # and keeps template reads separate from the target repository.
        with aas_routes._client(endpoint) as client, aas_routes._client(source) as templates:
            shell = aas_routes._resolve_shell(client, body["aas"])
            concepts = {c["id"]: c for c in templates.list_concept_descriptions()}
            concepts.update({c["id"]: c for c in client.list_concept_descriptions()})
            draft = (automatic_updates.prepare if automatic else updates.prepare)(
                _store(),
                client,
                endpoint,
                shell["id"],
                template_ids if automatic else selections,
                templates,
                source,
                list(concepts.values()),
            )
        return updates.summary(draft)

    return _call(run)


@router.get("/existing")
def existing(aas: str, endpoint: str):
    """Read-only device inventory: no need to load the template catalog here."""

    def run():
        with aas_routes._client(endpoint) as client:
            shell = aas_routes._resolve_shell(client, aas)
            state = updates.snapshot(client, shell["id"])
        return {
            "aasId": shell["id"],
            "submodels": [
                {
                    "id": key,
                    "name": value.get("idShort", key),
                    "version": (value.get("administration") or {}).get("version", ""),
                }
                for key, value in state["submodels"].items()
            ],
            "history": _store().history(endpoint, shell["id"]),
        }

    return _call(run)


@router.get("/history")
def history(aas: str, endpoint: str):
    with aas_routes._client(endpoint) as client:
        shell = aas_routes._resolve_shell(client, aas)
    return _store().history(endpoint, shell["id"])


@router.get("/{identifier}")
def get_update(identifier: str):
    return updates.summary(_draft(identifier))


@router.get("/{identifier}/snapshot")
def get_snapshot(identifier: str):
    draft = _draft(identifier)
    return {
        key: draft.get(key)
        for key in (
            "id",
            "endpoint",
            "aasId",
            "status",
            "before",
            "after",
            "selections",
            "evidence",
            "changes",
            "journal",
        )
    }


@router.get("/{identifier}/properties")
def properties(identifier: str):
    draft = _draft(identifier)
    client = updates.candidate_client(draft)
    rows = [row for sm in client.list_submodels() for row in aas_routes._properties_of(sm)]
    grouped = {}
    for row in rows:
        group = row["submodelIdShort"] + (
            " / " + row["parentCollection"] if row["parentCollection"] else " / Root"
        )
        grouped.setdefault(group, []).append(row)
    return {"success": True, "properties": rows, "count": len(rows), "grouped": grouped}


@router.post("/{identifier}/review")
def review(identifier: str, body: dict = Body(...)):
    def run():
        draft = _draft(identifier, body.get("endpoint"), body.get("aas"))
        lookup = wizard_routes._SubmodelLookup(updates.candidate_client(draft), draft["aasId"])
        decisions, rejected = [], []
        legacy = {fact["source"]: fact for fact in draft.get("legacyInputs", [])}
        for row in body.get("results", []):
            if row.get("selected") is False:
                continue
            try:
                sm_id, decision = wizard_routes._decision_of(row, lookup)
                fact = legacy.get(row.get("source"))
                if (
                    fact
                    and decision.action == "create"
                    and decision.value == fact["value"]
                    and row.get("aasType") == fact["model_type"]
                    and not wizard_routes._repicked(row)
                    and (
                        decision.container_type != "SubmodelElementList"
                        or decision.model_type == fact["model_type"]
                    )
                ):
                    # Root-level manual facts default to Property in the older
                    # adapter. Native imported SMEs already have a declared type.
                    decision.model_type = fact["model_type"]
                    decision.value_type = fact.get("value_type") or decision.value_type
                decisions.append((sm_id, decision))
            except wizard_routes._Unresolved as exc:
                rejected.append(str(exc))
        if rejected:
            raise updates.UpdateError("; ".join(rejected))
        evidence = {"filename": body.get("filename"), "rows": body.get("results", [])}
        filename = body.get("filename")
        if filename:
            upload = workspace.under(workspace.uploads(), filename)
            if upload.is_file():
                evidence["inputHash"] = hashlib.sha256(upload.read_bytes()).hexdigest()
                evidence["inputArtifact"] = _store().retain(upload)
            extracted = workspace.extraction_file(filename, edited=True)
            if not extracted.exists():
                extracted = workspace.extraction_file(filename)
            if extracted.exists():
                evidence["extractionHash"] = hashlib.sha256(extracted.read_bytes()).hexdigest()
                evidence["extractionArtifact"] = _store().retain(extracted)
        return updates.summary(updates.review(_store(), identifier, decisions, evidence))

    return _call(run)


@router.post("/{identifier}/commit")
def commit(identifier: str, body: dict = Body(...)):
    def run():
        draft = _draft(identifier, body.get("endpoint"), body.get("aas"))
        # Includes the known limitation that other clients can write outside A4S.
        if not wizard_routes.WIZARD_LOCK.acquire(blocking=False):
            raise updates.Conflict("Matching or another update is running")
        try:
            with aas_routes._client(draft["endpoint"]) as client:
                result = updates.commit(_store(), identifier, body.get("reviewHash", ""), client)
            warning = wizard_routes._recorded(
                "aas.instance-update",
                draft["aasId"],
                {"update": identifier, "endpoint": draft["endpoint"], "status": result["status"]},
            )
            if warning:
                result["result"]["unrecorded"] = warning
            return result["result"]
        finally:
            wizard_routes.WIZARD_LOCK.release()

    return _call(run)


@router.post("/{identifier}/restore")
def restore(identifier: str):
    def run():
        draft = _draft(identifier)
        with aas_routes._client(draft["endpoint"]) as client:
            return updates.summary(updates.restore(_store(), identifier, client))

    return _call(run)


@router.post("/{identifier}/reconcile")
def reconcile(identifier: str):
    def run():
        draft = _draft(identifier)
        with aas_routes._client(draft["endpoint"]) as client:
            return updates.summary(updates.reconcile(_store(), identifier, client))

    return _call(run)
