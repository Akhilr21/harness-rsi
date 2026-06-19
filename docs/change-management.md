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
- coverage-report changes and any suite/evaluator digest changes
- gate-policy changes and expected promotion impact
- validation commands and artifact paths
- migration or backfill plan for prior runs if old evidence is no longer
  comparable

Task data, evaluator definitions, suite version, and gate semantics should move
together. Once a candidate run exists, do not edit the tasks or evaluator
definitions used by that run in place. Create a new suite version instead.

PRs that change gate semantics should say so explicitly. PRs that only add
coverage should still explain the source and failure family of the new cases.

## Coverage Policy Expectations

Coverage is now part of the measurement contract, not just a report. Before
missing family coverage can fail a promotion gate, the suite must say which
environment/family/split cells are required, intentionally waived, or
report-only.

Every coverage-policy increment should record:

- required cells by environment, failure family, and split
- waived cells with a short reason, owner, and review date or expiry condition
- report-only cells that are useful to track but not ready to block promotion
- how waiver metadata is stored, such as manifest fields or a separate waiver
  file
- which gates consume the coverage policy: heldout, regression, composite, or
  promotion
- whether missing required cells fail closed before score comparison, after
  score comparison, or only at the composite-gate boundary
- expected artifact changes to `coverage.json`, gate decisions, composite
  gates, cycle summaries, rejection artifacts, and promoted harness lineage

Missing required evidence should fail closed. A waived cell should be explicit
evidence, not an absence that happens to pass. Waivers are acceptable only when
they preserve the measurement claim for the suite version under review.

This matters more, not less, for frontier-model and world-model work. Stronger
frontier models can raise aggregate scores while still hiding localized harness
failures in tool sequencing, state tracking, context selection, recovery, or
cost. World-model traces are even easier to over-credit because a plausible
rollout can mask impossible transitions, drift, bad intervention selection, or
reset/replay errors. Required and waived coverage cells make those evaluation
pressures explicit before a candidate can be promoted.

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
- Remediation: CM-0009 added policy configuration for environment-specific
  regressions. Cost and latency thresholds remain future work once those
  measurements are reliable enough.

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
- Remediation: CM-0010 added failure-family coverage reporting, evaluator
  digest/version fields, and malformed source-profile tests. External adapters
  should still wait until required coverage cells and waivers are explicit.

## CM-0010: Coverage Reporting And Digest Identity

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/manifest.json`,
  `src/harness_rsi/benchmarks.py`, `src/harness_rsi/cli.py`,
  `src/harness_rsi/harness.py`, `src/harness_rsi/cycle.py`,
  `src/harness_rsi/versions.py`, `tests/test_harness.py`,
  `tests/test_eval_suite_coverage.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: before adding external adapters or live world-model integrations,
  `sim-v0` needs first-class failure-family coverage reporting plus explicit
  suite/evaluator identity fields so reviewers can tell whether a candidate is
  being measured against the same suite, the same evaluators, and the same gate
  policy.
- Change made: added `suite_version` to the committed `sim-v0` manifest; added
  evaluator digests to materialized task rows; added stable suite and coverage
  digests; added `harness-rsi benchmark coverage`; wrote `coverage.json` during
  source benchmark materialization; propagated suite, coverage, and evaluator
  identity through run summaries, comparisons, gates, composite gates, cycle
  summaries, rejected-cycle decision artifacts, and promoted harness lineage.
  Added tests for coverage matrices, digest stability, malformed source
  profiles, run metadata, and sim-v0 cycle identity.
- Frontier/world-model note: keep frontier-model experiments on the fixed-model
  A/B contract. Treat Decart-style world-model work as local trace-evaluation
  probes in `world_model_static` until coverage and digest artifacts are stable.
