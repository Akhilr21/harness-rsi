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
- waived cells with `reason`, `owner`, `tracking_ref`, `review_by`, and an
  optional `expires_when` condition
- report-only cells that are useful to track but not ready to block promotion
- how waiver metadata is stored, such as manifest fields or a separate waiver
  file
- which gates consume the coverage policy: heldout, regression, composite, or
  promotion
- whether missing required cells fail closed before score comparison, after
  score comparison, or only at the composite-gate boundary
- expected artifact changes to `coverage.json`, gate decisions, composite
  gates, cycle summaries, rejection artifacts, and promoted harness lineage
- lifecycle-report grouping keys, artifact paths, and whether the report changes
  promotion semantics
- waiver-review gate fields, if any, including whether the policy is audit-only,
  whether overdue active-missing waivers fail closed, and which deterministic
  `as_of` date the gate uses

Missing required evidence should fail closed. A waived cell should be explicit
evidence, not an absence that happens to pass. Waivers are acceptable only when
they preserve the measurement claim for the suite version under review, and the
suite should reject waiver entries that do not identify who owns the missing
evidence, where it is tracked, and when it must be reviewed.

If waiver review changes promotion semantics, the gate must carry the review
policy and lifecycle evidence into the gate artifact. Blocking policies should
use an explicit review date rather than the wall clock so gates remain
reproducible.

This matters more, not less, for frontier-model and world-model work. Stronger
frontier models can raise aggregate scores while still hiding localized harness
failures in tool sequencing, state tracking, context selection, recovery, or
cost. World-model traces are even easier to over-credit because a plausible
rollout can mask impossible transitions, drift, bad intervention selection, or
reset/replay errors. Required and waived coverage cells make those evaluation
pressures explicit before a candidate can be promoted.

## Efficiency Policy Expectations

Efficiency is part of the harness-level improvement claim. A candidate that
keeps score flat by spending more attempts, tools, time, or cost may be a worse
harness even if the model is unchanged.

Every efficiency-policy increment should record:

- metric source and reliability class, such as deterministic attempts,
  deterministic tool calls, noisy local duration, or unavailable provider cost
- thresholds by split and gate scope
- whether missing metric values fail closed or remain evidence-only
- artifact changes to gates, composite gates, cycle summaries, rejection
  artifacts, and promoted harness lineage
- why duration or cost is being enforced now or intentionally left opt-in
- frontier/world-model implications, especially whether a candidate is spending
  more search or rollout analysis to appear better

Attempts and tool calls are reliable enough for local `sim-v0` policy gates.
Duration remains noisy in local tests, and cost remains unavailable until
provider usage accounting lands. If a policy configures a metric whose value is
missing, the gate should fail closed instead of silently ignoring the threshold.

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

## CM-0012: Waiver Metadata Accountability

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/manifest.json`,
  `src/harness_rsi/benchmarks.py`, `tests/test_harness.py`,
  `tests/test_eval_suite_coverage.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: a waived missing coverage cell is still measurement debt. If the
  suite lets a candidate promote while evidence is missing, the waiver should
  say who owns the debt, when it will be reviewed, and what condition should end
  the waiver.
- Change made: `coverage_policy.waivers` now require `reason`, `owner`,
  `tracking_ref`, and a `review_by` date in `YYYY-MM-DD` format, with optional
  `expires_when`. Normalized waiver cells preserve that metadata in
  `coverage.json` and gate artifacts. Malformed waiver lists, unknown waiver
  keys, duplicate waiver identities, missing waiver metadata, malformed review
  dates, and required/waiver overlap fail closed during benchmark
  materialization or coverage report generation.
- Gate enforcement: missing required cells still decide promotion. Waived cells
  still do not block promotion by themselves, but their owner/review metadata
  is now part of the coverage-policy digest and the gate artifact. A reviewer
  can inspect exactly which missing evidence was allowed, who owns it, and what
  tracking/review hook keeps it from becoming silent permanent sparsity. Gates
  also reject `coverage_digest_mismatch` when coverage policy changes after run
  evidence is produced.
- Frontier/world-model note: this does not prove the suite is comprehensive or
  safe for live frontier-model or world-model deployment. It narrows a more
  practical risk: stronger models can improve aggregate scores while hiding
  local failures in state consistency, drift detection, intervention selection,
  reset/replay, tool sequencing, context selection, or recovery. Waiver metadata
  keeps those missing pressures visible until they become real tasks or required
  cells.
