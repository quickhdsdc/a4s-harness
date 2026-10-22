"""Download published IDTA templates, audit strict readers, build a test catalog.

Raw upstream files are immutable evidence. Incompatible templates and conflicting
ConceptDescriptions are quarantined, never silently repaired or chosen. Import is
optional, create-only, and intended for an isolated repository.
"""

from __future__ import annotations

import argparse
import copy
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import logging
from pathlib import Path
import re
from urllib.parse import quote
import zipfile

import httpx

from a4s.aasctl import index, model, smt, updates
from a4s.aasctl.__main__ import main as cli
from a4s.aasctl.client import AasHttpError, BasyxClient, Endpoint

GITHUB = "https://api.github.com/repos/admin-shell-io/submodel-templates"
RAW = "https://raw.githubusercontent.com/admin-shell-io/submodel-templates"


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def discover(commit="main"):
    response = httpx.get(f"{GITHUB}/git/trees/{commit}", params={"recursive": "1"}, timeout=60)
    response.raise_for_status()
    tree = response.json()
    if tree.get("truncated"):
        raise RuntimeError("GitHub tree truncated; cannot determine the published catalog")
    families = defaultdict(list)
    for entry in tree["tree"]:
        path = entry["path"]
        match = re.fullmatch(r"(published/(?:[^/]+/)+?)(\d+(?:/\d+)*)/([^/]+)", path)
        if not match or not path.lower().endswith(".json"):
            continue
        name = match[3].lower()
        if any(word in name for word in ("example", "sample", "metamodelv3.1")):
            continue
        families[match[1]].append((tuple(map(int, match[2].split("/"))), path))
    return {
        "githubCommit": tree["sha"],
        "repository": GITHUB,
        "entries": [
            {
                "family": family.removeprefix("published/").rstrip("/"),
                "version": ".".join(map(str, max(version for version, _ in rows))),
                "jsonPaths": [path for version, path in rows if version == max(v for v, _ in rows)],
            }
            for family, rows in sorted(families.items())
        ],
    }


def check(operation):
    try:
        operation()
        return {"ok": True}
    except Exception as exc:  # Third-party decoders use several exception types.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def normalize_list_names(node, identifier, adjustments, path=""):
    """Make the SDK's positional-list normalization explicit in both exports."""
    if node.get("modelType") == "SubmodelElementList" and "orderRelevant" not in node:
        node["orderRelevant"] = True
        adjustments.append(
            {
                "submodel": identifier,
                "path": path + ".orderRelevant",
                "before": None,
                "after": True,
                "reason": "Make the AAS orderRelevant=true default explicit across readers",
            }
        )
    for key in ("submodelElements", "value", "statements", "annotations"):
        children = node.get(key)
        if not isinstance(children, list):
            continue
        in_list = node.get("modelType") == "SubmodelElementList" and key == "value"
        for position, child in enumerate(children):
            if not isinstance(child, dict) or "modelType" not in child:
                continue
            child_path = (
                f"{path}[{position}]"
                if in_list
                else ".".join(filter(None, (path, child.get("idShort", str(position)))))
            )
            if in_list and "idShort" in child:
                adjustments.append(
                    {
                        "submodel": identifier,
                        "path": child_path + ".idShort",
                        "before": child.pop("idShort"),
                        "after": None,
                        "reason": "AASd-120: list children are addressed by position, without idShort",
                    }
                )
            normalize_list_names(child, identifier, adjustments, child_path)


def download(manifest, directory):
    raw = directory / "raw"
    raw.mkdir(exist_ok=True)

    def one(job):
        family, path = job
        url = f"{RAW}/{manifest['githubCommit']}/" + quote(path, safe="/")
        file = raw / (hashlib.sha256(path.encode()).hexdigest()[:12] + ".json")
        if not file.exists():
            response = httpx.get(url, timeout=60, follow_redirects=True)
            response.raise_for_status()
            file.write_bytes(response.content)
        return {
            "family": family["family"],
            "releaseVersion": family["version"],
            "path": path,
            "url": url,
            "file": str(file),
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }

    jobs = [(family, path) for family in manifest["entries"] for path in family["jsonPaths"]]
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, jobs))


