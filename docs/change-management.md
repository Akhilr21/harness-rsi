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

## Eval-Suite Change Expectations

Eval-suite changes are measurement changes. They should be reviewed with the same
care as harness code because they can change whether a candidate is promoted.

Every meaningful eval-suite change should record:

- task sources added, removed, or changed
- affected environments, failure families, and splits
- evaluator changes and any digest changes
- gate-policy changes and expected promotion impact
- validation commands and artifact paths
- migration or backfill plan for prior runs if old evidence is no longer
  comparable

Task data, evaluator definitions, suite version, and gate semantics should move
together. Once a candidate run exists, do not edit the tasks or evaluator
definitions used by that run in place. Create a new suite version instead.

PRs that change gate semantics should say so explicitly. PRs that only add
coverage should still explain the source and failure family of the new cases.

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

## CM-0005: Candidate Lifecycle Correction

- Date: 2026-06-18
- Files changed: `src/harness_rsi/versions.py`, `src/harness_rsi/cli.py`,
  `src/harness_rsi/harness.py`, `src/harness_rsi/benchmarks.py`,
  `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/change-management.md`
- Hypothesis: the prior version-aware flow was still inverted because it created
  `H1` after a gate, even though `H1` must exist before it can be evaluated.
- Change made: split the lifecycle into `harness create-candidate` and
  `harness promote`. Candidate creation writes `status: candidate` from a parent
  and proposal. Promotion mutates that existing candidate to `status: promoted`
  only after a promote gate.
- Validation run: `pytest` reported 19 passing tests; `ruff check .` passed;
  `git diff --check` passed.
- Observation: gates also need to prove that the evaluated candidate behavior is
  the same behavior being promoted. The run summary and gate comparison now
  include `harness_behavior_digest`, and promotion rejects missing or mismatched
  candidate digests.
- Learning: Hn+1 has two states, candidate and promoted. Treating candidate
  creation and promotion as one action hides the most important experimental
  boundary.
- Remediation: next increment should generate proposals from train runs and wire
  a full automated cycle: run train, propose candidate, run heldout/regression,
  gate, then promote or reject.

## CM-0006: Automated Experiment Cycle

- Date: 2026-06-18
- Files changed: `src/harness_rsi/cycle.py`, `src/harness_rsi/cli.py`,
  `src/harness_rsi/improve.py`, `src/harness_rsi/benchmarks.py`,
  `src/harness_rsi/versions.py`, `src/harness_rsi/harness.py`,
  `src/harness_rsi/paths.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/change-management.md`
- Hypothesis: once candidate creation, heldout gates, regression gates, and
  promotion are explicit, the next useful primitive is a single transparent
  cycle that runs them in order and writes an audit summary.
- Change made: added `harness-rsi experiment cycle`. The command runs parent
  train evidence, proposes a patch, creates a candidate, evaluates heldout and
  regression splits for parent/candidate, writes both gates, writes a composite
  gate, and promotes only when both gates pass. Cycle summaries are written to
  `.rsi/cycles/`.
- Validation run: `pytest` reported 21 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke test ran a full mock cycle creating and
  promoting `H5` from `H0`, then inspected promoted lineage for heldout and
  regression run paths.
- Observation: the sidecar review caught that proposal generation was still
  reading legacy `.rsi/harness.json`, not the parent harness under test. The
  cycle now passes the parent harness path into proposal generation.
- Learning: promotion should consume a composite decision, not a single heldout
  gate. Otherwise regression evidence is checked in orchestration but not
  preserved as promotion lineage. Composite gates should also carry explicit
  heldout/regression run IDs, not just gate file paths.
- Remediation: next increment should add richer cycle policies, especially
  per-environment deltas, explicit cost/latency placeholders, and rejection
  artifacts for non-promoted candidates.

## CM-0007: Metrics And Rejection Decision Artifacts

- Date: 2026-06-18
- Files changed: `src/harness_rsi/harness.py`, `src/harness_rsi/benchmarks.py`,
  `src/harness_rsi/cycle.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/change-management.md`