- Validation run: targeted `pytest tests/test_eval_suite_coverage.py
  tests/test_harness.py` reported 51 passing tests; targeted `ruff check`
  passed. Tests cover waiver metadata in `sim-v0`, missing waiver metadata
  rejection, unknown waiver key rejection, duplicate waiver rejection,
  required/waiver overlap rejection, malformed `review_by` rejection, gate
  artifacts preserving owner/review metadata for waived missing cells, and gate
  rejection when coverage policy drifts after run evidence is produced.
- Observation: once waivers become gate-adjacent evidence, they need the same
  review discipline as code. Otherwise the harness can learn to route around
  weak spots in the eval suite instead of improving against them.
- Learning: harness-level RSI requires explicit management of evaluation debt.
  The system is not only evaluating candidate harnesses; it is also evaluating
  the trustworthiness of the benchmark surface used to promote them.
- Remediation: add a first-class waiver lifecycle command or report that can
  list active waivers by owner/review date, then expand `world_model_static`
  with Decart-style rollout trace cases so the most important world-model
  waivers can be retired or promoted into required cells.

## CM-0013: Static World-Model Rollout Trace Cases

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/sources/train/world_model_static.jsonl`,
  `benchmarks/sim-v0/sources/heldout/world_model_static.jsonl`,
  `benchmarks/sim-v0/sources/regression/world_model_static.jsonl`,
  `benchmarks/sim-v0/manifest.json`, `tests/test_harness.py`,
  `tests/test_eval_suite_coverage.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: world-model pressure can start as deterministic trace evaluation
  before the harness integrates a live simulator. Static rollout-shaped tasks
  should let the suite measure state tracking, drift detection, reset/replay,
  intervention choice, and rollout summarization while preserving the fixed
  model and digest-backed promotion contract.
- Change made: expanded `world_model_static` with six static rollout trace
  cases across train, heldout, and regression. Added source rows for rollout
  summaries, reset/replay comparability, and protected drift/reset regression
  cases. Updated `coverage_policy.required` so rollout summarization, heldout
  reset/replay, regression drift detection, and regression reset/replay are now
  explicit coverage requirements. `sim-v0` now materializes 33 tasks across
  train, heldout, and regression.
- Gate enforcement: no new gate type was added. The existing coverage gate now
  fails closed if any of the new world-model required cells disappear, and the
  existing suite and coverage digests make task or evaluator changes visible in
  run and gate artifacts.
- Frontier/world-model note: these are Decart/Oasis-style static rollout trace
  fixtures, not live simulator validation. No external world-model adapter,
  Decart/Oasis runtime, or simulator process was exercised. The value is that
  frontier-model runs now face local trace-shaped pressure before they can claim
  harness-level improvement on world-model-adjacent behavior.
- Validation run: `pytest` reported 51 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0`, regenerated
  coverage, ran heldout twice, and wrote a gate with 33 total suite tasks, 12
  heldout tasks, 14 required coverage cells, no missing required cells, and four
  `world_model_static` heldout tasks.
- Observation: `world_model_static` now makes state consistency, drift
  detection, impossible transitions, intervention selection, reset/replay, and
  rollout summarization visible in local coverage and gate artifacts. This is
  deterministic fixture validation only.
- Learning: world-model pressure can be represented as trace evaluation before
  simulator integration. Static rollout-shaped tasks strengthen the harness's
  state-tracking and intervention-policy evaluation while preserving the local
  suite contract. They do not prove live simulator performance.
- Remediation: review the new `world_model_static` coverage cells after several
  experiment cycles, then decide which additional world-model families should
  become required in a later suite version. Add a waiver lifecycle report and
  composite-gate digest-boundary tests before any live simulator adapter.

## CM-0014: Waiver Lifecycle Report

- Date: 2026-06-19
- Files changed: `src/harness_rsi/benchmarks.py`, `src/harness_rsi/cli.py`,
  `tests/test_harness.py`, `README.md`, `docs/evaluation-architecture.md`,
  `docs/eval-suite-roadmap.md`, `docs/change-management.md`
- Hypothesis: waiver metadata is preserved in coverage and gate artifacts, but
  the harness still needs a first-class query surface for measurement debt.
  Reviewers should be able to ask which waivers are active, who owns them, and
  which review dates are next without scanning raw coverage matrices.
- Change made: added `harness-rsi benchmark waivers --benchmark <name>` with an
  optional `--as-of YYYY-MM-DD` review date and `--due-within-days` window. The
  command writes `.rsi/benchmarks/<name>/waiver_lifecycle.json` and prints a
  concise summary grouped by owner and review date. The report carries suite
  digest, fresh coverage digest, stored `coverage.json` digest,
  coverage-policy digest, waiver identities, tracking references, review dates,
  expiry conditions, lifecycle state, and review status as `overdue`,
  `due_soon`, or `scheduled`.
- Gate enforcement: no promotion semantics changed in CM-0014. Waived cells
  remain non-blocking in this increment; CM-0018 later adds explicit overdue
  active-waiver gate policy.
- Frontier/world-model note: static world-model trace coverage now has a way to
  keep deferred evidence visible by owner and review date. This helps prevent
  frontier-model aggregate scores from hiding eval-suite debt, but it still does
  not claim live simulator safety or Decart/Oasis runtime validation.
- Validation run: `pytest` reported 56 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0` and ran
  `benchmark waivers --benchmark sim-v0 --as-of 2026-06-19
  --due-within-days 30`, writing `waiver_lifecycle.json` with 4 waivers, 4
  active missing cells, 0 retire candidates, `overdue=0`, `due_soon=0`,
  `scheduled=4`, owners `coding-evals=1`, `data-evals=1`, `eval-suite=2`, and
  matching fresh/stored coverage digests.