def build_catalog(downloads, directory, collection_id):
    from basyx.aas.adapter import aasx, json as sdk_json
    from basyx.aas import model as sdk_model

    def strict(value):
        return json.loads(json.dumps(value), cls=sdk_json.StrictAASFromJsonDecoder)

    accepted, concepts, audits, rejected, variants = {}, defaultdict(dict), [], [], []
    accepted_sources = {}
    for source in downloads:
        environment = json.loads(Path(source["file"]).read_bytes())
        models = environment.get("submodels", [environment])
        admitted = False
        for template in models:
            if template.get("kind") != "Template":
                continue  # Published packages sometimes contain example instances.
            row = {
                **source,
                "id": template["id"],
                "name": template.get("idShort"),
                "smlCount": sum(
                    n.model_type == "SubmodelElementList" for n in index.walk(template)
                ),
                "rawSdk": check(lambda: strict(template)),
                "instanceSdk": check(
                    lambda: strict(
                        smt.instantiate(
                            template, submodel_id="urn:a4s:idta:validation", include_optional=True
                        ).submodel
                    )
                ),
            }
            audits.append(row)
            if row["rawSdk"]["ok"] and row["instanceSdk"]["ok"]:
                identifier = template["id"]
                if identifier in accepted and updates.digest(
                    accepted[identifier]
                ) != updates.digest(template):
                    previous = accepted_sources[identifier]
                    old_extended = "withoperations" in previous["path"].lower()
                    new_extended = "withoperations" in source["path"].lower()
                    if old_extended == new_extended:
                        raise RuntimeError(
                            f"Conflicting template ID {identifier}; cannot choose silently"
                        )
                    # IDTA TimeSeries publishes standard and operation variants
                    # under one ID. A repository can hold only one. Keep the
                    # standard variant, explicitly retain the other as evidence.
                    omitted = previous if old_extended else row
                    omitted["catalogIncluded"] = False
                    variants.append(
                        {
                            **omitted,
                            "reason": "Operations variant shares its ID with the standard variant; retained separately",
                        }
                    )
                    if new_extended:
                        continue
                accepted[identifier] = copy.deepcopy(template)
                accepted_sources[identifier] = row
                row["catalogIncluded"] = True
                admitted = True
            else:
                rejected.append({**row, "template": template})
        if admitted:
            for concept in environment.get("conceptDescriptions", []):
                concepts[concept["id"]][updates.digest(concept)] = concept
    cds, conflicts = [], []
    for identifier, variants in concepts.items():
        values = list(variants.values())
        if identifier in accepted or identifier == collection_id:
            conflicts.append(
                {
                    "id": identifier,
                    "reason": "ConceptDescription reuses an Identifiable ID held by a Submodel/AAS",
                    "variants": values,
                }
            )
        elif len(values) != 1:
            conflicts.append(
                {
                    "id": identifier,
                    "reason": "Upstream sources disagree under one ID",
                    "variants": values,
                }
            )
        elif not (result := check(lambda: strict(values[0])))["ok"]:
            conflicts.append({"id": identifier, "reason": result["error"], "variants": values})
        else:
            cds.append(values[0])
    file_store = aasx.DictSupplementaryFileContainer()
    attachments, adjustments = [], []
    for identifier, template in accepted.items():
        normalize_list_names(template, identifier, adjustments)
        local_files = []
        for node in index.walk(template):
            if node.model_type != "File" or not node.value:
                continue
            if node.value.startswith("//") or ":" in node.value.split("/")[0]:
                continue
            local_files.append(node)
        if not local_files:
            continue
        source = accepted_sources[identifier]
        package_path = source["path"].removesuffix(".json") + ".aasx"
        package_url = source["url"].removesuffix(".json") + ".aasx"
        package = (
            directory / "raw" / (hashlib.sha256(package_path.encode()).hexdigest()[:12] + ".aasx")
        )
        if not package.exists():
            response = httpx.get(package_url, timeout=60, follow_redirects=True)
            response.raise_for_status()
            package.write_bytes(response.content)
        with zipfile.ZipFile(package) as archive:
            names = {name.lstrip("/").casefold(): name for name in archive.namelist()}
            for node in local_files:
                element = updates._locate(template, node.path)
                name = names.get(node.value.lstrip("/").casefold())
                if name is None:
                    # These are example file paths with no corresponding upstream
                    # package part. Keep the slot, remove only the dangling example
                    # URI in this generated copy, and retain the raw source bytes.
                    element.pop("value", None)
                    adjustments.append(
                        {
                            "submodel": identifier,
                            "path": node.path,
                            "before": node.value,
                            "after": None,
                            "reason": "Example File URI absent from the official AASX package",
                            "source": package_url,
                        }
                    )
                    continue
                data = archive.read(name)
                uri = file_store.add_file(
                    node.value,
                    io.BytesIO(data),
                    element.get("contentType") or "application/octet-stream",
                )
                if uri != node.value:
                    element["value"] = uri
                    adjustments.append(
                        {
                            "submodel": identifier,
                            "path": node.path,
                            "before": node.value,
                            "after": uri,
                            "reason": "Packaged file URI normalized or deconflicted",
                        }
                    )
                attachments.append(
                    {"uri": uri, "sha256": hashlib.sha256(data).hexdigest(), "source": package_url}
                )
    save(directory / "catalog-adjustments.json", adjustments)
    save(directory / "supplementary-files.json", attachments)
    shell = model.make_shell(collection_id, "CollectionofSMTs", asset_kind="Type")
    shell["submodels"] = [updates._reference(key) for key in accepted]
    environment = {
        "assetAdministrationShells": [shell],
        "submodels": list(accepted.values()),
        "conceptDescriptions": cds,
    }
    save(directory / "quarantined-templates.json", rejected)
    save(directory / "alternate-template-variants.json", variants)
    save(directory / "conflicting-concept-descriptions.json", conflicts)
    json_file = directory / "CollectionofSMTs_IDTA.json"
    save(json_file, environment)
    store = sdk_json.read_aas_json_file(json_file, failsafe=False)
    expected = 1 + len(accepted) + len(cds)
    if len(store) != expected:
        raise RuntimeError("SDK discarded objects from the complete catalog")
    # Include available upstream attachments. Dangling example URIs were recorded
    # above and removed only from the generated copy, never the raw downloads.
    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    logger = logging.getLogger("basyx.aas.adapter.aasx")
    logger.addHandler(handler)
    try:
        with aasx.AASXWriter(directory / "CollectionofSMTs_IDTA.aasx", failsafe=False) as writer:
            writer.write_all_aas_objects("/aasx/catalog.json", store, file_store, write_json=True)
    finally:
        logger.removeHandler(handler)
    restored = sdk_model.DictIdentifiableStore()
    with aasx.AASXReader(directory / "CollectionofSMTs_IDTA.aasx", failsafe=False) as reader:
        reader.read_into(restored, aasx.DictSupplementaryFileContainer())
    if len(restored) != expected:
        raise RuntimeError("AASX read-back lost objects")
    raw_counts = sum(len(index.walk(sm)) for sm in accepted.values())
    reencoded = json.loads(
        json.dumps(
            [obj for obj in restored if isinstance(obj, sdk_model.Submodel)],
            cls=sdk_json.AASToJsonEncoder,
        )
    )
    if sum(len(index.walk(sm)) for sm in reencoded) != raw_counts:
        raise RuntimeError("AASX read-back changed the number of addressable SMEs")
    report = {
        "sourceFiles": len(downloads),
        "templateArtifacts": len(audits),
        "acceptedTemplates": len(accepted),
        "quarantinedTemplates": len(rejected),
        "sdkReadableTemplateArtifacts": sum(row["rawSdk"]["ok"] for row in audits),
        "omittedAlternateVariants": len(variants),
        "smlTemplates": sum(row["smlCount"] > 0 for row in audits if row.get("catalogIncluded")),
        "smlCount": sum(row["smlCount"] for row in audits if row.get("catalogIncluded")),
        "addressableElements": raw_counts,
        "conceptDescriptions": len(cds),
        "omittedConflictingConceptIds": len(conflicts),
        "collectionId": collection_id,
        "sdkJsonObjects": len(store),
        "sdkAasxObjects": len(restored),
        "supplementaryFiles": len(attachments),
        "adjustments": len(adjustments),
        "packageWarnings": capture.getvalue().splitlines(),
        "templates": audits,
    }
    save(directory / "audit-report.json", report)
    return environment, report


