# Contract-first records and reusable evidence

Research Workflow Studio keeps a method's implementation separate from the cases it runs on. The model first reads the project context, looks for an existing implementation, and defines or reads the block contract. It then writes code against that contract outside MCP, records supplied check evidence, and registers the fixed implementation. Actual execution remains a separately authorized action in the user's conversation or local environment.

All MCP writes require `requestId`, `projectId`, and `expectedRevision`, except project creation. Replaying the same request returns its original result. References have `{projectId, type, id, version}`; omitted versions resolve once when saving. Historical versions remain readable. The generated `tools/list` schemas are the executable API specification.

## 1. Define the method before implementing it

`rws_spec_save` accepts `record` with these fields:

```json
{
  "title": "Image prediction with optional observation probes",
  "schemaVersion": 1,
  "kind": "inference",
  "status": "ready",
  "purpose": "Predict outputs for caller-selected cases and capture optional intermediate observations.",
  "inputs": [
    {"name": "images", "kind": "image", "semantic": "input-image", "required": true, "multiple": true}
  ],
  "outputs": [
    {"name": "outputs", "kind": "image", "semantic": "final-image"},
    {"name": "clean estimates", "kind": "image", "semantic": "clean-estimate", "required": false}
  ],
  "configSchema": {
    "type": "object",
    "properties": {"cfg": {"type": "number", "minimum": 0}},
    "required": ["cfg"],
    "additionalProperties": false
  },
  "dependencies": [],
  "acceptanceChecks": [
    {"id": "two-cases", "description": "A portable two-case fixture produces correctly identified outputs."}
  ],
  "capabilities": ["batch-output", "clean-estimate"]
}
```

`kind` is `inference`, `evaluation`, `analysis`, or `report`. `status` is `draft` or `ready`. Saving an existing `id` creates another spec revision, preserving the previous one. A ready contract needs outputs and acceptance checks. Drafts can have empty lists while the intended interface is being designed.

Each input/output descriptor requires `name` and `kind`; it may also contain `semantic`, `required`, `multiple`, and `description`. Names must be unique in each list. Input matching checks the referenced record's `kind` or reference `type`, and its semantic if specified. `required` defaults to true and `multiple` defaults to true. This supports a single method accepting a batch. Outputs are validated individually; the registry does not claim that every required output was produced merely because one artifact was registered.

`configSchema` supports `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`, `const`, `anyOf`, `oneOf`, `if`/`then`, `minProperties`, `minItems`, `maxItems`, `uniqueItems`, `minLength`, `pattern`, `minimum`, and `maximum`. `title`, `description`, `default`, and `$schema` are metadata. Defaults are not inserted. Unsupported validation keywords are rejected rather than ignored.

## 2. Register a fixed implementation, then reuse it

Use `rws_code_find` with `{projectId, query?, kind?, specRef?, limit?}` before creating another implementation. It returns `{items, total, limit, notice}`. `items` are exact record envelopes. Query searches title, description, capabilities, and entrypoint. The default limit is 50; the maximum is 200. To search another project, select its project ID; a found reference can be reused across projects.

`rws_code_register.record` retains the existing required `title`, `kind`, `version`, and `source`. A contracted implementation additionally requires:

| Field | Meaning |
| --- | --- |
| `specRef` | Exact ready contract revision; its kind must match the code kind. |
| `repository` | Repository identity supplied by the client. |
| `commit` | Fixed commit identifier supplied by the client; moving values such as `HEAD` or `main` are rejected. |
| `modulePath` | Implementation location inside the repository. |
| `entrypoint` | `module-or-path:callable`; registration does not import it. |
| `capabilities` | Same declared capabilities as the pinned contract. |
| `checkEvidence` | One `{checkId, status, evidence}` per acceptance check. |

Check status is `passed`, `failed`, or `skipped`. Evidence is a nonempty description or log reference. The server sets `validationOrigin: "supplied"` in the stored record. Do not send that generated field as an input. Failed/skipped checks remain explicit; registration is not independent verification or scientific acceptance.

The tuple `(repository, commit, modulePath, entrypoint)` identifies one contracted implementation within a project. Registering it again under a new title is rejected with `duplicate_identity` and the existing reference. A different case or configuration reuses that reference. Registered code cannot be edited. Legacy code records without contracts remain readable and valid, but cannot claim contracted validation.

## 3. Select cases on runs; identify outputs precisely

`rws_run_register.record` adds:

```json
{
  "sampleSelection": {
    "datasetRef": {"projectId": "example", "type": "dataset", "id": "cases", "version": 1},
    "sampleIds": ["case-01", "case-02"]
  },
  "purpose": "Explore behavior before choosing a method change."
}
```

`datasetRef` is optional. If supplied, each selected ID must belong to that immutable dataset version. Contracted inference runs require a nonempty sample selection. Their `config` must satisfy the pinned schema and their `inputRefs` must match declared input descriptors. An analysis experiment may use inference code to collect probes: the run's purpose explains the research intent, while the code kind describes what it computes. Case selection and purpose remain fixed once registered, along with actual code, configuration, input, and experiment bindings.

