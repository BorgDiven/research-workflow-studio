# A complete workflow on synthetic signals

Run all four template roles locally with Python 3.10+ and no third-party packages, model, GPU, network or private dataset:

```sh
python3 examples/run_pipeline.py --destination ./synthetic-example
```

The destination must be new. The command creates four independent code blocks, checks each with two single-case requests plus their batch, then connects their output JSON files:

```text
Explicit cases and settings
          │
          ▼
Inference: synthetic signal transform
          ├── final-output series ───┬── Analysis: descriptive table ──┐
          │                         ├── Evaluation: reference error ──┤
          └── intermediate-state    │                                 ▼
              diagnostic series     └─────────────────── Report: selected evidence
```

`pipeline-manifest.json` links the actual outputs. Every artifact retains its sample identity, producing request, settings, semantic role and exact input IDs. Analysis and evaluation read the saved final series. Reports compose these existing results and copy the selected evidence into a snapshot; they do not recompute scores. Each report output manifest points to a Markdown file beside it. Missing references produce an explicit missing status, never a zero score.

Use your own JSON request with `--input request.json`. It has `datasetId`, `cases` (each with `sampleId`, `task`, `input.values`, and optional `referenceValues`), and `config` (`scale`, `offset`, `diagnosticSteps`). Changing cases or settings does not create a new code implementation. The supplied examples use numeric signals to demonstrate the interface; adapting a real model requires its own reviewed method contract and tests.

The example makes no MCP calls and creates no RWS project. For RWS registration, first save each `contract.json` object's `spec`, then pin the resulting ready spec revision when registering code. Map the portable manifest IDs to exact RWS dataset/artifact/run references; do not paste local `inputIds` as if they were database references. The per-template READMEs describe that mapping.


## Current MCP request examples

[Process metrics](process-metrics.json) and [controlled operations](controlled-operations.json) contain fictional API examples for 0.4. They are descriptive request bundles, not an automatic script. Register the prerequisite project/specification/code/run or resource references first, replace the example IDs and expected revision with actual values, and submit only the explicitly selected operation. They contain no approval or CLI execution step.

The existing four-role pipeline above is unchanged. A separate [training template](../templates/training/README.md) demonstrates synthetic optimization and its loss/log/checkpoint outputs; it is not silently inserted into the inference/evaluation pipeline.