def cli_result(arguments):
    output, errors = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(output), redirect_stderr(errors):
            status = cli(arguments)
        return {
            "ok": status == 0,
            "data": json.loads(output.getvalue()),
            "stderr": errors.getvalue(),
        }
    except (Exception, SystemExit) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "stderr": errors.getvalue()}


def import_and_test(environment, endpoint, directory):
    from basyx.aas.adapter.json import StrictAASFromJsonDecoder, AASToJsonEncoder

    def semantic_fingerprint(value):
        native = json.loads(json.dumps(value), cls=StrictAASFromJsonDecoder)
        return updates.digest(json.loads(json.dumps(native, cls=AASToJsonEncoder)))

    with BasyxClient(Endpoint.from_env(endpoint)) as client:
        # Preflight all identities before the first create; never overwrite.
        objects = [("concept-descriptions", cd) for cd in environment["conceptDescriptions"]]
        objects += [("submodels", sm) for sm in environment["submodels"]]
        objects += [("shells", shell) for shell in environment["assetAdministrationShells"]]
        missing = []
        from a4s.aasctl.paths import encode_id

        for route, value in objects:
            try:
                existing = client.get(f"/{route}/{encode_id(value['id'])}")
            except AasHttpError as exc:
                if exc.status != 404:
                    raise
                missing.append((route, value))
            else:
                if updates.digest(existing) != updates.digest(value) and semantic_fingerprint(
                    existing
                ) != semantic_fingerprint(value):
                    raise RuntimeError(
                        f"Target has different {value['id']}; no overwrite performed"
                    )
        for number, (route, value) in enumerate(missing, 1):
            client.post("/" + route, value)
            if number % 500 == 0:
                print(f"Imported {number}/{len(missing)} objects", flush=True)
    return verify_cli(environment, endpoint, directory)


