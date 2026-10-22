# Local BaSyx environment

This is the maintained local stack. The former `a4s-basyx-next` upgrade copy
and `a4s-smt-lab` template trial are retired; their Compose files are removed.
Do not start those projects alongside this one.

## Required versions

This is the tested local AAS Creation compatibility baseline, checked against
the actual running containers and project virtual environment on 2026-10-22.
Python must be `>=3.11,<3.15`; the current local interpreter is `3.14.0`.
**`basyx-python-sdk==2.2.0` is required for typed AAS validation and reviewed
updates**, and is pinned in both the `aas` and `ui` extras of `pyproject.toml`.
The SDK package version and the AAS specification version are separate numbers;
see the [upstream compatibility guidance](https://github.com/eclipse-basyx/basyx-python-sdk#specification-compliance).

| Component / image repository | Version tag | Required image digest (`sha256:`) |
| --- | --- | --- |
| `eclipsebasyx/aas-environment` | `2.0.0-milestone-15` | `313da867059233e3c07e17a8ac21153a1f8fa0d02eada4e6b1b9f9e86afbd321` |
| `eclipsebasyx/aas-registry-log-mongodb` | `2.0.0-SNAPSHOT` | `7b60e4e23048bdefdf316394e6ffc33e8f84bd4e7c7333556a139ad76e73d44b` |
| `eclipsebasyx/submodel-registry-log-mongodb` | `2.0.0-SNAPSHOT` | `db6010732a3d0cc97159371f46194fd9038edf9dc5ba14d0bce543f3e819bc5e` |
| `eclipsebasyx/aas-discovery` | `2.0.0-SNAPSHOT` | `8d6f77a3ff5543cdcb0237d0003dd4ed45198633139bd8b0cce31a212402d8ed` |
| `eclipsebasyx/aas-gui` | `SNAPSHOT` | `a49b0c75b41269fd9e8bce5dd32bbbc69b65aee018c0f37b0a33c328ed860ebe` |
| `mongo` | `7.0.16` | `c630c59342c1493d50345136df2af14a76b9e827dd5316bfabee07a0880a5f3a` |
| `eclipse-mosquitto` | `2.0.15` | `bbac73a740f479b16a5f1a311ebf0c530664ce9290f2cfacb3f4711e7a104007` |

Compose uses `repository:tag@sha256:digest` for every image. SNAPSHOT is a
moving tag, not an immutable release: retain the digest to reproduce this
baseline. These pins capture the already-running images; recording them does
not upgrade or restart services. Other versions require fresh compatibility
testing, rather than an assumption that their version numbers are interchangeable.

Verify the installed SDK from the project root:

```powershell
.venv/Scripts/python.exe -c "import importlib.metadata; print(importlib.metadata.version('basyx-python-sdk'))"
docker compose -f BaSyxMinimal/docker-compose.yml config --images
docker compose -f BaSyxMinimal/docker-compose.yml ps
```

See [IDTA import compatibility](../docs/idta-template-catalog.md#sdk-upgrade-and-source-repairs)
for the source rejection counts, generated-copy adjustments and SDK test limits.

## Start

The public checkout includes the IDTA Collection and a configurable example
device JSON. Additional local device AASX files and the original backup ZIP
are not published. On a **fresh checkout**, prepare the seed list before the
first start:

```powershell
Copy-Item aas-env.example.properties aas-env.properties
```

This replaces the workstation-specific seed list with the two distributed
packages. Keep an existing customized configuration when updating a configured
installation. To add your own blueprints, list each file once in
`basyx.environment`; see the catalog notes below.

From this directory, with Docker Desktop running:

```powershell
docker compose up -d
```

The first start can take several minutes while the catalog is loaded. Check:

```powershell
docker compose ps
```

The AAS environment must be healthy before using AAS Creation. Start the local
application with `..\start.cmd` if needed.

| Component | Address |
| --- | --- |
| AAS, submodel and ConceptDescription repositories | http://localhost:8081 |
| AAS Registry | http://localhost:8082/shell-descriptors |
| Submodel Registry | http://localhost:8083/submodel-descriptors |
| AAS Discovery | http://localhost:8084/lookup/shells |
| AAS Web UI | http://localhost:3000 |
| MQTT | localhost:1884 |

Stop with `docker compose stop`; start again with `docker compose up -d`.
Mongo data persists in the named `basyxminimal_repository-m15` volume, with
Mongo configuration in `basyxminimal_mongo-config-m15`. Deleting containers
does not delete these volumes. The older `basyxminimal_repository` volume
from migration testing is not used by this configuration.

## Configuration and blueprints

On 2026-10-22, nine reference-type encodings were corrected in the source
`injection molding machine.aasx`, `process.aasx` and `robot disassembly.aasx`.
External semantic IDs now use `GlobalReference` keys; two AAS-to-SM bindings
now use `ModelReference`. All identifiers, semantic addresses, values, attachments
and relationship files were preserved. The three packages opened with the installed
AASX Explorer loader; the corrected references passed strict SDK checks and all
14 seed packages passed startup-batch validation. Details and checksums are in
[the repair report](catalog/reference-types-fix.json). This source repair did not
reimport or replace data in running repositories.

- `docker-compose.yml`: one formal project, named `basyxminimal`.
- `aas-env.properties`: BaSyx AAS Environment milestone-15, pinned by image
  digest, with the newer `spring.mongodb.*` configuration keys.
- MongoDB 7.0.16 uses a fresh volume rather than mounting MongoDB 5 database
  files. Registry, discovery, MQTT and viewer services retain their existing
  integration configuration and ports.
- `aas/`: all device blueprint packages and the new `CollectionofSMTs.aasx`.
  The collection contains 63 validated IDTA templates. The application exposes
  only templates referenced by this collection, not every submodel in the repo.
- The collection loads before device blueprints. `basyx.environment` lists each
  of the 14 files exactly once; do not combine the collection file with a scan
  of its containing directory. Update this list when adding a seed package.
- The AGV device submodel uses the instance ID
  `https://admin-shell.io/idta/aas/AGV/sm/TechnicalDataAGV`, with kind `Instance`.
  Its idShort stays `TechnicalDataAGV`, and its semanticId still identifies the
  standard template. The AGV shell references this instance; the Collection
  retains the original standardized SMT ID. Operations and attachments remain.
- Correction to the initial diagnosis: BaSyx's fatal exception concerned the
  repeated Submodel across packages, not its ConceptDescription. The temporarily
  removed dictionary definition has been restored. The XML retained in
  `catalog/quarantined-agv-concept-description.xml` is historical evidence, not
  an object currently excluded from the AGV package. See `catalog/startup-batch-fix.json`.
- AGV XML packaging was also checked with the installed Explorer's own
  `AdminShellPackageFileBasedEnv` loader. The repaired package uses an unprefixed
  content-types manifest root and explicit end tags for empty XML values. This
  corrects serialization compatibility without changing model data or attachment
  bytes. See `catalog/explorer-compatibility-fix.json`. The same loader also opened
  the new Collection with all 63 templates and 3000 ConceptDescriptions.
- `catalog/`: upstream attribution, release selection, exclusions, adjustments
  and the local promotion record. These records are outside the seed directory.
- `aas_backup.zip`: the original user backup, preserved byte-for-byte. It is
  not loaded on startup.

A clean database is initialized from the bundled blueprints. This is not an
automatic restore of previously created device instances. The pre-upgrade API
export, full Mongo archive (including stored attachments), and original folder
copy are preserved locally under:

`~/.a4s/backups/basyx-20261021T204406Z/`

Do not restore the old database over the new template catalog without handling
colliding template IDs. The new volume intentionally separates the clean
blueprint environment from the interrupted migration's database.

All 14 packages were deserialized using the actual milestone-15 Java libraries
from the running container. Its native `IdentifiableAssertion` passed the entire
configured batch: 14 shells and 105 submodels. The source-repair operation itself
did not restart the main service. After the user's subsequent
restart, the 2026-10-22 runtime check found the environment, both registries,
discovery, MongoDB and MQTT healthy, with the Web UI running. Container health
does not replace the per-template compatibility checks recorded below.
Repeat the configured-batch ID check from the project root:

```powershell
.venv/Scripts/python.exe scripts/validate-basyx-seeds.py
```

It checks ZIP integrity, package-local IDs, repeated Shell/Submodel identities
across the configured startup batch, and repeated loading of the same file.
It also checks the content-types root syntax required by the installed Explorer.
Dictionary definitions may recur across packages. This is not a full service
startup check. Three regression cases cover cross-package Submodel reuse,
overlapping file/directory loads, and legitimate dictionary reuse.
`scripts/normalize-aasx-xml.py INPUT --output OUTPUT` can prepare a separate
Explorer-compatible XML package. It preserves model namespace declarations and
expands empty tags without discarding optional values. Verify the separate
output before replacing a source; two regression cases cover this conversion.
See [catalog compatibility notes](../docs/idta-template-catalog.md) for the
completed SDK and CLI checks and their limits.

Deployments may use a separate device repository. `A4S_SMT_ENDPOINT` selects the
template source; the selected target AAS repository remains independent.
