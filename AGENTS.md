# Working on Research Workflow Studio

Keep project context, research questions, implementation identity and evidence separate. An exploration may produce insight without proposing a new method.

## Contract-first development

1. Read the project foundation, current research question and exact referenced records.
2. Search for a reusable specification and implementation before creating one.
3. Save a block specification describing purpose, inputs, output semantics, configuration, dependencies and acceptance checks. Mark it ready when agreed.
   Link its exact revision (or an existing implementation) from the relevant research using `implementationLinks` with implementation/control/diagnostic role. A purpose declaration is not an execution fact; never invent a run merely to link research and code.
4. Implement against that frozen specification. Put case inputs, task instructions and ordinary parameters in external configuration. A different case is not a new implementation version.
5. Verify the implementation with appropriate development tools. Record actual results; never label submitted evidence as independent verification.
6. Register the specification revision, repository, existing Git commit, module path, entrypoint and check evidence. Registration does not execute anything.
7. Record selected cases, actual configuration and produced artifacts. Preserve final images, predicted clean images, velocity fields, metric tables and derived analysis as distinct semantics.
8. Save the comparison's exact selection. An analysis states observations, interpretation, scope and limitations. A report pins those inputs and its renderer identity when one exists.

MCP has model authority. It may propose project-foundation changes and provenance corrections; human approval is a separate operation. Do not bypass that boundary with database writes or browser automation. Explicit user authorization for a reviewed migration is still required outside normal model operations.

Preserve immutable production facts and old report snapshots. Corrections are audited overlays. Never invent a producer to fill a missing field, silently choose the latest duplicate, or equate matching case labels across projects with the same input.

An algorithm improvement keeps its own code identity and explicit parent references; do not overwrite the original method. One implementation may support multiple configuration modes in the same run, with actual settings on each artifact. Comparison method groups are explicit exact-artifact selections, independent of producing code and run. They do not prove method equivalence; zero control, matching labels, and code ancestry alone never establish native behavior. See `docs/code-result-reuse.md`.

Inference owns generation and necessary process records. Derived computations and visualizations used only for diagnosis, without affecting generation decisions, belong in reusable analysis modules. A clean prediction used in a FlowAlign pullback update is inference; endpoint extrapolation, differences and PCA computed from saved state/velocity/time are analysis. Both may share pure functions. Analysis may explicitly decode saved latents for visualization, but must not resample or query the generating model for new velocities while claiming offline analysis. Evaluation scores by a fixed protocol; reports organize existing evidence.

Code may declare exact `source.historicalArtifactRefs`, a `source.historicalReuseNote`, and optional exact `source.legacyCodeRefs`. These are historical reference material, not outputs of the refactored implementation or evidence of equivalence. Keep original artifact producers and run code references. Show historical material separately with “重构一致性未验证”; missing exact versions remain missing. The code canvas defaults to hiding external codes loaded only through historical provenance when this project has its own contracted code. Keep external implementations explicitly declared by the current research, including exact specification bindings, visible for every role; the show/hide control counts only collapsible historical sources. Preserve direct provenance navigation. Legacy projects keep their existing default.

## Development

- Runtime uses Python standard library and a vanilla JavaScript desktop UI. Avoid adding a build system or remote dependency without a concrete need.
- All durable writes go through `Store.call`. Use `expectedRevision` and a stable `requestId` for exact retries.
- Keep private databases, real research data, credentials and machine-specific paths out of commits.
- Run `python3 -m unittest discover -s tests` and `node --test web/tests/*.test.js`.
- Scaffolding and static checks do not run research. `tools/check_block.py --execute` is an explicit local execution request; use supplied synthetic fixtures for software tests.
- Do not compute file hashes or run model experiments as part of ordinary verification.
