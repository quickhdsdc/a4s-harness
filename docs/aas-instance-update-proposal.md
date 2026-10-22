# AAS instance updates and template migration — proposal

Date: 2026-10-21. Status: design proposal for discussion; no workflow or remote
deployment change is implemented by this document.

Implementation checkpoint, 2026-10-21: the local reviewed update workflow is now
available. See [usage and validation boundaries](aas-instance-updates.md). The
proposal below also contains future directions, such as curated cross-version
migration maps; it is not a claim that every automatic conversion is implemented.

UI revision, 2026-10-21: the earlier per-template strategy/target selectors are
superseded by a shared standardized-template checklist. The backend now prepares
category-based replacements and feeds old populated values into Matching with
new input. Unrelated existing SMs remain destinations. See the usage document
for current behavior; the strategy discussion below is historical design context.

## Problem and current implementation

An existing device may contain a partially populated Submodel whose template is
old, unknown, modified, or unchanged. Selecting an SMT must not automatically
create a duplicate or erase that device's existing data. Matching must consider
the selected template's full shape even when blank slots were previously pruned.

Local source inspection: `cmd_smt_instantiate` currently creates an instance, or
explicitly replaces an existing one by deleting/recreating it. It does not perform
a semantic migration. The append-only ledger is reusable audit infrastructure,
but existing mutation summaries are not a complete, recoverable state history.

## Keep identities independent

| Concept | Proposed identity and purpose |
| --- | --- |
| Template family | Curated stable catalog key, e.g. IDTA specification family and application role. Not inferred by removing version segments from a URI. |
| Template release | Immutable artifact ID, declared version/revision, full semantic reference, source repository and content hash. |
| Live SM instance | Target repository identity + canonical Submodel ID; attached to a particular AAS/role. |
| Instance content revision | A4S revision/change-set ID and snapshot hash, independent of the template release number. |

`idShort` remains the readable SMT name. It is not a uniqueness or migration key.
`semanticId` and `administration.templateId` are useful evidence, not substitutes
for explicit cross-release compatibility. Record the template release actually
used; never infer it from an inherited instance version alone.

A published SMT release is immutable. Retain multiple releases in the catalog,
with distinct artifact IDs if stored simultaneously in the same repository.
Conflicting artifacts with the same ID/version but different hashes require
disambiguation. Legacy same-ID overwrites cannot be reconstructed retroactively
without a retained snapshot. Unknown release metadata remains unknown.

## One update workflow, explicit intent

| Intent | Default behavior |
| --- | --- |
| Add | Create/attach a new SM when none serves the chosen role. |
| Enrich | Preserve live ID and all existing values; fill missing slots, including slots absent from the pruned instance. |
| Migrate | Build the chosen release's structure, migrate existing values and reviewed custom fields, then integrate new input. |
| Replace | Prepare a replacement without assuming old values should carry over; archive the old state and review removals before activation. |

An intentional parallel SM is a separate explicit choice. Family similarity alone
does not prove that two SMs represent the same role: multiple nameplates may
legitimately describe different suppliers, components or contexts.

Template selection first discovers candidate existing SMs. Evidence includes
retained provenance, full semantic references, documented family/version maps,
role, and structural similarity. Names/embeddings/LLM output can propose a
candidate, but must not silently authorize a destructive merge. A human selects
the exact target when evidence is insufficient.

## Candidate state before live mutation

1. Read the selected target AAS/SM and retain its baseline and hash.
2. Pin the chosen SMT artifact, version, hash and structural constraints.
3. Construct a candidate graph from the SMT, overlaying compatible existing
   instance data and local extensions. Do not copy SMT example values as evidence.
4. Match new extracted data against that candidate graph, not merely the sparse
   live instance. Distinguish existing targets from slots that must be created.
5. Preview additions, value updates, preserved values, moves, conversions,
   removals and unresolved conflicts, with old/new values and source evidence.
6. Apply the reviewed plan, re-read actual results and record committed/partial/
   failed state. Idempotency keys prevent a retry from creating another instance.

For migration, use the old retained template, the new template and the current
instance to distinguish template evolution from site customization. New document
data is another input to that comparison. If the old template is unavailable,
allow conservative enrichment and explicit reviewed mappings; do not infer that
unmatched existing fields are obsolete.

