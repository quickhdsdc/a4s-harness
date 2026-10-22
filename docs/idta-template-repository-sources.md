# IDTA template repository: source and release checks

Checked on **2026-10-21**. This note records source discovery, not a claim that
every downloaded template passes the A4S CLI or BaSyx SDK. Those compatibility
results belong to the import run report.

## Official sources and release selection

The [IDTA GitHub repository](https://github.com/admin-shell-io/submodel-templates)
owns the template artifacts and links to the hosted repository. Its
[README](https://github.com/admin-shell-io/submodel-templates/blob/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/README.md)
defines `published/` as officially released and registered. `deprecated/`
remains usable but is no longer maintained. Development work is managed
separately. Therefore release status must come from the source location; a
larger version number alone is insufficient.

This investigation pinned the official tree to commit
`f3790038b6c9c2d7e5ebbb4609997468fadf3e85`. The
[recursive tree API](https://api.github.com/repos/admin-shell-io/submodel-templates/git/trees/f3790038b6c9c2d7e5ebbb4609997468fadf3e85?recursive=1)
returned 1,602 entries with `truncated: false`.

The machine-readable selection manifest is
[`official-release-manifest.json`](../work/records/idta-smt-catalog-20261021/official-release-manifest.json).
It selects the highest numeric release directory **within each published
family**, excluding example/sample payloads and separating explicitly marked
AAS 3.1 variants. Result: **65 families, 66 main JSON artifacts, 66 main AASX
artifacts**, plus 72 alternate AAS 3.1 artifact paths. Time Series Data has two
intentional main variants, with and without operations. Counts describe source
files, not successfully parsed Submodels. All published JSON paths in this
pinned tree have numeric release directories; none were excluded for lacking
one. Provision of 3D Models is included at release 1.0.2.

## Hosted repository API and downloads

The [hosted website](https://smt-repo.admin-shell-io.com/) is a JavaScript app.
Its [served frontend bundle](https://smt-repo.admin-shell-io.com/static/frontend/smt-repo-app.js)
contains these GET paths, verified live:

| Purpose | URL / representation |
| --- | --- |
| Submodel inventory | [`/api/v3.0/submodels`](https://smt-repo.admin-shell-io.com/api/v3.0/submodels): object with `result` and `paging_metadata` |
| Concept descriptions | [`/api/v3.0/concept-descriptions`](https://smt-repo.admin-shell-io.com/api/v3.0/concept-descriptions): object with `result` |
| One Submodel | `/api/v3.0/submodels/{Base64URL-encoded complete identifier}`: one Submodel object |
| Original JSON download | `/api/published-file?path=aas-json%2F{URL-encoded filename}`: full AAS Environment JSON |
| Original AASX download | `/api/published-file?path={URL-encoded filename}`: binary AASX |

The inventory returned 66 Submodels: **62 Templates and four Instances**,
confirmed by counting the preserved response
`work/temp/idta-discovery/submodels.json` (not by inferring kind from names).
The Instances include documentation and asset-identification examples; importing
the entire inventory as templates would be incorrect. The concept-description
route returned 2,846 entries. No released/draft selector or separate release
manifest appeared in the frontend's repository calls. Responses observed here
do not carry a reliable publication-status field.

Verified download examples:

- [Battery Technical Data JSON](https://smt-repo.admin-shell-io.com/api/published-file?path=aas-json%2FIDTA%2002035-4_DBP-Part-4_TechnicalData.json),
  HTTP 200, 144,142 bytes, SHA-256
  `a90774b959c766efe596243c39934df266ee34ce1132ba85f4b382efff842cb0`.
- [Battery Technical Data AASX](https://smt-repo.admin-shell-io.com/api/published-file?path=IDTA%2002035-4_DBP-Part-4_TechnicalData.aasx),
  HTTP 200, 11,280 bytes, SHA-256
  `e193e00f3b17eabec0f8f2386ca6d27e0c6b6a9fd749cb9037e429c5ffe88dd7`.

JSON downloads include `assetAdministrationShells`, `submodels`, and
`conceptDescriptions`. Preserve the original bytes and provenance; assemble a
new catalog from the intended `kind: Template` Submodels rather than importing
the supplied example shells as production assets.

## Why the website alone does not establish the newest release

The hosted download mapping and root README table lag behind the actual
published tree. The pinned tree contains these newer release folders:

| Family | Published folder version | Official evidence |
| --- | --- | --- |
| Generic Technical Data | 2.0.2 | [Release README](https://github.com/admin-shell-io/submodel-templates/blob/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/published/Technical_Data/2/0/2/README.md) |
| Industrial Digital Nameplate | 3.0.2 | [Release directory](https://github.com/admin-shell-io/submodel-templates/tree/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/published/Digital%20nameplate/3/0/2) |
| Battery Digital Nameplate | 1.1 | [Release README](https://github.com/admin-shell-io/submodel-templates/blob/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/published/Digital%20Battery%20Passport/1_Digital%20Nameplate/1/1/README.md) |
| Battery Technical Data | 1.0.2 | [Release README](https://github.com/admin-shell-io/submodel-templates/blob/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/published/Digital%20Battery%20Passport/4_Technical%20Data/1/0/2/README.md) |
| Asset Interfaces Description | 1.2 | [Release directory](https://github.com/admin-shell-io/submodel-templates/tree/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/published/Asset%20Interfaces%20Description/1/2) |

These are **artifact release versions**. `administration.version` and
`administration.revision` can omit the bug-fix component. Preserve both the
published directory version and the actual model administration metadata;
never manufacture a model version from a download filename.

Battery Material Composition, Product Condition, and Circularity are official
published families even where their IDs use `urn:samm:`. An unfamiliar ID scheme
does not establish that a template is custom. The existing local `Relationship`
template has no corresponding published family identified in this tree; retain
its backup rather than implying an official replacement exists.

## Compatibility and redistribution boundaries

The [BaSyx SDK specification table](https://github.com/eclipse-basyx/basyx-python-sdk#specification-compliance)
states that SDK package versions and supported AAS specification versions are
independent. Its FAQ advises checking the exact model version and schema when
strict parsing fails. Latest templates include explicit AAS 3.1 alternatives;
record which representation was tested. Do not interpret a repository HTTP 200
or a permissive JSON decode as proof that the full template parsed losslessly.

The upstream [license](https://github.com/admin-shell-io/submodel-templates/blob/f3790038b6c9c2d7e5ebbb4609997468fadf3e85/LICENSE.txt)
is CC BY 4.0. Preserve upstream attribution, the license link, and a record of
local changes when redistributing these artifacts. The A4S project's license
does not replace the upstream template license. Keep provenance for embedded
third-party material and do not infer rights to unrelated external dictionaries
or supplementary documents merely from their references.
