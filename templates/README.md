# Reusable development blocks

Define the reusable method before writing its implementation. Select cases and parameter values through input JSON; keep the same implementation when only those inputs change. These four templates run entirely on synthetic numeric signals using Python's standard library. They do not download models, start a GPU job or establish scientific results.

| Role | Input | Output | Boundary |
| --- | --- | --- | --- |
| [Inference](inference/README.md) | Selected numeric cases and affine-transform settings | Final series; optional intermediate diagnostic series | Produces data. A diagnostic output is an observation, not a separate method version. |
| [Analysis](analysis/README.md) | Exact stored final-series artifacts | Descriptive-statistics table | Reads existing outputs; does not invoke inference. |
| [Evaluation](evaluation/README.md) | Stored final series and corresponding reference values | Per-case mean absolute error, protocol definition and coverage | Records units, direction, alignment, aggregation and missing-data behavior. |
| [Report](report/README.md) | Selected final series, metric or analysis-table artifacts; optional supplied interpretation | Markdown documents and an evidence snapshot | Composes existing evidence; does not silently compute new metrics or conclusions. |

## Create, inspect, then run

From the repository root:

```sh
python3 tools/scaffold.py --kind inference --destination .local/my-method --title "My method"
python3 tools/check_block.py .local/my-method --output .local/my-method-static.json
python3 tools/check_block.py .local/my-method --execute --output .local/my-method-executed.json
python3 .local/my-method/block.py --input .local/my-method/request.json --output .local/my-method/output.json
```

The destination and each output file must be new. `--kind` accepts `inference`, `analysis`, `evaluation`, or `report`. Each generated directory contains:

- `contract.json`: method purpose, typed inputs/outputs, configuration schema, dependencies, acceptance checks and entrypoint.
- `block.py`: the reusable `run(request)` implementation.
- `_runtime.py`: a small JSON boundary and output-file helper.
- `request.json`: a runnable input selection and configuration.
- `fixtures.json`: two different cases and explicit expected results.
- `README.md`: the role's precise behavior and integration boundary.

The checker **does not execute code by default**. `--execute` explicitly runs the local implementation on each of the two fixture cases separately and then on their combined batch. It checks coverage, input immutability, declared output types, exact input IDs, expected values and per-case agreement between single and batch requests. It uses a subprocess with a timeout, **not a security sandbox**. Run it only for code you have reviewed. MCP never invokes it automatically.

The evidence receipt records which checks actually ran. Unknown custom acceptance checks remain skipped; static checks cannot be presented as execution validation. A passing fixture check covers these inputs only. It does not prove correctness for arbitrary cases or the quality of a model. The receipt records an existing Git identity when available; untracked or modified code is not marked ready for committed implementation registration. No file-hash verification is part of this workflow.

## Portable JSON boundary

An input request identifies the dataset, each selected sample and its task. For example, the inference block accepts:

```json
{
  "requestId": "example-transform-1",
  "datasetId": "synthetic-signals-v1",
  "cases": [
    {"sampleId": "sample-01", "task": "inspect-signal", "input": {"values": [1, 2, 3]}}
  ],
  "config": {"scale": 2, "offset": 0, "diagnosticSteps": 1},
  "inputs": []
}
```

Downstream requests place exact previously saved artifacts in `inputs`. A selected input's dataset, sample and task identities must agree with the request. Reusing evidence does not rename its producer. Analysis and evaluation reject ambiguous duplicate final outputs; choose the exact one you intend to use.

Every output manifest has this structure:

```json
{
  "schemaVersion": "rws.block-output/v1",
  "requestId": "example-transform-1",
  "synthetic": true,
  "artifacts": [],
  "sampleStatuses": [{"sampleId": "sample-01", "status": "completed"}],
  "summary": {"selected": 1, "completed": 1, "missing": 0}
}
```

Each artifact contains `id`, `sampleId`, `caseIdentity` (dataset/sample/task), `kind`, `semantic`, actual `config`, `producer`, exact `inputIds`, and typed `content`. Diagnostics also carry an `observation` such as a step. The templates use series, tables, metrics and Markdown attachments; no synthetic score is labeled as image quality. Evaluation preserves missing coverage instead of inventing a zero. Report code retains selected evidence and supplied text; its CLI writes Markdown files beside the output manifest.

A method contract describes the algorithm and allowed inputs. An invocation describes which samples and settings were used. An artifact describes what was actually produced. A comparison or report selects those artifacts without changing these identities.

## Use with Research Workflow Studio

These portable files are **not raw MCP arguments**. The adapter or AI client should:

1. Save the `contract.json` object's `spec` through `rws_spec_save` and obtain its exact ready revision.
2. Register the reviewed implementation with that `specRef`, repository, fixed Git commit, module path, entrypoint, capabilities and supplied checker evidence. Do not label uncommitted files as an existing committed implementation.
3. Register the selected dataset and existing artifacts. Map local manifest IDs to exact RWS references.
4. Register execution facts using those references and the actual configuration. Map each artifact's producer to `producerRef`, `inputIds` to `inputRefs`, and case identity to `datasetRef`/`sampleId`/`taskKey`.
5. Register evaluations with their explicit protocol and coverage; register analyses and reports with the exact selected evidence. Use the saved Markdown for `rws_report_create_revision`.

Creating records through MCP does not launch code. Execution and scientific decisions remain under user direction. The tools above are source-checkout development commands; the optional installed web/MCP package does not install this scaffolding interface.

For an executable connection of all four roles, see [the synthetic pipeline example](../examples/README.md):

```sh
python3 examples/run_pipeline.py --destination .local/synthetic-example
```