def verify_cli(environment, endpoint, directory):
    catalog = environment["assetAdministrationShells"][0]["id"]
    result = {
        "endpoint": endpoint,
        "catalog": cli_result(
            [
                "--endpoint",
                endpoint,
                "--json",
                "smt",
                "list",
                "--from-endpoint",
                endpoint,
                "--of-shell",
                catalog,
            ]
        ),
        "templates": [],
    }
    for sm in environment["submodels"]:
        identifier = sm["id"]
        row = {
            "id": identifier,
            "name": sm.get("idShort"),
            "show": cli_result(
                [
                    "--endpoint",
                    endpoint,
                    "--json",
                    "smt",
                    "show",
                    identifier,
                    "--from-endpoint",
                    endpoint,
                ]
            ),
            "tree": cli_result(["--endpoint", endpoint, "--json", "sm", "tree", identifier]),
            "validate": cli_result(["--endpoint", endpoint, "--json", "validate", identifier]),
            "instantiate": cli_result(
                [
                    "--endpoint",
                    endpoint,
                    "--json",
                    "smt",
                    "instantiate",
                    identifier,
                    "--from-endpoint",
                    endpoint,
                    "--as",
                    "urn:a4s:idta:cli-dry-run",
                    "--include-optional",
                    "--dry-run",
                ]
            ),
        }
        result["templates"].append(row)
        if len(result["templates"]) % 10 == 0:
            print(
                f"CLI checked {len(result['templates'])}/{len(environment['submodels'])} templates",
                flush=True,
            )
    save(directory / "cli-report.json", result)
    summary = {
        key: sum(row[key]["ok"] for row in result["templates"])
        for key in ("show", "tree", "validate", "instantiate")
    }
    summary["validateNoFindings"] = sum(
        row["validate"].get("data", {}).get("ok", False) for row in result["templates"]
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--commit", default="main")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collection-id", default="urn:a4s:catalog:idta:20261021")
    parser.add_argument("--import-endpoint")
    parser.add_argument(
        "--verify-endpoint", help="Only rerun CLI reads/dry-runs against an existing catalog"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.verify_endpoint:
        if args.import_endpoint:
            parser.error("Choose import or verify-only, not both")
        environment = json.loads(
            (args.output / "CollectionofSMTs_IDTA.json").read_text(encoding="utf-8")
        )
        print(json.dumps({"cli": verify_cli(environment, args.verify_endpoint, args.output)}))
        return
    sdk_log = logging.FileHandler(args.output / "sdk-reader.log", encoding="utf-8", mode="w")
    logging.getLogger("basyx").addHandler(sdk_log)
    logging.getLogger("basyx").propagate = False
    manifest = (
        json.loads(args.manifest.read_text(encoding="utf-8"))
        if args.manifest
        else discover(args.commit)
    )
    previous_manifest = args.output / "source-manifest.json"
    if previous_manifest.exists():
        previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
        if previous["githubCommit"] != manifest["githubCommit"]:
            raise RuntimeError("Use a new output directory for a different pinned release snapshot")
    save(args.output / "source-manifest.json", manifest)
    license_url = f"{RAW}/{manifest['githubCommit']}/LICENSE.txt"
    response = httpx.get(license_url, timeout=30)
    response.raise_for_status()
    (args.output / "UPSTREAM-LICENSE.txt").write_bytes(response.content)
    (args.output / "ATTRIBUTION.md").write_text(
        f"IDTA / admin-shell-io Submodel Templates, CC BY 4.0.\nSource: {RAW}/{manifest['githubCommit']}\n"
        "Raw source files are unchanged. Incompatible models and conflicting definitions are quarantined.\n"
        "The generated copy clears dangling File examples, removes forbidden list-child idShorts, and makes the standard orderRelevant=true default explicit; see catalog-adjustments.json.\n"
        "Available referenced attachments are included; see supplementary-files.json.\n",
        encoding="utf-8",
    )
    downloads = download(manifest, args.output)
    save(args.output / "download-manifest.json", downloads)
    environment, report = build_catalog(downloads, args.output, args.collection_id)
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in ("templates", "packageWarnings")
            }
        ),
        flush=True,
    )
    if args.import_endpoint:
        print(json.dumps({"cli": import_and_test(environment, args.import_endpoint, args.output)}))


if __name__ == "__main__":
    main()