- Hypothesis: pass rate alone is too coarse to study harness-level RSI. The
  system needs environment-specific performance and basic efficiency signals,
  even before real cost accounting exists.
- Change made: run summaries now include `metrics`, `per_environment`, duration,
  attempt counts, tool-call counts, and nullable cost placeholders. Comparisons
  and gates now include `metric_deltas` and `environment_scores`. Rejected
  cycles write first-class decision artifacts under `.rsi/decisions/`.
- Validation run: `pytest` reported 21 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke test ran a no-promote cycle for `H6` and
  inspected the rejected decision artifact plus heldout gate metrics.
- Observation: duration deltas are noisy at this scale, but the field is still
  useful as a placeholder for heavier benchmarks. Per-environment scores make
  the world-model probe visible instead of burying it inside aggregate pass
  rate.
- Learning: rejected candidates are as valuable as promoted ones for harness RSI.
  They need explicit artifacts so failed improvement hypotheses become future
  training/evaluation material.
- Remediation: next increment should add policy configuration that can gate on
  environment-specific regressions and eventually cost/latency thresholds.

## CM-0008: Enhanced Eval-Suite Roadmap

- Date: 2026-06-19
- Files changed: `README.md`, `docs/evaluation-architecture.md`,
  `docs/eval-suite-roadmap.md`, `docs/change-management.md`
- Hypothesis: the next eval-suite increment needs a documented roadmap before
  implementation so task sources, splits, gate policy, per-environment behavior,
  failure-family coverage, testing levels, and review expectations are explicit.
- Change made: documented the `sim-v0` roadmap, benchmark-source classes,
  train/heldout/regression split contract, failure-family coverage matrix,
  per-environment gate policy, eval-suite testing levels, and change-management
  expectations.
- Validation run: `git diff --check`.
- Observation: this is a documentation-only change. It describes expected
  roadmap behavior and keeps future policy enforcement separate from fields that
  are currently recorded as evidence only.
- Learning: eval-suite design is part of the harness, not background test data.
  The roadmap needs versioning and review discipline before stronger gates are
  implemented.
- Remediation: implement `sim-v0` in increments: manifest and metadata first,
  per-environment policy second, failure-family coverage reporting third, and
  external adapters only after local policy tests are stable.

## CM-0009: Sim-v0 Sources And Policy Gates

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/*`, `src/harness_rsi/benchmarks.py`,
  `src/harness_rsi/cli.py`, `tests/test_harness.py`,
  `tests/test_eval_suite_coverage.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: harness-level RSI needs a richer local simulation suite and
  stronger gates before external benchmark adapters are credible.
- Change made: added source-controlled `sim-v0` benchmark sources with train,
  heldout, and regression splits across knowledge work, coding microtasks, data
  operations, customer support, static world-model traces, and mechanics. Added
  benchmark profile materialization into `.rsi/benchmarks/<name>`, copied
  `gate_policy.json`, added per-environment gate enforcement, and fixed
  regression-drop semantics so `max_allowed_drop` can actually allow a bounded
  regression when configured.
- Validation run: `pytest` reported 28 passing tests; `ruff check .` passed.
  Manual smoke test materialized `sim-v0` in `/private/tmp`, ran H0 heldout and
  regression splits, and wrote a heldout gate showing `effective_min_delta`,
  `max_environment_drop`, `protected_environments`, `environment_scores`, and
  no `environment_failures`.
- Observation: the first implementation pass exposed that source benchmark
  lookup must work outside the repo root. The source resolver now checks both
  `./benchmarks/<profile>` and the editable package's repository root. It also
  exposed a gate-policy readability issue, so gate artifacts now separate
  requested thresholds from effective thresholds.
- Learning: the suite should stay as data plus policy around the existing
  runner. Creating separate training and evaluation runtimes would add
  complexity without improving the measurement claim yet.
- Remediation: next increment should add failure-family coverage reporting,
  evaluator digest/version fields, and explicit policy tests for malformed
  source profiles before adding Terminal-Bench, SWE-bench, or tau-style
  adapters.
