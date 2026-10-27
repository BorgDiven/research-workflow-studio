# Evidence composition report

A runnable Python standard-library example; all signals are synthetic and are not research results.

Selected stored artifacts + optional per-case note → a Markdown document for each selected sample. It embeds existing values and their source IDs, and snapshots the selected evidence. It neither invents conclusions nor calculates additional metrics.

## Start from a contract

From the Research Workflow Studio repository:

```sh
python3 tools/scaffold.py --kind report --destination ./my-report
python3 tools/check_block.py ./my-report
python3 tools/check_block.py ./my-report --execute --output ./my-report/check-evidence.json
python3 ./my-report/block.py --input ./my-report/request.json --output ./my-report/output.json
```

The static check does not execute the implementation. `--execute` explicitly imports and runs local Python code in a subprocess with a timeout; it is not a security sandbox. Use it on the supplied CPU examples or code you have reviewed. RWS MCP only records supplied check evidence and never runs these commands.

Edit `contract.json` first: purpose, typed ports, parameter schema and acceptance checks describe the reusable method. Then implement `block.py:run(request)`. Edit `request.json` to select cases and parameters; `fixtures.json` contains two different cases and explicit expected outputs for regression checks. The checker tests both separately and as a batch. It does not prove arbitrary-input correctness or scientific quality.

## Boundary and provenance

The CLI writes document files beside the output manifest. A direct run(request) call returns Markdown and an unmaterialized attachment; the caller must persist it before marking it available. RWS reports can reuse these snapshots or compose them into a larger final report; report generation code belongs in the report code lane.

Requests carry `requestId`, `datasetId`, `cases`, `config`, and exact `inputs`. Outputs carry stable artifact IDs, sample/task/dataset identity, semantic role, actual settings, producing request, input IDs and explicit sample status. A run is an execution fact; it is not a new method or a new research hypothesis. Keep files and source IDs when reusing evidence across hypotheses or reports.

This portable JSON manifest is not a raw MCP payload. Save `contract.spec` via `rws_spec_save`; register code with its exact ready `specRef` and checker evidence. Register the input dataset/artifacts and map local IDs to exact RWS references. Map producer to `producerRef`, `inputIds` to `inputRefs`, and case identity to `datasetRef`/`sampleId`/`taskKey`. Use a real commit and repository identity when registering an implementation; a fixture receipt with no Git commit must not be presented as a committed version. For reports, use the saved Markdown and exact selected evidence in `rws_report_create_revision`.