- Observation: waiver owner and review metadata was present in artifacts, but
  reviewers still had to scan those artifacts to answer which measurement debt
  was active, who owned it, and what date came next.
- Learning: waivers are measurement debt. Making them queryable by owner and
  review date improves eval-suite accountability without changing the
  fixed-model promotion contract.
- Remediation: decide whether overdue waiver states should remain audit-only or
  become future gate-policy inputs, then add composite-gate digest-boundary tests
  before external benchmark or live world-model adapters.

## CM-0015: Composite Gate Boundary Hardening

- Date: 2026-06-19
- Files changed: `src/harness_rsi/benchmarks.py`, `src/harness_rsi/cycle.py`,
  `src/harness_rsi/versions.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: after suite, coverage, evaluator, and waiver identity are carried
  through artifacts, the next failure mode is boundary slippage. A candidate
  should not promote from a single split, from mixed heldout/regression evidence,
  from child gates that changed after composition, or from coverage metadata that
  changed after the composite gate was written.
- Change made: `compare_runs` now rejects baseline/candidate coverage-digest
  mismatch when both runs carry coverage identity. `write_composite_gate` now
  validates heldout/regression split roles and requires matching baseline
  harness, candidate harness, candidate behavior digest, benchmark, model, suite
  version, suite digest, coverage digest, current coverage digest, and
  coverage-policy digest. Composite `promote` decisions require both component
  gates to promote. Composite gates now store canonical child-gate digests, and
  promotion re-reads those child gate files before mutating a candidate harness.
  Promotion also rejects non-composite gates and stale coverage digests.
- Gate enforcement: promotion semantics changed. A single heldout or regression
  gate is no longer sufficient promotion evidence; benchmark-grade promotion
  requires a composite heldout+regression gate with current coverage evidence
  and untampered child gates.
- Frontier/world-model note: this is important for frontier and
  world-model-adjacent use cases because stronger models can make aggregate
  scores look stable even when evidence is mixed across suite versions, coverage
  policies, or split roles. Live Decart/Oasis-style adapters should not be added
  until these local digest boundaries are boring.
- Validation run: `pytest` reported 66 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0` in `/private/tmp`
  and ran `experiment cycle --parent H0 --candidate H1 --benchmark sim-v0
  --mock --min-heldout-delta 0 --max-regression-drop 0 --no-promote`, writing
  heldout and regression gates, a `heldout+regression` composite gate, and a
  rejection artifact. The composite gate carried `heldout_gate_digest`,
  `regression_gate_digest`, `coverage_digest`, and `coverage_policy_digest`.
- Observation: the previous implementation had the right artifact vocabulary but
  still trusted the caller at the composite and promotion boundary. It also let
  compare evidence carry the candidate coverage digest forward even if the
  baseline run came from a different coverage contract.
- Learning: digest fields only matter if boundaries actively compare them. A
  promotion artifact must be tamper-evident at the child-gate level, not only at
  the final candidate behavior digest.
- Remediation: next decide when efficiency metrics are reliable enough for gate
  semantics, then add a split-isolation audit that proves proposal evidence is
  train-only and does not leak heldout or regression task IDs.

## CM-0016: Split-Isolation Proposal Audit

