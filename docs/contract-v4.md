# Experiment tracking and controlled execution

This increment retains project foundations, research questions, reusable code,
actual executions and immutable evidence as separate identities. It extends the
workbench to training and process observations without adding another research
stage or turning a completed program into a scientific conclusion.

## Process observations

A code specification may declare process metrics: identity, unit, horizontal
axis (step, epoch or time), run/sample scope and optional dataset split or fixed
evaluation protocol. Training is a supported code/specification kind alongside
inference, evaluation, analysis and report generation.

Scripts submit bounded batches against an exact run reference. Identical points
can be retried; conflicting values at the same run/metric/split/sample/coordinate
are rejected. Missing values need an explicit reason and are never replaced by
zero. Process recording does not require an LLM call for every training step.

Curves can only be automatically grouped when their metric definition, unit,
axis, data scope and protocol/specification match. Separate runs remain visible;
the interface does not average repetitions, reset counters or missing values.
Dataset-level metrics do not acquire invented sample identities merely to fit
an image grid.

Live observations remain appendable. Saving evidence freezes selected metrics,
coordinate range and the required last included sequence from the preceding query into an immutable artifact.
Query returns throughSequence; reuse it on later pages and supply it when freezing. Snapshots over 5000 points are rejected, never silently truncated. Later points cannot alter existing artifacts or reports. A process snapshot
packages existing observations; it is not another model execution or an
independent evaluation. Code specifications govern model outputs; the service
identifies its own observation-snapshot packaging explicitly.

## Repository and execution resources

- A server describes a local host or an existing SSH alias and its workspace
  root. Credentials remain in the operator's existing SSH/Git configuration.
- A repository binds a server, checkout path and declared remote identity.
- An environment binds that repository and server to a working directory and
  Python executable. It describes an existing environment; registration does
  not install dependencies or provision a machine.
- A run can pin the repository and environment used for its implementation.
  Code identity remains the exact commit, module/entrypoint and specification.

Resources are project records with exact revisions. Updating a resource does
not silently redirect an already reviewed operation or a historical run.
Before starting a job, the runner checks the registered checkout against the
fixed implementation commit. A mismatch is an actionable error, not permission
to reset, fetch, switch or overwrite the checkout.

## Reviewed operations

Operations record a concrete action, arguments and exact target references.
Git actions are inspection, creation of a branch, explicitly scoped commit,
tag and non-force push. Push requires a fixed remoteUrl and a unique matching remote; local bare-remote paths must stay inside workspaceRoot. Task actions are start, status, bounded logs and stop;
environment inspection is read-only. There is no arbitrary-shell MCP endpoint.

MCP can prepare and inspect requests. Mutating operations require human approval
of the exact plan. An explicitly invoked command-line runner claims that request
atomically, performs the external action outside the database transaction and
records its observation. Read-only operations can be claimed without a separate
approval step. Approval does not itself launch a program.

Claim and result updates pass through the shared Store with runner authority;
they are not advertised MCP tools or accepted HTTP operations. Duplicate claims
must not duplicate launches or pushes. An interrupted or uncertain external
action stays unknown until inspected; it is never automatically relaunched.
Job identity, log locations and exit observations are distinct from the research
run and its scientific interpretation.

## Desktop workflow

The three primary views remain research, code/execution, and outputs/comparison.
Project resources open from one compact repository/environment entry. Training
appears in code/execution when present. Outputs use an image/material grid,
curve overlays or metric tables according to the material being inspected.
Operator-only controls expose their actual state: prepared, awaiting review,
approved/waiting for runner, running, completed, failed or unknown.

The public demonstration contains fictional resources and observations only.
It cannot approve requests, start jobs, write repositories or contact an
experimental backend.

## Verification boundary

Acceptance uses isolated SQLite databases, standard-library numeric fixtures,
temporary Git repositories with a local bare remote, mocked SSH and a fixture
MLflow HTTP service. No real research server, model experiment, research
repository publication or file-hash audit is part of the software verification.
Actual remote transport and an existing MLflow installation still require their
own explicitly selected integration check.


## Explicit MLflow import

The source command tools/track_metrics.py reads only explicitly selected MLflow HTTP metric history. It requires a URL, external run ID and metric mapping. Supply a declared split with --mlflow-split and import different splits separately. It supports run-scoped metrics only because this history has no sampleId; sample-scoped data uses explicit JSONL sampleId. It does not install or discover MLflow, control its jobs, import lifecycle state or infer conclusions.
