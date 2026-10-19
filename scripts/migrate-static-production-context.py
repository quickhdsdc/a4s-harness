"""Replace only the local Festo ProductionContext template and current instance.

The local JSON blueprint is the source of truth. This one-time migration backs
up both server submodels before replacing them. No MES or OPC values are written.
Run without --apply to inspect the target first.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from a4s.aasctl.client import BasyxClient, Endpoint
from a4s.kernel.config import load_env
from a4s.mesctl.client import Config, MesClient
from a4s.machines.festo_cp_lab.mes_binding import resolve_line
from a4s.server.festo_assets import current_instance, instance_submodels
from a4s.server.write_routes import _copy_submodel

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_FILE = ROOT / "BaSyxMinimal/aas/festo-cp-lab.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    load_env(str(ROOT / ".env"))
    endpoint = Endpoint.from_env()
    config = Config.from_env()
    # This migration is for this checkout's isolated local services only.
    if endpoint.base_url != "http://localhost:8081" or config.endpoint != "http://localhost:8092":
        raise RuntimeError("Migration only supports the local AAS and OpenMES endpoints")
    document = json.loads(BLUEPRINT_FILE.read_text(encoding="utf-8"))
    template = next(model for model in document["submodels"] if model.get("idShort") == "ProductionContext")
    fields = {element["idShort"]: element.get("value") for element in template["submodelElements"]}
    with MesClient(config) as mes:
        line = resolve_line(fields, mes)
    with BasyxClient(endpoint) as aas:
        shell = current_instance(aas)
        models = instance_submodels(aas, shell)
        existing = models.get("ProductionContext")
        if not existing:
            raise RuntimeError("Current Festo instance has no ProductionContext")
        original_template = aas.get_submodel(template["id"])
        instance = _copy_submodel(template, shell["id"])
        if existing["id"] != instance["id"]:
            raise RuntimeError("Instance ProductionContext ID does not match selected asset")
        print(json.dumps({"apply": args.apply, "asset": shell["idShort"],
                          "mes_line": line["code"],
                          "submodel_ids": [template["id"], instance["id"]]}))
        if not args.apply:
            return
        directory = ROOT / "work/temp/festo-context-migration" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "before.json").write_text(json.dumps({"template": original_template,
            "instance": existing}, indent=2, ensure_ascii=False), encoding="utf-8")
        aas.replace_submodel(template["id"], template)
        aas.replace_submodel(instance["id"], instance)
        for model in (template, instance):
            actual = aas.get_submodel(model["id"])
            actual_fields = {e["idShort"]: e.get("value") for e in actual["submodelElements"]}
            expected_fields = {e["idShort"]: e.get("value") for e in model["submodelElements"]}
            if actual_fields != expected_fields:
                raise RuntimeError(f"Read-back differs for {model['id']}; backup: {directory}")
        print(json.dumps({"updated": True, "backup": str(directory), "mes_writes": False,
                          "opc_writes": False}))


if __name__ == "__main__":
    main()