- Date: 2026-06-19
- Files changed: `src/harness_rsi/improve.py`, `src/harness_rsi/cycle.py`,
  `src/harness_rsi/versions.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: harness-level RSI fails if validation traces leak into proposal
  generation. The system needs to prove that `train` is the only proposal
  evidence source and that heldout/regression remain validation-only.
- Change made: `propose_patch` now rejects source runs whose benchmark metadata
  split is not `train`. Proposals now include a normalized evidence manifest
  with source split, run path, task IDs, trace task IDs, task digest, result
  digest, trace digest, input digest, and prompt digest for non-mock proposals.
  Experiment cycles now write `.rsi/cycles/<cycle-id>-split-isolation.json`
  with proposal source checks, embedded evidence checks, train/validation task
  ID disjointness, trace task ID checks, recursive validation-reference scanning,
  and a split-isolation digest. Composite gates carry that audit path and digest,
  and promotion rejects missing, failing, or mutated split-isolation evidence.
- Gate enforcement: promotion semantics changed. Benchmark-grade promotion now
  requires a passing split-isolation audit in addition to heldout/regression
  composite gate evidence.
- Frontier/world-model note: this is especially important for frontier and
  Decart/Oasis-style world-model work because validation rollouts contain rich
  state traces that are tempting to reuse as proposal context. A stronger model
  can appear to improve after seeing a leaked validation rollout while the
  harness has not learned a generalizable improvement.
- Validation run: `pytest` reported 71 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0` in `/private/tmp`
  and ran `experiment cycle --parent H0 --candidate H1 --benchmark sim-v0
  --mock --min-heldout-delta 0 --max-regression-drop 0 --no-promote`, writing a
  passing split-isolation audit with zero leaked validation references. The
  composite gate carried the split-isolation audit path and digest, and the
  rejection artifact preserved the same audit reference.
- Observation: prior artifacts identified the train source run, but that was a
  metadata claim, not an information-flow proof. Non-mock proposal generation
  also sent raw trace text to the model without recording a normalized manifest
  of model-visible evidence.
- Learning: split isolation is not just a split label. It is a boundary over
  results, traces, task IDs, run IDs, run paths, prompt context, and recursive
  proposal payloads.
- Remediation: next decide whether efficiency metrics are reliable enough to
  become gate inputs, and separately decide whether overdue waiver lifecycle
  states should remain audit-only or become promotion policy.

## CM-0017: Efficiency Gate Policy

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/gate_policy.json`,
  `src/harness_rsi/benchmarks.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: harness-level RSI should not promote candidates that preserve or
  improve score only by spending more attempts, tool calls, time, or cost. The
  fixed-model claim needs an efficiency boundary in addition to correctness,
  coverage, split-isolation, and digest boundaries.
- Change made: split `gate_policy.json` entries can now configure
  `max_attempt_delta`, `max_tool_call_delta`, `max_duration_ms_delta`, and
  `max_cost_usd_delta`. Gates write `efficiency_thresholds` and
  `efficiency_failures`, and reject candidates when configured metrics exceed
  their allowed delta. Missing configured metrics fail closed with
  `metric_unavailable`. `sim-v0` now enforces `max_attempt_delta: 0` and
  `max_tool_call_delta: 0` for heldout and regression gates, while leaving
  duration and cost unset by default.
- Gate enforcement: promotion semantics changed for source-backed `sim-v0`
  gates. A candidate can no longer promote on heldout/regression if it uses more
  attempts or tool calls than the baseline, even with the same pass rate.
  Duration and cost are supported but opt-in.
- Frontier/world-model note: frontier models and Decart/Oasis-style world-model
  harnesses can appear better by spending more retries, search, tool use, or
  rollout analysis. Attempts/tool-call gates are the first reliable local check
  that a harness improvement is not just hidden extra compute. Duration remains
  noisy locally, and cost should wait for provider usage accounting.
- Validation run: `pytest` reported 76 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0` in `/private/tmp`,
  ran two equal mock heldout runs, and wrote a gate with
  `efficiency_thresholds` set to `attempts=0`, `tool_calls=0`,
  `duration_ms=null`, `cost_usd=null`, no `efficiency_failures`, and decision
  `promote`.
- Observation: metrics already existed in run, comparison, gate, and decision
  artifacts, but they were mostly passive evidence. A flat score with higher
  attempts or tool calls could still pass unless a reviewer manually noticed the
  metric deltas.
- Learning: efficiency is a harness-level RSI signal only when measured under
  the same model, split, suite, coverage policy, and split-isolation boundary.
  Attempts and tool calls are deterministic enough for `sim-v0`; duration and
  cost need stronger measurement before default enforcement.
- Remediation: next decide whether overdue waiver lifecycle states should become
  promotion policy, then keep external adapters read-only until local gates are
  stable under repeated cycles.

## CM-0018: Waiver Review Gate Policy

- Date: 2026-06-19
- Files changed: `benchmarks/sim-v0/gate_policy.json`,
  `src/harness_rsi/benchmarks.py`, `src/harness_rsi/cycle.py`,
  `src/harness_rsi/versions.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: waivers are measurement debt. Querying them is useful, but a
  candidate should not promote from overdue missing evidence when the suite
  owner has explicitly made waiver review a promotion gate. The gate must remain
  deterministic: no implicit wall-clock date, no evaluator changes, and no
  promotion impact unless split `gate_policy.json` opts in.