`rws_artifact_register.record` adds `semantic`, `observation`, `inputRefs`, `datasetRef`, and `taskKey`. These complement existing `sampleId`, `producerRef`, and actual per-output `config`:

- `semantic` describes the output meaning, for example `final-image`, `clean-estimate`, `velocity-field`, `diagnostic`, `metric`, `series`, `table`, or `attachment`. It is extensible; contracted outputs must match a declared kind/semantic pair.
- `observation` is `{step?, time?, label?}`. A clean estimate or velocity field from a contracted implementation must include an observation; these are not silently treated as final images.
- `inputRefs` identifies exact input records used by this output and must be drawn from its producer's inputs for contracted runs.
- `datasetRef` plus `sampleId` identifies the selected dataset case. `taskKey` can distinguish different edit instructions or tasks for the same sample.

A case comparison identity is `(exact datasetRef, sampleId, taskKey)`, falling back to `(source projectId, sampleId, taskKey)` when no dataset is supplied. An output without a sample ID must remain an isolated item rather than joining every other unidentified output.

One contracted run cannot register the same producer/case/task/semantic/observation/configuration identity twice. Another actual run may produce a repeated result; both exact references are retained. UI grouping does not delete or move those sources.

Each output's actual `config` is validated against the pinned contract. Valid sweep values may differ from the run's default configuration; malformed values or undeclared fields cannot enter comparison tables as if they were valid settings.

`rws_result_query` accepts `{projectId, sampleIds?, semantics?, codeRefs?, offset?, limit?}` and returns `{items, total, offset, limit}`. Its default limit is 100 and maximum is 200. Each item includes the exact artifact envelope and resolved `codeRef`. Pagination and filters never select a winning repeat automatically.

## 4. Separate a comparison from its interpretation and report

`rws_comparison_save` keeps exact `inputRefs`, `fixedConditions`, and `varyingConditions`. Optional `viewSpec` stores presentation choices:

```json
{
  "mode": "single",
  "sampleIds": ["case-01"],
  "semantics": ["clean-estimate"],
  "axis": "observation.step",
  "selectedValues": [1, 3, 7],
  "observation": {},
  "filters": {"caseKeys": [], "codeIds": [], "config": {}, "selections": {}},
  "repeats": "all"
}
```

Only `mode` is required, either `single` or `multi`. `filters` is application-owned JSON; selections still refer to the fixed input set. `repeats` can be explicitly `all` or `latest`; nothing defaults to `latest`. Missing cells and repeats need explicit handling by the viewer. A comparison is an evidence selection, not a scientific conclusion.

`rws_analysis_save` adds `comparisonRefs`, `scope: {sampleIds?, description?}`, and `coverage: {expected, observed, missingSampleIds?}`. Existing observations, interpretation, and limitations remain distinct. Coverage counts describe the declared analysis scope; they are not scores or proof of generalization. Observed cannot exceed expected, and named missing samples must be consistent with the stated scope. Analysis may be manual; code/run references are optional.

`rws_report_create_revision` adds `comparisonRefs`, `generatorCodeRef`, and `generatorRunRef`. A generator reference points to report-generation code; its run must match that code and have actual completed or partial work. A report may also be manually authored without those optional references. Reports snapshot exact transitive records, their relevant project foundations, and any approved source projections as they existed at creation. Later comparison edits or new results cannot rewrite old report contents.

## 5. Correct metadata without rewriting evidence

`rws_amendment_propose` accepts the normal write arguments and:

```json
{
  "record": {
    "title": "Correct a recovered output's source label",
    "targetRef": {"projectId": "example", "type": "artifact", "id": "output", "version": 1},
    "patch": {"title": "Method-level title", "semantic": "clean-estimate", "observation": {"step": 7}},
    "reason": "Original source documentation identifies this intermediate observation.",
    "evidenceRefs": []
  }
}
```

The target must be an exact version in the current project. The pending amendment records the already approved amendment versions used as its review base. Only a human can call `rws_amendment_apply` or `rws_amendment_dismiss`, with `{requestId, projectId, expectedRevision, amendmentRef}`. The amendment reference must be exact. A changed correction base rejects stale approval; the stale proposal can still be dismissed.

Supported patches are restricted by target record type: `title`, `description`, `parentRefs`, `source`, `provenance`, `producerRef`, `inputRefs`; artifact case/meaning fields `semantic`, `datasetRef`, `sampleId`, `taskKey`, `observation`; run `sampleSelection`, `purpose`, and `recoveredByRef`. Execution configuration, implementation identity, research judgment, and stage are not amendment fields. A recovery points from a failed/partial run to a different completed run with the same implementation and scope; it leaves the original failure status intact. Reports, evaluations, and specs cannot be amended through this interface.

Read envelopes always retain the original `record`. When approved corrections exist, they additionally expose `effectiveRecord` and exact `amendmentRefs`. Frontends use `effectiveRecord || record` for the current view and retain the raw record for audit. Old report snapshots do not get these later overlays. Approved/dismissed amendments receive a new revision and human attribution; the pending version remains readable.

The MCP client always acts as `model`, never as `human`. It can propose metadata corrections and foundation changes, but cannot approve them, advance stages, decide scientific validity, launch a program, or access arbitrary repository files.
