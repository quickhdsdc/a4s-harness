# Blueprint discovery and template search

In AAS Creation, use **Search templates** to filter standardized templates by
name, description or version. All search words must match. The count shows the
number visible and selected; **Selected only** helps review your choices.
Filtering never deselects hidden templates. Clear the filters to return to the
whole collection. Templates still come exclusively from the configured
CollectionofSMTs.

## Shopfloor blueprint creation

The asset library loads current blueprint identities through `GET /api/blueprints`.
Drag a blueprint to create a device instance. New blueprint names are supported
without adding a repository URL or ID to frontend code. Known names retain their
existing icons and floor types; that presentation mapping does not choose IDs.
Use **Refresh library** after importing, removing or renaming a source blueprint.

The former frontend contained a fixed `BLUEPRINT_IDS` table. Some entries used
example namespaces while the actual device blueprints retained their original
IDs. That mismatch returned404 before the backend could read a blueprint. The
table has been removed; each discovered card carries its canonical ID and source
repository. The create route reads the shell and its current submodel references
from that source. New identities are derived from the selected blueprint, not
from its former namespace. Existing-AAS navigation uses the created canonical ID.

Source lookup defaults, in order:

1. An explicit `blueprint_endpoint` on the creation request.
2. `A4S_BLUEPRINT_ENDPOINT`.
3. `A4S_SMT_ENDPOINT`.
4. `A4S_AAS_ENDPOINT`.

The selected destination `endpoint` on the creation request determines where
new device models are written. Library and destination can be separate
repositories. The response includes `blueprint_id` and `blueprint_endpoint`.
This changes model discovery/copying; it does not invoke device operations.

Blueprint discovery uses `assetInformation.assetKind=Type`, excluding the SMT
collection. The existing legacy Instance-as-blueprint compatibility list and
`A4S_BLUEPRINT_IDS` classification overrides remain; these classify known legacy
models and do not prescribe the identities used for ordinary Type blueprints.

The floor shows creation in progress. A failed create displays an error and
removes the unsuccessful visual placeholder rather than leaving a phantom asset.

## Local verification

The corrected route created and read back temporary instances from all13 local
device blueprints, including CNC, injection molding and AGV. Submodel counts
matched their source shells; successful test instances were removed and original
blueprint shells compared unchanged. Separate-repository behavior and arbitrary
publisher IDs are covered by backend regression tests.

The template keyword and blueprint-card helpers have frontend regression tests.
Browser validation records are generated under `work/records/blueprint-creation-20261021/`;
they are local test evidence, not deployment artifacts. No remote deployment is
part of this change.