- Change made: split gate policy now supports `fail_on_overdue_waivers`,
  `waiver_review_as_of`, and `waiver_due_within_days`. When blocking is enabled,
  `waiver_review_as_of` is required and must be `YYYY-MM-DD`. Gates write
  `waiver_review_policy`, a summarized `waiver_review`, and
  `waiver_review_failures`. Only waivers with `review_state=overdue` and
  `lifecycle_state=active_missing` fail promotion. `due_soon` waivers and
  overdue retire candidates remain evidence-only. Composite gates require
  heldout/regression waiver review policy and evidence to match, and promotion
  re-runs the stored policy before mutating a candidate harness.
- Gate enforcement: `sim-v0` enables overdue-waiver blocking for heldout and
  regression with `waiver_review_as_of: 2026-06-19`. The current suite has four
  active missing waivers scheduled for `2026-09-30`, so current gates continue
  to pass. A review policy pinned to `2026-10-01` rejects equal-score candidates
  until those waivers are renewed, retired, or promoted into required coverage.
- Frontier/world-model note: for frontier models and Decart/Oasis-style
  world-model harnesses, missing trace coverage can look harmless while aggregate
  score improves. Overdue waiver gates make that measurement debt explicit
  before product-facing or simulator-backed claims are allowed to build on it.