Prefer exact semantic correspondence and reviewed release mappings. Unit
conversion, renamed/moved fields, cardinalities and SME type changes require
validation. An LLM may suggest mappings; a typed executor performs Property,
MultiLanguageProperty, Range, File and other writes using the appropriate shape.
Missing new evidence is not an instruction to erase a previously known value.

The current blank-property/collection pruning remains relevant, but it must be
included in the reviewed change set and history. Empty mandatory elements cannot
be pruned while claiming full template conformance. Retain a full template
baseline outside the sparse runtime instance so later enrichment can restore
needed paths. Do not extend cleanup into unrelated SMs or template artifacts.

## Commit and identity policy

Compatible enrichment normally retains the live Submodel ID. Breaking migration
or complete replacement can prepare a new SM with a fresh ID, validate it, then
switch the target AAS reference. Keep the old state in history, not as a duplicate
active SM by default. Check external references before switching IDs; check shared
SM usage before altering or deleting a repository resource.

Multiple REST writes are not assumed atomic. Prefer supported conditional writes
and repository transaction capabilities. If absent, serialize A4S writes, check
the baseline again, journal individual results and reconcile on interruption.
A client-side hash check alone does not prevent another writer racing afterward.
Do not advertise atomic rollback where the repository cannot provide it.

## History: snapshots and change sets first, Git as an optional adapter

Extend the existing ledger with a durable update record: target repository/AAS/SM,
before and after snapshots/hashes, exact SMT release, input document hash and
locators, mappings, human decisions, executor version, time, actor, and actual
per-write results. Record the intended update durably before mutation and its
observed result afterward. A recoverable state revision includes shell references,
relevant SMs and required referenced artifacts, not just a count of writes.

Snapshots and documents belong in persistent application storage, not `work/temp`.
Capture replacements and cleanup deletions as well as additions. Changes made
outside A4S need repository history/events or a monitored gateway; an A4S-only
ledger cannot promise complete history of manual/other-client writes.

Git is suitable for published templates, migration maps and reviewable JSON
checkpoint exports. Keep instance-history exports separate from the software
repository and exclude credentials. Do not commit live telemetry per sample.
Normalize serialization without reordering semantically ordered AAS lists.
Git does not provide typed semantic migration, live REST transactions or automatic
restoration of the running repository. Restore means a new reviewed update,
validated against the current state; it does not mean `git reset` on a server.

## UI and rollout proposal

Keep creation and existing-instance update as entry points to the same workflow.
For each selected SMT show family/release, detected existing target, and intent.
Default to enrichment when a clearly identified target exists. Put alternative
targets, parallel instances and replacement behind explicit choices.

Matching preview should show existing value, proposed value, destination path and
operation (keep/fill/update/create/move/remove), followed by a compact change
summary. Reuse human review instead of adding a generic second warning gate.

Implement locally in stages: (1) same-release enrichment and target discovery,
(2) snapshots/change sets and reviewed restore, (3) pinned multi-release catalog,
(4) explicit release mappings and schema migration. No remote rollout is proposed
until the local workflow is validated.

All three deployments share the logic through configuration. A4S's template
repository remains separate from the production-instance repository.
Include repository identity in every plan and history key.

## Primary references

- [IDTA AAS metamodel 3.1.2: administrative information](https://industrialdigitaltwin.io/aas-specifications/IDTA-01001/v3.1.2/spec-metamodel/common.html): version/revision and templateId; templateId documents origin, semanticId is relevant to validation.
- [IDTA AAS metamodel 3.1.2: core](https://industrialdigitaltwin.io/aas-specifications/IDTA-01001/v3.1.2/spec-metamodel/core.html): AAS references SMs; derivedFrom relates AASs, not arbitrary SM content revisions.
- [OSLC Configuration Management primer](https://docs.oasis-open-projects.org/oslc-op/config-primer/v1.0/config-primer.html) and [change sets](https://docs.oasis-open-projects.org/oslc-op/config/v1.0/os/config-resources.html#change-sets): immutable baselines, mutable streams and reviewed changes provide a useful engineering pattern without requiring an entire PLM platform.
- [BaSyx Go AAS repository history](https://wiki.basyx.org/en/latest/content/user_documentation/basyx_components/go/aas_repository/usage.html#read-a-historical-aas-state): optional recording must be enabled before changes and is not retroactive. This is not proof of support in our Java `2.0.0-SNAPSHOT` deployment.

These sources ground the vocabulary; the workflow above is an A4S design proposal,
not a claim that the AAS standard mandates this migration/version-control system.
