# Stored signal reference evaluation

A runnable Python standard-library example; all signals are synthetic and are not research results.

A stored final series + the same sample’s explicit `referenceValues` → mean absolute error over corresponding positions → a metric with protocol definition and a reference snapshot. The protocol fixes units, direction, preprocessing, aggregation and missing-data policy.

## Start from a contract

From the Research Workflow Studio repository:

```sh
python3 tools/scaffold.py --kind evaluation --destination ./my-evaluation
python3 tools/check_block.py ./my-evaluation
python3 tools/check_block.py ./my-evaluation --execute --output ./my-evaluation/check-evidence.json
python3 ./my-evaluation/block.py --input ./my-evaluation/request.json --output ./my-evaluation/output.json
```

The static check does not execute the implementation. `--execute` explicitly imports and runs local Python code in a subprocess with a timeout; it is not a security sandbox. Use it on the supplied CPU examples or code you have reviewed. RWS MCP only records supplied check evidence and never runs these commands.

Edit `contract.json` first: purpose, typed ports, parameter schema and acceptance checks describe the reusable method. Then implement `block.py:run(request)`. Edit `request.json` to select cases and parameters; `fixtures.json` contains two different cases and explicit expected outputs for regression checks. The checker tests both separately and as a batch. It does not prove arbitrary-input correctness or scientific quality.

## Boundary and provenance

Predictions and references must have equal nonzero length. No resizing, alignment, normalization or missing-to-zero conversion is hidden here. Missing samples appear in sampleStatuses and coverage. A real image metric requires a new explicit protocol (including color space, range and pairing), not a renamed synthetic score.

Requests carry `requestId`, `datasetId`, `cases`, `config`, and exact `inputs`. Outputs carry stable artifact IDs, sample/task/dataset identity, semantic role, actual settings, producing request, input IDs and explicit sample status. A run is an execution fact; it is not a new method or a new research hypothesis. Keep files and source IDs when reusing evidence across hypotheses or reports.

This portable JSON manifest is not a raw MCP payload. Save `contract.spec` via `rws_spec_save`; register code with its exact ready `specRef` and checker evidence. Register the input dataset/artifacts and map local IDs to exact RWS references. Map producer to `producerRef`, `inputIds` to `inputRefs`, and case identity to `datasetRef`/`sampleId`/`taskKey`. Use a real commit and repository identity when registering an implementation; a fixture receipt with no Git commit must not be presented as a committed version. For reports, use the saved Markdown and exact selected evidence in `rws_report_create_revision`.
