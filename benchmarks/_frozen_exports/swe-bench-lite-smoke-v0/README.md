# SWE-bench Lite Smoke Frozen Export

This directory stores a tiny read-only fixture derived from public
`princeton-nlp/SWE-bench_Lite` metadata. It is intentionally not a full
SWE-bench runner and does not grade patches.

`tasks.json` preserves three real SWE-bench Lite instance IDs from the public
test split. `split-map.json` maps those public rows into local
`train`/`heldout`/`regression` roles so the harness can exercise the full import,
materialize, adapter-report, and stability-smoke path with deterministic local
evaluators.

The local evaluator checks fixture identity only. Full Docker-based SWE-bench
patch grading remains out of scope for this fixture.
