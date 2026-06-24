# Tau2-Bench Retail Smoke Frozen Export

This directory stores a tiny read-only fixture derived from public
`sierra-research/tau2-bench` retail task identities. It is intentionally not a
tau2-bench runner and does not run a user simulator, tool environment, policy
checker, or database mutation loop.

`tasks.json` preserves three real tau2-bench retail task IDs from
`data/tau2/domains/retail/tasks.json`. `split-map.json` maps those source rows
into local `train`/`heldout`/`regression` roles so the harness can exercise
import, materialization, adapter reporting, and a no-promote stability smoke
with deterministic identity-only local evaluators.

The local evaluator checks fixture identity only. Full tau2-bench simulator
execution remains out of scope for this fixture.
