# IDTA template catalog

The 2026-10-21 compatibility trial produced the 63-template catalog now bundled
in `BaSyxMinimal/aas/CollectionofSMTs.aasx`. Its configuration replaces the old
local BaSyx stack and both temporary test stacks. After the user's manual
container startup, the 2026-10-22 runtime check found the AAS environment and
its supporting services healthy, with the Web UI running. No remote deployment
occurred as part of this catalog import.
See [local startup instructions](../BaSyxMinimal/README.md).

## Backup and artifacts

Before downloading or importing, the original repository was exported and Mongo
archived under `~/.a4s/backups/basyx-20261021T195827Z/`:

- `repository.json`:20 shells,81 submodels,617 ConceptDescriptions.
- `mongo.archive.gz`:read-only database dump.
- `CollectionofSMTs.aasx`:byte-exact original blueprint copy.
- `blueprint-file.json`:original path and SHA-256. The original and copy hash is
  `b91a63930767f8b7c1e5c7551071a116f19f8bf66d206f3bac68c083095688ed`.

Generated artifacts are under `work/records/idta-smt-catalog-20261021/`:

- `CollectionofSMTs_IDTA.json` and `CollectionofSMTs_IDTA.aasx`:trial collection.
- `raw/`,source/download manifests and upstream license:unmodified source files,
  exact release paths,commit and byte hashes.
- `audit-report.json`:SDK checks and package round-trip counts.
- `cli-report.json`:real repository command results per linked template.
- `quarantined-templates.json`:original models that strict SDK parsing rejects.
- `alternate-template-variants.json`:the alternative TimeSeries operation variant.
- `conflicting-concept-descriptions.json`:all variants of excluded definition IDs.
- `catalog-adjustments.json`:every local example-file value adjustment.
- `supplementary-files.json` and `sdk-reader.log`:attachment provenance and reader
  diagnostics. Successful parsing does not imply complete semantic conformance.

The user subsequently authorized promotion. The verified AASX is now in the
active seed directory, and provenance/adjustment records are in
`BaSyxMinimal/catalog/`. The full pre-promotion backup, including original folder
contents and Mongo attachments, is `~/.a4s/backups/basyx-20261021T204406Z/`.
The original `aas_backup.zip` remains byte-exact.

## Source selection and results