- Validation run: `pytest` reported 84 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0` in `/private/tmp`,
  ran a full mock cycle with `waiver_review_as_of=2026-06-19`, promoted with no
  waiver review failures, then forced a temp policy to `2026-10-01` and
  confirmed an equal-score heldout gate rejected with four `overdue_waiver`
  failures.
- Observation: lifecycle reports already exposed owner, review date, stale
  coverage identity, and active/retire state, but a candidate could still
  promote while active missing evidence was overdue if reviewers did not inspect
  the report manually.
- Learning: measurement debt becomes promotion debt only when it is bound to an
  explicit policy, review date, and digest evidence. Blocking overdue active
  waivers is defensible; blocking due-soon or already-covered waivers is too
  noisy for this stage.
- Remediation: run repeated local cycles with the waiver review gate enabled,
  then add read-only external benchmark adapters once coverage, efficiency,
  split-isolation, and waiver-review gates remain stable together.

## CM-0019: Repeated Local Cycle Stability

- Date: 2026-06-19
- Files changed: `src/harness_rsi/cycle.py`, `src/harness_rsi/cli.py`,
  `tests/test_harness.py`, `README.md`, `docs/evaluation-architecture.md`,
  `docs/eval-suite-roadmap.md`, `docs/change-management.md`
- Hypothesis: before external benchmark adapters, the local harness must prove
  it can run repeated `Hn -> Hn+1` attempts under the full current promotion
  contract. One successful cycle is not enough; adapter work should wait until
  coverage, waiver review, efficiency, split isolation, composite gates, and
  promotion-time digest rechecks remain stable across a short candidate chain.
- Change made: added `harness-rsi experiment stability`, which runs repeated
  experiment cycles, optionally promotes and advances the parent after each
  passing cycle, and writes `.rsi/cycles/stability-*.json`. The report records
  parent/candidate lineage, child cycle paths, heldout/regression/composite
  decisions, split-isolation audit status, suite and coverage identity, waiver
  review policy, efficiency thresholds, failure counts, rollup stability checks,
  and a `stability_digest`.
- Gate enforcement: no new gate semantics changed. CM-0019 validates the
  existing gates together. A stability report passes only when every child cycle
  has promoted heldout/regression gates, a passing split-isolation audit, stable
  suite/coverage/policy identity, and no coverage, waiver-review, environment,
  efficiency, or split-isolation failures. `--no-promote` remains useful for dry
  runs: validation can pass while parent lineage stays unchanged.
- Frontier/world-model note: frontier models and Decart/Oasis-style world-model
  harnesses make repeated-cycle evidence more important, not less. A single
  local win can be accidental. A short promoted chain shows the harness can keep
  train-only proposal evidence, deterministic trace coverage, waiver review, and
  efficiency boundaries intact before richer external or simulator-backed tasks
  are attached.
- Validation run: `pytest` reported 89 passing tests; `ruff check .` passed;
  `git diff --check` passed. CLI smoke materialized `sim-v0` in `/private/tmp`
  and ran `experiment stability --parent H0 --candidate-prefix H --cycles 2
  --benchmark sim-v0 --mock`, producing a `pass` stability report for
  `H0 -> H1 -> H2` with stable suite/coverage/policy digests, zero waiver review
  failures, zero efficiency failures, zero split-isolation violations, and
  `promotion_status=pass`.
- Observation: CM-0015 through CM-0018 hardened individual boundaries, but the
  missing evidence was operational. Reviewers could inspect one cycle at a time,
  yet there was no single artifact answering whether repeated candidate attempts
  preserved the same gate contract without manual repair.
- Learning: local cycle stability is the adapter-readiness gate. External
  benchmarks should contribute task sources and fixture metadata, not become the
  first place where promotion-boundary interactions are tested together.
- Remediation: use stability reports as the required smoke before adding
  read-only Terminal-Bench, SWE-bench, tau/tau3-style, or live world-model
  adapters. If a future adapter changes gate semantics, it should create a new
  CM entry rather than hiding that change inside adapter plumbing.

## CM-0020: Read-Only External Adapter Metadata

- Date: 2026-06-19
- Files changed: `benchmarks/external-adapter-smoke-v0/`,
  `src/harness_rsi/benchmarks.py`, `src/harness_rsi/cli.py`,
  `tests/test_harness.py`, `README.md`, `docs/evaluation-architecture.md`,
  `docs/eval-suite-roadmap.md`, `docs/change-management.md`
- Hypothesis: after CM-0019 stability reports, the first external-adapter
  increment should prove metadata parity, not benchmark ambition.
  Terminal-Bench, SWE-bench, and tau/tau3-style sources can be represented
  safely if they compile into the existing local split, evaluator, coverage, and
  gate schema without adding new promotion semantics.
- Change made: added task-level `external_adapter` metadata validation for
  source profiles, a read-only `benchmark adapters --benchmark <name>` report,
  and a committed `external-adapter-smoke-v0` profile with terminal,
  issue-patch, and tool-agent-user task shapes across train, heldout, and
  regression. Adapter rows must identify `name`, `kind`, `external_id`,
  `fixture_version`, `source_url`, and `mode: read_only`. The report records
  adapter task counts, kind counts, split counts, fixture versions, source URLs,
  metadata failures, and an `adapter_report_digest`.
- Gate enforcement: no promotion semantics changed. Adapter reports do not run
  external benchmark harnesses, do not create runs or gates, do not mutate
  coverage or gate policy artifacts, and are not promotion evidence. They are
  provenance and fixture-readiness evidence only.
- Frontier/world-model note: external coding, terminal, and customer-support
  tasks are useful only if they enter the harness through the same local
  measurement contract. Live Decart/Oasis-style world-model adapters remain
  deferred because CM-0020 does not yet define simulator trace ingestion,
  intervention replay, or live rollout validation semantics.
- Validation run: `pytest` reported 93 passing tests; `ruff check .` passed;
  `git diff --check` passed. Focused `pytest tests/test_harness.py` reported 76
  passing tests and `pytest tests/test_eval_suite_coverage.py` reported 17
  passing tests. A CLI smoke materialized `external-adapter-smoke-v0` and
  `harness-rsi benchmark adapters --benchmark external-adapter-smoke-v0`
  produced a passing read-only report with 9 adapter rows, zero metadata
  failures, and no gate semantics changed. A one-cycle stability smoke on
  `external-adapter-smoke-v0` passed from H0 to H1 with zero coverage,
  environment, efficiency, split-isolation, waiver, heldout, or regression
  failures.
- Observation: the repo already had source profile materialization and stability
  reports, but “add external adapters” could still be misread as building
  runners first. The missing step was an inspectable metadata contract that lets
  adapter-shaped tasks become local benchmark rows without changing the
  promotion boundary.
- Learning: adapters should begin as provenance and fixture surfaces. The
  harness-level RSI claim remains local: same model, same split contract, same
  evaluator identity, same coverage/waiver/efficiency gates, and same composite
  promotion checks.
- Remediation: next add importers from frozen local exports of real
  Terminal-Bench, SWE-bench, and tau/tau3-style datasets into this metadata
  contract. Any adapter that needs new scoring, tool execution, Docker, or live
  simulator semantics must get its own CM entry and gate-policy review.

## CM-0021: Frozen Local External-Adapter Importers

- Date: 2026-06-19
- Files changed: `src/harness_rsi/adapter_importers.py`,
  `src/harness_rsi/cli.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: after CM-0020 metadata parity, the next useful external-benchmark
  increment is a frozen local import path, not a live runner. Terminal-Bench,
  SWE-bench, and tau/tau3-style exports should be able to become local source
  profiles only when they preserve split identity, fixture version, external
  task identity, deterministic evaluator identity, and read-only adapter mode.
