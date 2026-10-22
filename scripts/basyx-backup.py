"""Read-only API export plus a Mongo archive before optional BaSyx migration.

No restore into an existing database. Imported API resources use create-only
semantics; differences are reported rather than overwritten.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import subprocess

from a4s.aasctl.client import AasHttpError, BasyxClient, Endpoint
from a4s.kernel.config import load_env


def resources(client, route):
    cursor, values = None, []
    while True:
        params = {"limit": 1000}
        if cursor:
            params["cursor"] = cursor
        response = client.get(route, params=params)
        if isinstance(response, list):
            return response
        values.extend(response.get("result", []))
        cursor = response.get("paging_metadata", {}).get("cursor")
        if not cursor:
            return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://localhost:8081")
    parser.add_argument(
        "--mongo-container", help="Optional existing Mongo container to archive read-only"
    )
    parser.add_argument("--import-file", type=Path)
    args = parser.parse_args()
    load_env()
    with BasyxClient(Endpoint.from_env(args.endpoint)) as client:
        if args.import_file:
            payload = json.loads(args.import_file.read_text(encoding="utf-8"))
            counts, failures = {}, []
            for route in ("concept-descriptions", "submodels", "shells"):
                counts[route] = 0
                for value in payload[route]:
                    try:
                        client.post("/" + route, value)
                        counts[route] += 1
                    except AasHttpError as exc:
                        failures.append(
                            {
                                "kind": route,
                                "id": value.get("id"),
                                "status": exc.status,
                                "error": exc.body[:700],
                            }
                        )
            report = args.import_file.with_name("import-report.json")
            report.write_text(
                json.dumps(
                    {"target": args.endpoint, "created": counts, "failed": failures}, indent=2
                ),
                encoding="utf-8",
            )
            print(json.dumps({"created": counts, "failed": len(failures), "report": str(report)}))
            return 1 if failures else 0
        payload = {
            route: resources(client, "/" + route)
            for route in ("shells", "submodels", "concept-descriptions")
        }
    home = Path(os.environ.get("A4S_HOME", Path.home() / ".a4s")).expanduser()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = home / "backups" / ("basyx-" + stamp)
    directory.mkdir(parents=True, exist_ok=False)
    export = directory / "repository.json"
    export.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.mongo_container:
        command = [
            "docker",
            "exec",
            args.mongo_container,
            "sh",
            "-c",
            'mongodump --username "$MONGO_INITDB_ROOT_USERNAME" --password "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin --archive --gzip',
        ]
        with (directory / "mongo.archive.gz").open("wb") as sink:
            result = subprocess.run(command, stdout=sink, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError("Mongo backup failed; original database unchanged")
    print(
        json.dumps(
            {
                "backup": str(directory),
                "counts": {key: len(value) for key, value in payload.items()},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