The requested [hosted repository](https://smt-repo.admin-shell-io.com/) is usable
but its inventory/download map lags the official published release tree. Both
were inspected; latest release selection uses the pinned official GitHub commit
`f3790038b6c9c2d7e5ebbb4609997468fadf3e85`. See
[source investigation and citations](idta-template-repository-sources.md).

The website inventory had62 templates and4 instances. Latest published JSON
files covered65 release families,66 files and67 template models; MTP packages
also contained4 example instances, which were not imported as templates.

With `basyx-python-sdk==2.2.0`,64 of67 original template models parsed strictly.
The generated catalog links63 unique IDs. TimeSeries standard/withOperations
artifacts share one ID, so the standard variant is linked and the other remains
in raw evidence. No official model ID was rewritten to disguise the collision.

Three templates were quarantined without changing their semantics:

| Template | Strict reader failure |
| --- | --- |
| CapabilityDescription | Repeated SMT/Cardinality qualifiers with different values:ZeroToMany and Recursive. |
| PAMSpecificationSheet | Repeated FormInfo qualifier type with different text. |
| IEC81346Structure | SelfManagedEntity lacks a global/specific asset identifier. |

The63 linked templates retain33 templates with277 SubmodelElementLists and5788
addressable SMEs. Full strict JSON/AASX read-back retained3064 identifiable
objects:one Collection shell,63 templates and3000 ConceptDescriptions. Lists
were not flattened into collections.

Aggregating official files exposed104 definition IDs with different payloads
and12 ConceptDescription IDs also used by Submodels. Their variants are retained
separately rather than choosing a global definition arbitrarily. Semantic
references remain in their original models, so some referenced definitions are
not available in the aggregate. This is a compatibility catalog, not a claim of
complete dictionary closure.

Two available source attachments were packaged. Sixteen example File URIs could
not be found in their corresponding official AASX files; only those example
values were cleared in the generated copy. The File SMEs and their types were
retained. Original bytes and each before/after URI remain in the records. Other
upstream templates were not repaired to force reader acceptance.

The initial CLI validation found9 forbidden list-child idShort attributes in
ProductCondition,MaterialComposition andRailwayFireProtection. SDK decoding
silently removes them, so SDK readability alone does not establish raw-template
conformance. The generated JSON and AASX now explicitly remove those9 attributes,
with the original names retained in the adjustment log; list positions, content
and ordering remain. Another176 omitted `orderRelevant` values are written as
the [standard default true](https://github.com/admin-shell-io/aas-specs-metamodel/blob/master/documentation/IDTA-01001/modules/ROOT/pages/spec-metamodel/submodel-elements.adoc),
because the Java and Python readers materialized different defaults in this
trial. Explicit source values,including false,are preserved. Thus201 logged
adjustments comprise16 dangling file examples,9 list names and176 explicit
defaults. The original source bytes were never changed.

Final real CLI verification passed63/63 each for template display,tree parsing,
validation with no findings,and dry-run instantiation. The application template
list adapter returned63 from the trial source; the normal running application
returned7 before promotion. Ninety-five related backend tests passed after the localized
slot fix. These results do not imply all SDK nonfatal reference diagnostics or
dictionary-reference gaps have been resolved.

## SDK upgrade and source repairs

The current required SDK is `basyx-python-sdk==2.2.0`, checked in the project
virtual environment and pinned in both the `aas` and `ui` extras. The tested
container versions and immutable image digests are recorded in the
[BaSyx README](../BaSyxMinimal/README.md#required-versions).

This trial demonstrates that SDK 2.2.0 can read the retained templates with
their SubmodelElementLists intact. It does **not** establish that an older SDK
could not read those same models: the historical SDK version and a controlled
old/new comparison on the same input files were not recorded for this trial.
Do not attribute every earlier parsing failure to the SDK upgrade. Upstream
[guidance](https://github.com/eclipse-basyx/basyx-python-sdk#specification-compliance)
distinguishes the SDK package version from the supported AAS specification and
explains that strict readers can reject nonconforming files from other tools.

The download was not universally problem-free. Of 67 original template models,
64 passed the strict SDK reader; three remain quarantined, and one alternate
TimeSeries representation was not linked because it shares a model ID.
The 63-template generated collection includes 201 logged adjustments:

| Adjustment in the generated copy | Count |
| --- | --- |
| Clear example File values whose attachments are absent upstream | 16 |
| Remove forbidden `idShort` attributes on direct list children | 9 |
| Materialize omitted `orderRelevant` as the standard default `true` | 176 |

These are adjustment counts, not counts of distinct templates. Raw downloads
remain unchanged; generated-copy changes are recorded in
[`catalog-adjustments.json`](../BaSyxMinimal/catalog/catalog-adjustments.json).
The three rejected models were not rewritten to force acceptance. Dictionary
conflict handling and missing referenced definitions are described above.

Separate local fixes addressed application-generated empty multilingual values,
legacy device-blueprint reference types, cross-package AGV identity collisions,
and AASX Explorer XML packaging. Those are distinct from the IDTA source
adjustments. The final 63/63 CLI parse, validation and dry-run instantiation
results apply to the curated collection, not to every untouched upstream file.

## Application correction

Instantiation used to write an unfilled MultiLanguageProperty as `value:[]`.
SDK2.2 rejects an empty MultiLanguageTextType. The local instantiator now omits
the optional value instead; it does not insert fabricated text. A regression
test deserializes the actual instantiated slot with the strict SDK. This is
an application fix, distinct from upstream template problems.

The CLI outline/tree and dry-run instantiation tests are structural checks.
They do not establish full PDF extraction, entity-matching quality, migration
across changed family identifiers, or production readiness for every template.

## Reproduce and inspect

Start only the maintained local stack, using `docker compose up -d` from
`BaSyxMinimal/`. No18081/18082 test-stack Compose files are needed.

Rebuild the same pinned catalog offline from the application point of view
(downloads require network access; this does not import into a repository):

```powershell
.venv/Scripts/python.exe scripts/audit-idta-templates.py --commit f3790038b6c9c2d7e5ebbb4609997468fadf3e85 --output work/records/idta-smt-catalog-20261021
```

The script retains unmodified downloads, reports incompatible artifacts and
reuses cached raw bytes for the same pinned commit. Use a new output directory
when selecting another release snapshot. Optional `--import-endpoint` is
create-only and aborts on conflicting model IDs; do not use it to upgrade a
populated repository blindly.

After manually starting the final local stack, inspect and rerun the structural
CLI checks without writing any models:

```powershell
.venv/Scripts/python.exe -m a4s.aasctl --endpoint http://127.0.0.1:8081 --json smt list --from-endpoint http://127.0.0.1:8081 --of-shell urn:a4s:catalog:idta:20261021
.venv/Scripts/python.exe scripts/audit-idta-templates.py --output work/records/idta-smt-catalog-20261021 --verify-endpoint http://127.0.0.1:8081
```

## Local blueprint promotion

The configuration pins BaSyx milestone-15 and uses Mongo7 with new named
volumes. The collection loads before legacy device packages. The AGV package's
TechnicalDataAGV previously shared an ID with the current template while using
a different internal structure. During the interrupted restored-database trial,
BaSyx retained that older model, then failed while importing an attachment at
`GeneralInformation.ProductImages[0].ImageFile`. The same encoded HTTP path
returned404 in the old-copy repository and200 in the new-template repository.
This was a conflicting stored structure, not proof that list paths are unsupported.

The final source AGV package now uses the current TechnicalDataAGV, includes its
two referenced files, and preserves the original shell and delegated services.
The new volume avoids the partially migrated database. Existing runtime data
remains recoverable from the full backup; the clean stack starts from bundled
blueprints. The prior isolated63-template CLI results are not a substitute for
starting and checking this final combined stack.

The subsequent startup error was initially misdiagnosed as the package-local
Submodel/ConceptDescription ID clash. Inspection of the actual Java
[IdentifiableAssertion](https://github.com/eclipse-basyx/basyx-java-server-sdk/blob/2.0.0-milestone-15/basyx.aasenvironment/basyx.aasenvironment-core/src/main/java/org/eclipse/digitaltwin/basyx/aasenvironment/environmentloader/IdentifiableAssertion.java)
showed that this fatal check concerns Shell/Submodel identities across the whole
load batch. It does not inspect ConceptDescriptions. Two batch faults remained:
the AGV package repeated a Submodel already loaded from the Collection, and the
file-plus-containing-directory setting loaded the entire Collection twice.

The AGV now has an independently identified device submodel of kind Instance;
its semanticId still points to the standardized template and the shell reference
was updated. The temporarily removed ConceptDescription was restored. Startup
now names every seed file exactly once, with the Collection first.

The validator reproduced 65 repeated load identities before the batch correction
and passes all 14 files afterward. An offline Java harness using the actual
container libraries reproduced the native exception before the correction and
then deserialized every package and passed the native checker for 14 shells and
105 submodels. It starts no server and writes no repository. Three automated
regression cases cover the batch behavior. No main service was restarted after
the correction; live startup verification remains pending. See
`BaSyxMinimal/catalog/startup-batch-fix.json`.

## Explorer interoperability correction

Java startup deserialization did not establish compatibility with the installed
AASX Explorer. Its actual `AasxCsharpLibrary.dll` loader opened the original AGV
backup but rejected the edited package's prefixed `ns0:Types` manifest root with
`Required Types tag not found`. Repairing that exposed a second error: seven
empty Blob values had been serialized as self-closing XML elements. Writing
explicit end tags preserved those empty values and made the loader succeed.

The final active AGV package was verified through that same local loader:
1 shell, 2 submodels, 103 ConceptDescriptions. The new Collection also loaded:
1 shell, 63 templates, 3000 ConceptDescriptions. Parsed XML trees before and
after the syntax repair compare equal; all attachment and relationship parts
are byte-identical. This is a loader API check, not interactive GUI automation.
No container was restarted. Backup and hashes are recorded in
`BaSyxMinimal/catalog/explorer-compatibility-fix.json`. The maintained normalizer
requires a separate output file, and the batch validator now catches the
manifest-root failure as well as repeated startup identities.

Upstream artifacts retain their CC BY4.0 attribution and license. The generated
package's adjustment record accompanies it; the application license does not
replace template or embedded third-party terms.