- Change made: added `benchmark import-adapters --source <path> --profile
  <name>` to compile frozen JSON/JSONL exports into
  `benchmarks/<profile>/sources/{train,heldout,regression}`. The importer writes
  `manifest.json`, strict local `gate_policy.json`, and `import_report.json`
  with source export digest, importer version, adapter counts, kind counts,
  split counts, fixture versions, metadata failures, and an import digest. It
  fails closed for missing train/heldout/regression splits, live or runner
  modes, unsupported adapter kinds, duplicate external fixture IDs, and missing
  deterministic evals.
- Gate enforcement: no promotion semantics changed. Importer reports do not
  create runs, gates, composite gates, proposal evidence, or promoted harnesses.
  Imported rows become promotion-relevant only after the existing
  materialization, run, heldout/regression gate, split-isolation, composite
  gate, and promotion-time digest path consumes them.
- Frontier/world-model note: for frontier models, this broadens measurement
  coverage without changing the fixed-model Hn/Hn+1 claim. For Decart/Oasis
  world-model use cases, CM-0021 still does not ingest simulator traces, replay
  interventions, grade rollout video/state, or run a live world-model adapter.
  Static `world_model_static` probes remain the only world-model pressure in
  this repo until a separate trace-ingestion contract exists.
- Validation run: `pytest` reported 100 passing tests; `ruff check .` passed;
  `git diff --check` passed. Focused `pytest tests/test_harness.py` reported 83
  passing tests after importer, materialization, adapter-report, read-only
  side-effect, missing split, live-mode, duplicate external-id,
  force-overwrite, top-level JSON list, and unsafe profile-path cases. A CLI
  smoke imported a frozen local export into
  `cm0021-smoke`, materialized it, wrote a passing read-only adapter report with
  3 adapter rows and zero metadata failures, then ran a one-cycle stability
  smoke from H0 to H1 with zero coverage, environment, efficiency,
  split-isolation, waiver, heldout, or regression failures.
- Observation: frozen real exports expose provenance, split, fixture, and
  evaluator gaps without requiring Docker, terminal execution, or user-simulator
  plumbing. The importer is where those gaps should fail loudly before the
  benchmark becomes local evidence.
- Learning: adapter import is still measurement infrastructure. Even without
  changing gate semantics, it changes what future gates can measure, so import
  reports need source digests, fixture versions, and deterministic split
  coverage just like benchmark reports need suite and coverage digests.
- Remediation: next add rejected-row reporting and optional split-map review so
  larger frozen exports can explain why rows were not imported. Then import a
  tiny real frozen export from one benchmark family and run the complete
  materialize, adapter-report, and stability-smoke path before any live runner
  or simulator adapter work.

## CM-0022: Import Review And Rejected-Row Reporting

- Date: 2026-06-20
- Files changed: `src/harness_rsi/adapter_importers.py`,
  `src/harness_rsi/cli.py`, `tests/test_harness.py`, `README.md`,
  `docs/evaluation-architecture.md`, `docs/eval-suite-roadmap.md`,
  `docs/change-management.md`
- Hypothesis: larger frozen external-adapter exports need row-level rejection
  visibility and split-map review before they can safely become local source
  profiles. A binary “profile written or not” importer hides measurement gaps
  that later frontier-model or world-model experiments could mistake for
  benchmark coverage.
- Change made: extended `benchmark import-adapters` with `--split-map`,
  `--review-split-map`, and explicit `--allow-rejected-rows` support. Import
  reports now include source row count, accepted task count, rejected row count,
  rejection reason counts, accepted/rejected row digests, split-map digest,
  split-map used/unused entries, and compact non-raw rejected-row records.
  Strict failures and review-only runs write
  `benchmarks/_import_reviews/<profile>/import_review.json` without creating a
  materializable source profile.
- Gate enforcement: no promotion semantics changed. Import reviews, rejected
  rows, split maps, and import reports are provenance/import-QA artifacts only.
  Accepted rows become measurement evidence only after materialization, runs,
  heldout/regression gates, split-isolation audit, composite gate, and
  promotion-time digest checks.
- Frontier/world-model note: for frontier models, CM-0022 makes negative
  measurement evidence visible before a stronger model can make sparse coverage
  look good. For Decart/Oasis-style world-model work, this still does not ingest
  simulator traces, replay interventions, evaluate rollout video/state, or add
  live simulator validation.
