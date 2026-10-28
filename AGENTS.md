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

## Development

- Runtime uses Python standard library and a vanilla JavaScript desktop UI. Avoid adding a build system or remote dependency without a concrete need.
- All durable writes go through `Store.call`. Use `expectedRevision` and a stable `requestId` for exact retries.
- Keep private databases, real research data, credentials and machine-specific paths out of commits.
- Run `python3 -m unittest discover -s tests` and `node --test web/tests/*.test.js`.
- Scaffolding and static checks do not run research. `tools/check_block.py --execute` is an explicit local execution request; use supplied synthetic fixtures for software tests.
- Do not compute file hashes or run model experiments as part of ordinary verification.
