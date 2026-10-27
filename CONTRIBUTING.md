# Contributing

Start with an issue describing the concrete research workflow and the before/after behavior. Small fixes can go directly to a pull request.

Use Python 3.9+ and Node.js 20+ for tests. The browser app has no package install or bundling step.

```sh
python3 -m unittest discover -s tests
node --test web/tests/*.test.js
```

Keep changes focused. Add tests for durable record boundaries, provenance, permissions and meaningful behavior. Include desktop screenshots for visible changes, using synthetic data only. Never include a research database, personal server address, token or actual experiment material in a contribution.

Read [AGENTS.md](AGENTS.md) and [CONTRACT.md](CONTRACT.md) before changing record semantics. UI selections must not modify source identity. Reports must remain reproducible when new evidence arrives.
