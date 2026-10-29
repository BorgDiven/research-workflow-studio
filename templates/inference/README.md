# Synthetic signal transform

A runnable Python standard-library example; all signals are synthetic and are not research results.

`input.values` → apply `scale * value + offset` → a final series plus optional interpolated diagnostic series. Diagnostics are observations of this synthetic transform, not new method versions. `diagnosticSteps=0` emits only the final series.

## Start from a contract

From the Research Workflow Studio repository:

```sh
python3 tools/scaffold.py --kind inference --destination ./my-inference
python3 tools/check_block.py ./my-inference
python3 tools/check_block.py ./my-inference --execute --output ./my-inference/check-evidence.json
python3 ./my-inference/block.py --input ./my-inference/request.json --output ./my-inference/output.json
```

The static check does not execute the implementation. `--execute` explicitly imports and runs local Python code in a subprocess with a timeout; it is not a security sandbox. Use it on the supplied CPU examples or code you have reviewed. RWS MCP only records supplied check evidence and never runs these commands.

Edit `contract.json` first: purpose, typed ports, parameter schema and acceptance checks describe the reusable method. Then implement `block.py:run(request)`. Edit `request.json` to select cases and parameters; `fixtures.json` contains two different cases and explicit expected outputs for regression checks. The checker tests both separately and as a batch. It does not prove arbitrary-input correctness or scientific quality.

## Boundary and provenance

Change the implementation only when the reusable method changes. Sample names, data, parameter values and diagnostic selection belong to a request. These synthetic intermediate signals do not represent model latents, clean predictions or actual inference quality.

Inference owns generation and necessary process records. A clean prediction used to choose a FlowAlign pullback update belongs here. Derived computations and visualizations that do not affect generation decisions should be reusable analysis modules; they may share pure functions with inference. Analysis can read saved state/velocity/time for endpoint extrapolation, differences or PCA and explicitly decode saved latents for visualization, but must not resample or query the generating model for new velocities while claiming offline analysis. Evaluation scores by a fixed protocol; reports organize existing evidence.

Requests carry `requestId`, `datasetId`, `cases`, `config`, and exact `inputs`. Outputs carry stable artifact IDs, sample/task/dataset identity, semantic role, actual settings, producing request, input IDs and explicit sample status. A run is an execution fact; it is not a new method or a new research hypothesis. Keep files and source IDs when reusing evidence across hypotheses or reports.

When registering a refactored implementation, `source.historicalArtifactRefs` can list exact historical artifact references with a `source.historicalReuseNote`; optional `source.legacyCodeRefs` links original code. The UI lists these as “历史复用材料 · 重构一致性未验证”, retaining their real producers and excluding them from this version's output/execution counts. This association does not verify equivalence or create a new execution.

This portable JSON manifest is not a raw MCP payload. Save `contract.spec` via `rws_spec_save`; register code with its exact ready `specRef` and checker evidence. Register the input dataset/artifacts and map local IDs to exact RWS references. Map producer to `producerRef`, `inputIds` to `inputRefs`, and case identity to `datasetRef`/`sampleId`/`taskKey`. Use a real commit and repository identity when registering an implementation; a fixture receipt with no Git commit must not be presented as a committed version. For reports, use the saved Markdown and exact selected evidence in `rws_report_create_revision`.