- Validation run: `pytest` reported 106 passing tests; `ruff check .` passed;
  `git diff --check` passed. Focused `pytest tests/test_harness.py` reported 89
  passing tests after strict review artifacts, partial imports, raw split-label
  maps, split-map review-only mode, and rejected-row report fields. A CLI smoke
  wrote a review-only artifact for `cm0022-smoke`, imported the same frozen
  export with `--allow-rejected-rows`, recorded 3 accepted adapter rows and 1
  rejected row, materialized the profile, wrote a passing adapter report with
  zero metadata failures, then ran a one-cycle stability smoke from H0 to H1
  with zero coverage, environment, efficiency, split-isolation, waiver, heldout,
  or regression failures.
- Observation: CM-0021’s fail-closed importer was safe for small fixtures but
  too opaque for larger frozen exports. Review artifacts provide an audit trail
  without allowing failed rows to become benchmark evidence by accident.
- Learning: rejected rows are first-class measurement debt. They are not model
  failures, but they say exactly where the harness still lacks a replayable,
  deterministic eval contract.
- Remediation: next import one tiny real frozen export from one benchmark family
  and run the complete materialize, adapter-report, and stability-smoke path.
  Then add source-location preservation for JSONL directory imports so rejected
  rows can cite file and line number instead of only export name and row index.

## CM-0023: SWE-Bench Lite Frozen Export Smoke

- Date: 2026-06-21
- Files changed:
  `benchmarks/_frozen_exports/swe-bench-lite-smoke-v0/README.md`,
  `benchmarks/_frozen_exports/swe-bench-lite-smoke-v0/tasks.json`,
  `benchmarks/_frozen_exports/swe-bench-lite-smoke-v0/split-map.json`,
  `tests/test_harness.py`, `README.md`, `docs/evaluation-architecture.md`,
  `docs/eval-suite-roadmap.md`, `docs/change-management.md`
- Hypothesis: one tiny real frozen benchmark-family export can enter the local
  harness without weakening the fixed-model Hn/Hn+1 measurement contract. The
  useful proof is not a public leaderboard score; it is whether source identity,
  split mapping, fixture version, evaluator digest, materialization, adapter
  reporting, and no-promote stability evidence all survive the same local path.
- Change made: added `swe-bench-lite-smoke-v0`, a committed frozen export with
  three public SWE-bench Lite instance IDs mapped into local `train`, `heldout`,
  and `regression` roles by `split-map.json`. The local evaluator is
  identity-only and deterministic, so the fixture proves import plumbing and
  provenance rather than patch correctness. Added an end-to-end test that imports
  the fixture, asserts import-report identity, materializes the source profile,
  asserts coverage and adapter report identity, and runs a one-cycle no-promote
  stability smoke.
- Gate enforcement: no promotion semantics changed. The committed export,
  split map, import report, and adapter report remain provenance/import-QA
  artifacts. They matter for promotion only after materialization, run evidence,
  heldout/regression gates, split-isolation audit, composite gate, and
  promotion-time digest checks. The stability smoke uses `--no-promote` to prove
  validation without mutating the promoted parent chain.
- Frontier/world-model note: for frontier coding models, this makes the first
  real public benchmark identity available inside the local harness without
  claiming benchmark resolution ability. For Decart/Oasis-style world-model
  work, nothing changes: this does not add simulator traces, intervention
  replay, live state validation, video/state rollouts, or world-model adapters.
- Validation run: `pytest` reported 107 passing tests; `ruff check .` passed;
  `git diff --check` passed. Focused pytest for
  `test_benchmark_import_adapters_materializes_swe_bench_lite_smoke_fixture`
  reported 1 passing test after exercising import, materialization, adapter
  reporting, and one no-promote stability cycle. A CLI smoke in
  `/private/tmp/harness-rsi-cm0023.mZ0BQq` imported the committed SWE-bench Lite
  fixture with split-map usage 3/3, materialized
  `swe-bench-lite-smoke-v0`, wrote a passing read-only adapter report with 3
  adapter rows and zero metadata failures, then ran a one-cycle no-promote
  stability smoke from H0 to `DryRun1` with zero coverage, environment,
  efficiency, split-isolation, waiver, heldout, or regression failures.
- Observation: the importer contract was already strong enough to ingest a real
  public benchmark-family fixture once the source stayed tiny and the split
  roles were explicit. The critical boundary is naming the local evaluator as
  identity-only so a passing smoke cannot be mistaken for SWE-bench patch
  grading.
- Learning: real benchmark rows are useful early when they test provenance and
  replayability, not when they force the project to adopt a full external runner
  before the local gate contract is stable.
- Remediation: next add source-location preservation for JSONL directory imports
  so rejected rows can cite file and line number. Then add equally tiny
  Terminal-Bench and tau-style frozen exports before live runners, Docker
  grading, or simulator loops.
