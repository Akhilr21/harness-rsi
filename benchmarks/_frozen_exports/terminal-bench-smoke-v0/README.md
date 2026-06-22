# Terminal-Bench Smoke Frozen Export

This directory stores a tiny read-only fixture derived from public
`harbor-framework/terminal-bench` task identities. It is intentionally not a
Terminal-Bench runner and does not execute terminal tasks, Docker containers, or
benchmark tests.

`tasks.json` preserves three real Terminal-Bench task directory identities from
`original-tasks/`. `split-map.json` maps those public rows into local
`train`/`heldout`/`regression` roles so the harness can exercise import,
materialization, adapter reporting, and a no-promote stability smoke with
deterministic identity-only local evaluators.

The local evaluator checks fixture identity only. Full Terminal-Bench execution
remains out of scope for this fixture.
