# Synthetic training block

Fit a linear model to each explicitly supplied numeric dataset using ordinary
Python and gradient descent. This CPU teaching fixture does not train a neural
network, download data or contact a server. Cases contain `input.pairs` of
`[x, target]`; case names never select a different algorithm.

The fixed specification declares three outputs for each dataset:

- a loss series including the initial loss and each optimization step;
- a JSON checkpoint containing the fitted weight, bias and step count;
- a JSONL training log containing `metricId`, step coordinate `x`, `value`,
  `sampleId` and stable `eventId`, ready for the batched metrics collector.

`run(request)` returns these records without filesystem effects. The command line
materializes checkpoint and log files next to the output manifest. Existing
outputs are never overwritten. The batch fits independent datasets and preserves
the same result as running each dataset separately; it does not merge them into
one larger training dataset.

After scaffolding, inspect `contract.json`, then explicitly run:

```sh
python block.py --input request.json --output results/output.json
```

Change `learningRate`, `epochs` and the numeric pairs in the request. A non-finite
optimization result raises an error rather than recording a completed training
result. Training completion does not establish a research conclusion.

The specification declares the sample-scoped `loss` process metric. After an
actual Studio run has been registered with that specification, ingest a selected
log using `tools/track_metrics.py --input` with its exact project, run ID and
revision. A spool retry keeps the same event IDs. The template itself never
creates a Studio run, changes its status or connects to an external service.
