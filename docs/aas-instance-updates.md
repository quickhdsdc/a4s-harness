# Update an existing device AAS

Start the local application with `start.cmd`, then open
<http://localhost:5173>. `stop.cmd` stops this checkout's frontend/backend and
leaves Docker and persistent data intact.

## Workflow

1. Choose **Create New AAS** or **Edit Existing AAS**. Editing starts by selecting
   a device. Its existing submodels appear as compact blocks, with declared versions,
   inside the selected device card. They sit beside its identity when space permits
   and wrap below it in a narrow panel. Update history stays collapsed in that card.
2. Both modes use the same **Submodel templates** checklist, including
   declared version/revision. There are no update-strategy or target-SM selectors.
   Search by name, keyword or version. Help is available from the question mark
   by hover, keyboard focus or click. Connection settings stay in a collapsed section.
3. When editing, choose the information to add or update. At Next the backend
   compares the selected templates and this device's existing submodels in one
   LLM request, with visible preparation status. It prepares an isolated candidate.
   For each selected template it identifies existing submodels of the same
   information category, extracts their populated data as input facts,
   and stages one fresh template instance instead of those old matching targets.
   Unrelated existing submodels remain matching destinations and retain their data.
4. Upload/select input and review extraction. Matching receives document facts
   together with the extracted old facts in one global batch. Old submodel name,
   path, declared SME type, unit and source remain available for interpretation.
5. Review matching. Source filenames and provenance remain in the evidence,
   without filling the review table. Equal values for the same destination are combined. Different values for one
   destination start unselected as alternatives; choosing one deselects the other.
   Bulk selection does not choose unresolved alternatives. Unmatched or unselected
   old values are not written into the replacement; review them before applying.
   Gray means not selected for writing; it does not remove the proposed match.
   **No Match** identifies an entity with no destination. Unselected rows have no
   strikethrough. A short **Choose a value** prompt disappears when its field has
   a selected alternative; further explanation stays in a question-mark tooltip.
6. Click **Next** once. The checked matches are the user's reviewed choices.
   The application builds and validates the revision, then commits that exact
   review hash automatically. There is no separate Preview/Apply click. Review
   failures stop before any commit. Baseline checks, journaled writes, new bindings
   and read-back verification remain in force. Old bindings are detached only here,
   after the new SMs have been written and attached. Old repository resources and
   before-snapshots remain available for history/shared users.
7. Population shows the actual write counts. **View update details** is collapsed
   by default and contains submodel replacements, readable change counts, the diff
   and **Template coverage**. Unfilled required template items are completeness
   diagnostics, not failed writes. The count includes fields and containers
   omitted by blank cleanup; template completeness can remain incomplete after a
   successful population. The diagnostics do not add a confirmation step.

With no template selected, all existing submodels stay matching destinations;
there is no replacement or template upgrade. An empty AAS needs a template.
Blank-element cleanup applies to all candidate SMs, including retained ones.
Writes are sequential REST operations: an interruption can produce a partial
result, which is recorded for reconciliation.

`idShort` remains the selected template's readable name. New globally unique IDs
are used for template instances. Multiple selected templates can add/update
several categories together. Select only one version of each category per run;
the backend rejects overlapping template categories.

## Templates and automatic category detection

The configured single CollectionofSMTs is an internal catalog mechanism; user
copy calls its entries **standardized submodel templates**. `A4S_SMT_COLLECTION`
accepts its canonical ID or idShort; the default is `CollectionofSMTs`. Template
source and production instance repository remain separate. The picker reads only
the current Collection's referenced templates. Refresh reloads that list; Next
also refreshes existing selections and clears IDs no longer offered, preserving
valid choices. Preparation reads the selected template resources directly and
checks that they are actual SMTs, without another Collection-membership gate.
An external catalog edit therefore does not invalidate an otherwise valid
template resource during preparation. Template pinning and revision review remain
in force.

The LLM comparison receives names, declared template origins, semantic references,
descriptions and bounded structural outlines of selected templates and existing
SMs. It does not need raw value payloads to classify categories. Different names
and semantic-reference schemes can still describe one information category:
`TechnicalData_IMM` and `TechnicalDataIMM` are a verified local example.

The response must account for every selected template and every existing SM.
Existing SMs are either assigned once to a replacement group or explicitly kept;
invented IDs, duplicate assignments and incomplete partitions are rejected. The
model is instructed to keep ambiguous or unrelated categories, including different
device/component domains. No rule-based fallback silently replaces a failed model
comparison. Exact metadata rules still reject obviously overlapping selected SMT
versions before the comparison. No model call is needed without selected templates
or without existing submodels. Decision reasons, model and input hash are retained
as `categoryAssessment` in the revision. Review remains necessary before writing.