- Validation run: `pytest` reported 37 passing tests; `ruff check .` passed;
  `git diff --check` passed. Manual smoke test in `/private/tmp` materialized
  `sim-v0`, ran `benchmark coverage --benchmark sim-v0`, and ran
  `experiment cycle --parent H0 --candidate H1 --benchmark sim-v0 --mock
  --no-promote`. The smoke produced `coverage.json`, a rejected cycle summary,
  a composite gate, and a rejection artifact carrying `suite_version`,
  `suite_digest`, `coverage_digest`, and heldout/regression evaluator digests.
- Observation: coverage reporting immediately showed that many family/split
  cells are intentionally sparse. That is useful evidence, but it should remain
  report-only until the project has explicit required cells and waiver semantics.
- Learning: CM-0009 made `sim-v0` executable and policy-aware; the next risk is
  evidence identity. If suite, evaluator, and coverage identity are implicit,
  future gates can be hard to audit even when the runner behaves correctly.
  Coverage reporting also makes clear that harness RSI is not just score
  improvement; it is the discipline of deciding which failures become durable
  evaluation pressure.
- Remediation: define required versus waived coverage cells, add waiver metadata
  to the suite manifest or a separate waiver file, and only then promote missing
  family coverage from report-only evidence into gate enforcement.

## CM-0011: Coverage Policy Gate Enforcement

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/manifest.json`,
  `src/harness_rsi/benchmarks.py`, `src/harness_rsi/cli.py`,
  `tests/test_harness.py`, `tests/test_eval_suite_coverage.py`,
  `README.md`, `docs/evaluation-architecture.md`,
  `docs/eval-suite-roadmap.md`, `docs/change-management.md`
- Hypothesis: `sim-v0` should not promote candidates from coverage that is only
  accidentally sparse. Required and waived coverage cells make promotion gates
  distinguish missing evidence from intentionally deferred evidence.
- Change made: added `coverage_policy` to the `sim-v0` manifest with required
  cells and waived missing cells. Coverage reports now classify required,
  waived, and unclassified missing environment/family/split cells. Gates now
  include `coverage_policy_digest`, `coverage_failures`,
  `missing_required_cells`, `waived_missing_cells`, and
  `unclassified_missing_count`, and they reject candidates when required
  coverage is missing. Waived and unclassified missing cells remain visible as
  audit evidence but do not block promotion by themselves.
- Gate enforcement: missing required cells fail closed during gate evaluation
  alongside score and environment checks. Waived cells are copied into gate
  artifacts so reviewers can see exactly which evidence was absent and why it
  was allowed for this suite version. Report-only cells remain visible in
  `coverage.json` and gate artifacts as `unclassified_missing_count`.
- Frontier/world-model note: aggregate pass-rate wins are not enough evidence
  for frontier models or Decart-style world-model traces. Coverage policy should
  protect localized families such as state consistency, drift detection,
  intervention selection, reset/replay, tool sequencing, context selection, and
  recovery from being hidden by stronger model priors or easier task families.
- Validation run: `pytest` reported 45 passing tests; `ruff check .` passed.
  Tests cover required and waived coverage cells, gate pass with waived missing
  cells, gate rejection when a required cell is missing, and fail-closed behavior
  for malformed coverage-policy shape. CLI smoke materialized `sim-v0`, wrote
  coverage, ran two heldout passes, and wrote a gate decision with no coverage
  failures.
- Observation: the first policy layer exposed the difference between sparse
  coverage and missing required evidence. `sim-v0.1` has many unclassified
  missing cells, but only explicit required cells should block promotion. This
  keeps the suite honest without pretending it is comprehensive yet. The full
  coverage matrix is already too large for routine CLI output, so the command
  now prints summary counts and preserves the full matrix in `coverage.json`.
- Learning: coverage policy is a measurement contract, not just benchmark
  metadata. It lets the harness say, "this missing evidence is acceptable for
  now" or "this missing evidence invalidates promotion," which is exactly the
  kind of explicit self-evaluation loop needed for harness-level RSI.
- Remediation: add waiver owner/review metadata or expiry conditions, and expand
  `world_model_static` with Decart-style rollout trace cases before making more
  world-model families required.
