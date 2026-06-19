# Change Management

This document records changes, observations, learnings, and remediations for the
`harness-rsi` experiment. The point is not to pretend each iteration is correct.
The point is to preserve what each iteration taught us.

## Change Template

Each meaningful change should record:

- ID
- date
- files changed
- hypothesis
- change made
- validation run
- observation
- learning
- remediation or next action

## CM-0001: Minimal CLI Skeleton

- Date: 2026-06-15
- Files changed: `src/harness_rsi/*`, `tests/test_harness.py`, `README.md`
- Hypothesis: a raw filesystem-native CLI is enough to test the harness loop
  before adopting an agent framework.
- Change made: added `init`, `run`, `improve`, `promote`, and `reject`.
- Validation run: `pytest`, `ruff check .`, `harness-rsi run --mock`.
- Observation: the mock loop proves the artifact flow works, but it does not yet
  prove harness-level improvement.
- Learning: traces, proposals, and explicit promotion are the minimum viable
  substrate.
- Remediation: add versioned harnesses, splits, and gates before treating any
  candidate as an improvement.

## CM-0002: PR-First Workflow

- Date: 2026-06-15
- Files changed: `README.md`
- Hypothesis: `main` should remain stable while experimental harness changes move
  through PRs.
- Change made: documented `dev` and feature-branch workflow.
- Validation run: `pytest`, `ruff check .`, `git diff --check`.
- Observation: this gives a lightweight human approval layer.
- Learning: change management matters because harness promotion and repo
  promotion are structurally similar.
- Remediation: keep future increments on PR branches unless explicitly approved
  for `main`.

## CM-0003: Benchmark And Gate Spine

- Date: 2026-06-18
- Files changed: `src/harness_rsi/benchmarks.py`,
  `src/harness_rsi/harness.py`, `src/harness_rsi/cli.py`,
  `src/harness_rsi/paths.py`, `docs/evaluation-architecture.md`,
  `docs/change-management.md`
- Hypothesis: harness-level RSI needs explicit train, heldout, and regression
  environments before external benchmarks are useful.
- Change made: added a synthetic benchmark layout, benchmark run/compare/gate
  commands, run metadata, sub-second run IDs, per-task comparison, and same-model
  comparison enforcement.
- Validation run: `pytest` reported 9 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke test ran `H0` and copied `H1` on the
  synthetic heldout split, then compared and gated both a permissive policy and
  a strict improvement policy.
- Observation: the first benchmark layer revealed three immediate failure modes:
  run ID collisions, invalid ad hoc JSONL serialization, and comparisons that
  could accidentally compare different models. The first CLI smoke test also
  revealed that repeated gate policies for the same candidate could overwrite
  the previous gate artifact.
- Learning: evaluation infrastructure is itself a harness component; if it is
  weak, Hn+1 can appear better without actually being better.
- Remediation: add tests for benchmark initialization, metadata capture,
  comparison invariants, gate pass/fail cases, model mismatch rejection,
  benchmark/split mismatch rejection, and unique gate artifact names.
  Implemented unique gate names with a decision timestamp after the smoke test
  exposed overwrite risk.

## CM-0004: Version-Aware Harness Promotion

- Date: 2026-06-18
- Files changed: `src/harness_rsi/versions.py`, `src/harness_rsi/cli.py`,
  `tests/test_harness.py`, `README.md`, `docs/evaluation-architecture.md`,
  `docs/change-management.md`
- Hypothesis: harness-level improvement needs immutable-ish Hn artifacts with
  lineage, not direct mutation of the current harness config.
- Change made: added `harness-rsi harness promote`, `harness-rsi harness list`,
  and a versioning module that creates `H1` from `H0` only after a promote gate.
  The new version records proposal/gate/run lineage and rejects rejected gates,
  parent mismatch, candidate mismatch, existing-version overwrites, and model
  changes.
- Validation run: `pytest` reported 17 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke test created `H2` from `H0` using a
  promote gate and proposal artifact, then listed harness versions.
- Observation: the legacy `promote` command still exists for proposal-only
  mutation of `.rsi/harness.json`; benchmark-grade promotion now has a separate
  safer path. The smoke test also surfaced an old local manual copy where
  `.rsi/harnesses/H1.json` declared `id: H0`, so `harness list` now exposes
  filename/declared-ID mismatches.
- Learning: version creation is itself part of the evaluation harness. If Hn+1
  is not an explicit artifact, the experiment cannot be replayed or audited.
- Remediation: next increment should either deprecate legacy `promote` for
  benchmark work or make it require a gate when targeting versioned harnesses.
  A later cleanup command should repair or quarantine malformed local harness
  files instead of only listing the mismatch.