Each selected template is snapshotted and pinned by source, ID, declared
version/revision and content hash before candidate generation. The normal
checklist offers the current catalog entries: publish multiple referenced IDs
in the Collection to offer several versions. The backend also retains pinned
archived releases for history and the earlier explicit-update adapter; removal
from the catalog does not remove historical snapshots.

Existing typed values remain source facts. Keeping a compatible unchanged old
value preserves its native payload (including language entries, MIME types and
structured references). Changed values use type-aware conversion and validation.
There are no guessed unit conversions or arbitrary schema migration maps.
Operations, relationships and other non-value structures are retained in the
before-snapshot rather than treated as ordinary scalar matching facts; inspect
structural deletions in the review when replacing such a submodel.

The pinned Python SDK validates complete candidate SME types and list rules.
Blank Property/MultiLanguageProperty and recursively empty collections are pruned.
Unfilled newly introduced File/Blob/Range/reference slots are omitted; existing
non-Property SMEs are preserved. The result distinguishes actual empty-element
removal from unused template slots never written to the repository. Template
completeness notes remain collapsed and do not suppress reviewed writes. A sparse
instance is not advertised as fully conformant when required slots are absent.

## History, interruptions and restore

History is under the configured, expanded `$A4S_HOME` (default `~/.a4s`):

- `instance-updates.sqlite3`: drafts, immutable template artifacts, before/after
  snapshots, reviewed diffs, evidence manifests, operation journal and outcomes.
- `instance-update-artifacts/`: retained content-addressed input/extraction files.
- `instance-update-locks/`: small OS lock files; process exit releases the locks.

These are persistent application data, not disposable `work/temp` files. Web
actions are honestly recorded as actor `web`; no authenticated human identity is
invented. The existing ledger additionally links each commit to its revision.

Under the selected instance's **Update history**, download snapshots or choose
**Preview restore**. Restore creates a new reviewed revision from the current
baseline. It preserves unrelated SMs and does not rewrite the old history entry.

If a worker or network fails, use **Check actual result** to read the repository
again without repeating writes. `partial`/`uncertain` states retain pending and
acknowledged operations. Unverified values are distinguished from verified values.
Reconcile before deciding whether to restore or prepare a fresh update.

The baseline check and cross-process A4S lock prevent stale or simultaneous A4S
commits. They cannot provide a distributed transaction against other direct
repository writers. External changes detected before/after writing are exposed;
complete history of manual changes outside A4S needs repository-side capture.
Shared SMs require replacement rather than an in-place write affecting other AASs.

Git may store exported JSON checkpoints separately. Git checkout/reset does not
restore a running repository. Do not put private instance data, credentials,
SQLite databases, or telemetry into the software source repository.

## Maintained local BaSyx environment

The verified milestone-15 repository configuration and SDK 2.2.0 now replace
both temporary verification stacks. Use `BaSyxMinimal/docker-compose.yml` on
port8081. The independent upgrade copy on18081 and template trial on18082 are
retired. See [BaSyx setup](../BaSyxMinimal/README.md) for the single start command,
fresh Mongo7 volumes, bundled blueprints, backups, and startup validation status.

Before another migration, create a read-only API export and Mongo archive:

```powershell
.venv/Scripts/python.exe scripts/basyx-backup.py --endpoint http://127.0.0.1:8081 --mongo-container basyxminimal-mongo-1
```

Backups go to `$A4S_HOME/backups/basyx-<UTC time>/`. Import API snapshots only
into a deliberately selected empty repository; `--import-file` creates resources
and reports conflicts rather than overwriting them. A JSON export alone does
not include stored attachments. Keep the full Mongo archive for recovery.

The final local file promotion was prepared with containers stopped at the
user's request. Fresh startup of the final configuration is pending. Earlier
isolated repository and instance-update checks remain valid within their
original test scope; they are not a final clean-start claim.

## Verification

The single-Next population flow was verified locally on 2026-10-22. One click
uses the current checked matching rows to generate a reviewed revision and then
commit that exact hash; a failed review never invokes commit. Firefox and
Chromium exercised both outcomes. Result details are collapsed, and template
coverage diagnostics are clearly separate from actual write failures. The
53 focused backend tests, 43 frontend tests and production build passed.
The maintained Firefox integration also completed real category preparation,
matching, a single-Next commit and read-back of `NEW456` on a disposable device;
the old resource retained `OLD123` and test resources were removed. Evidence is
in `work/records/one-click-population-20261022/verification.json`.

Real BaSyx read-back exposed one serialization equivalence: an empty
SubmodelElementList value can return as null/absent instead of `[]`. The revision
hash treats those empty states identically only for that SME type. Nonempty list
elements, their order and type declarations remain part of the strict comparison.

The 2026-10-22 category-comparison change passed 52 focused backend tests, 43
frontend tests and the UI build. A real model comparison of
`InjectionMoldingMachine_155` selected only the old `TechnicalData_IMM` for
replacement by `TechnicalDataIMM`, retained its other three SMs and carried all
eight populated old facts into the input pool. Firefox Next showed the preparation
phase and exposed only one IMM technical SM in the candidate matching graph.

A disposable copy completed REST preparation, review, commit and SDK read-back:
8/8 old values survived, all four final SMs passed strict validation, and only
one IMM technical SM remained attached. That copy and its SMs were removed; the
user's original instance and SMT resource remained unchanged. Evidence:
`work/records/imm-category-20261022/{live-review,live-commit,browser-next}.json`.

Legacy metadata compatibility is applied to reviewed candidate copies, never
directly to the source blueprint, template or baseline. A single-key semantic
`ExternalReference` incorrectly using key type `Submodel` is normalized to
`GlobalReference` without changing its IRI. Empty optional `category` attributes
are omitted. Both repairs appear in the revision and schema diff; other malformed
references and SME payloads still fail strict SDK validation. See
[IDTA referencing constraints, AASd-122](https://industrialdigitaltwin.io/aas-specifications/IDTA-01001/v3.1.2/spec-metamodel/referencing.html).

Previously prepared drafts retain their old matching scope. Start a fresh workflow
with Reset to use LLM category comparison; old matching decisions must not be
reused after replacement targets change.

On 2026-10-22, HTTP regression checks reproduced a routing failure for canonical
HTTPS AAS IDs: URL decoding restored `/` before route matching, so the old
single-segment parameters returned `404 Not Found` before looking up the device.
The parse, existence, property and export routes now accept complete IDs using
path parameters. Tests cover HTTPS IDs, URNs and idShorts while preserving the
explicit target repository. The 41 focused backend tests and 42 frontend tests
passed, as did the production UI build.

Firefox and Chromium checks uploaded the IMM demo PDF, selected a template and
clicked Next for `InjectionMoldingMachine_155`. Existence, graph parsing and
automatic update preparation returned 200, and Extraction opened. The checks
also covered inline inventory, versions, keyboard help and narrow-panel Next
visibility. They did not run a new model extraction or commit an update; the
live target state remained unchanged. Evidence is in
`work/records/compact-aas-input-20261022/verification.json`.

Install application UI/validation dependencies with the exact pins:

```powershell
.venv/Scripts/python.exe -m pip install -e '.[ui,dev]'
.venv/Scripts/python.exe -m pytest tests/test_instance_updates.py tests/test_instance_update_routes.py tests/test_template_catalog.py
```

Real repository checks create/remove only synthetic resources. For development,
prefer a disposable repository; select its endpoint explicitly:

```powershell
$env:A4S_UPDATE_TEST_ENDPOINT='http://127.0.0.1:8081'
.venv/Scripts/python.exe -m pytest tests/integration/test_instance_updates_live.py -m integration
```

These checks also passed against the original localhost:8081 repository. Browser
verification used Firefox, real matching, preview, commit and read-back, with a
known extraction fixture (not a fresh PDF extraction). Chrome automation was
blocked by the workstation's administrator policy; that policy was not changed.

To repeat the browser check, install `.[browser]`, run
`python -m playwright install firefox`, set `A4S_UI_TEST_URL` to the local frontend
and `A4S_UPDATE_TEST_ENDPOINT` to the chosen test repository, then run
`pytest tests/integration/test_instance_update_browser.py -m integration`.
`A4S_SOURCE_TEST_ENDPOINT` defaults to localhost:8081; it must contain the local
DigitalNameplate template used by this fixture. The browser uses an isolated
profile and known extracted text, not an operator's browser session.

The template/production distinction applies in every deployment. Templates can
remain in a library repository while devices use a separate target. Plans, history
and cache identities include the target repository and canonical AAS identity.
