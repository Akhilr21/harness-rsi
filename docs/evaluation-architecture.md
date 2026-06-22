# Evaluation Architecture

`harness-rsi` studies harness-level improvement:

```text
fixed model M + harness Hn -> score
fixed model M + harness Hn+1 -> score
```

The model, task split, evaluator, and budget should stay fixed while the harness
changes. A candidate harness earns promotion only through evidence, not because a
prompt sounds better.

The enhanced eval-suite roadmap lives in `docs/eval-suite-roadmap.md`. This file
describes the current architecture; the roadmap doc tracks how `sim-v0` should
grow from local source-controlled probes into broader suite-versioned evals.

## Harness Versions

- `H0` is the baseline harness.
- `Hn+1` is a candidate generated from evidence about `Hn`.
- Harnesses live under `.rsi/harnesses/`.
- Each harness records `id`, `parent`, `model`, prompt, retry policy, and tool
  policy.

The core invariant is that `Hn` and `Hn+1` must use the same model during a
comparison. If the model changes, the experiment is no longer measuring the
harness.

## Eval Levels

### Level A: Mechanics

These tests verify the harness runtime itself:

- load harness configs
- parse JSONL tasks
- capture traces
- gate tool calls
- score deterministic evals
- compare runs
- reject invalid promotion attempts

### Level B: Synthetic Environments

Synthetic tasks are small, fast, and controlled. They are where we debug the
experimental loop before touching expensive public benchmarks.

Initial environments:

- `knowledge_work`: extract objectives, constraints, and decision criteria from
  messy requests.
- `coding_micro`: diagnose small failures and produce patch-oriented answers.
- `data_ops`: reason about schemas and data assets.
- `tool_use`: validate tool access and observation loops.
- `customer_support`: follow policy-like artifacts.
- `world_model_static`: test rollout-shaped static traces for state
  consistency, drift, impossible transitions, reset/replay, intervention choice,
  and rollout summaries.
- `mechanics`: protect basic regression behavior.

`sim-v0` is the first named version of this level. Its source files live under
`benchmarks/sim-v0`, then compile into `.rsi/benchmarks/sim-v0` for the existing
runner. It keeps the local speed of synthetic environments while adding
benchmark-source metadata, family labels, split counts, and gate-ready
per-environment scores.

### Level C: External Benchmarks

External benchmarks should be adapters, not the first source of complexity.

- Terminal-Bench measures AI agents in terminal environments and includes tasks
  across software engineering, ML, security, data science, and more.
- SWE-bench measures patch generation for real GitHub issues with reproducible
  Docker evaluation.
- tau/tau3-bench measures tool-agent-user interaction for customer-service style
  domains such as airline, retail, telecom, and banking knowledge.

The first adapters should be read-only wrappers that convert external task
metadata into the local task/run/gate schema.

External adapters should not set new gate semantics. They should preserve the
same local split, trace, compare, and promotion contract used by `sim-v0`.

CM-0020 starts with metadata/schema parity only. A task row that comes from an
external benchmark can include:

```json
"external_adapter": {
  "name": "terminal-bench",
  "kind": "terminal",
  "external_id": "benchmark-task-id",
  "fixture_version": "snapshot-or-release-id",
  "source_url": "https://...",
  "mode": "read_only"
}
```

Allowed CM-0020 adapter kinds are `terminal`, `swe_patch`, and
`tool_agent_user`. These map to Terminal-Bench-style terminal tasks,
SWE-bench-style issue patching, and tau/tau3-style tool-agent-user workflows.
Live simulator/world-model adapters remain deferred; static world-model traces
stay in `sim-v0` until their own adapter contract is explicit.

`benchmark adapters --benchmark <name>` writes
`.rsi/benchmarks/<name>/adapter_report.json`. The report is provenance and
fixture evidence only. It records source benchmark counts, split counts, fixture
versions, source URLs, metadata failures, and a report digest. It does not run
Docker, terminals, customer-service simulators, or external benchmark harnesses,
and its digest is not promotion evidence.

CM-0021 adds frozen local importers for this same metadata contract:

```bash
harness-rsi benchmark import-adapters \
  --source frozen-export.json \
  --profile frozen-adapters-v0
```

The importer accepts local JSON/JSONL exports whose rows identify the adapter
name, external task ID, fixture version, split, instruction-like text, and a
deterministic local evaluator. It writes a normal source profile under
`benchmarks/<profile>/sources/{train,heldout,regression}` plus
`import_report.json`, `manifest.json`, and `gate_policy.json`.

The import report records source export identity, source digest, importer
version, split counts, adapter counts, fixture versions, and a digest over the
report. It is not a run, gate, score, or promotion artifact. The imported rows
only become measurement evidence after `benchmark init`, `benchmark run`,
heldout/regression gates, split-isolation audit, composite gate, and
promotion-time digest checks. Missing splits, duplicate external fixture IDs,
live/runner modes, unsupported adapter kinds, and missing deterministic evals
fail before a source profile is written.

CM-0022 makes larger imports reviewable without relaxing the promotion boundary.
`import_report.json` now separates accepted task rows from rejected source rows,
records rejection reason counts, accepted/rejected row digests, and split-map
review metadata. Strict mode still fails closed on any rejected row. When strict
mode fails, or when `--review-split-map` is used, the CLI writes a review-only
artifact under `benchmarks/_import_reviews/<profile>/import_review.json`; that
directory is not a materializable benchmark source profile. `--allow-rejected-rows`
can write a partial source profile only if accepted rows still cover train,
heldout, and regression.

CM-0023 adds the first tiny real frozen export smoke:
`benchmarks/_frozen_exports/swe-bench-lite-smoke-v0`. The committed export uses
three public SWE-bench Lite instance IDs and a split map that assigns them to
local train, heldout, and regression roles. The local evaluator checks fixture
identity only, so this is still adapter plumbing and provenance evidence, not
SWE-bench patch-grading evidence. The smoke path is:
`benchmark import-adapters` -> `benchmark init` -> `benchmark adapters` ->
one no-promote `experiment stability` cycle.

CM-0024 tightens directory JSONL import auditability. Rejected rows from a
directory source now preserve source-directory-relative `source_path` and
1-based `line_number` fields in review/import reports, while accepted task rows
never receive that importer-side provenance in the source profile. This is
provenance precision only; it does not alter run, gate, coverage,
composite-gate, or promotion semantics.

CM-0025 widens tiny real frozen-export coverage to Terminal-Bench and
tau2-bench retail task identities. Both fixtures follow the CM-0023 pattern:
three public source IDs, explicit local split maps, deterministic identity-only
evaluators, materialization, adapter reporting, and no-promote stability smoke.
They do not execute terminal tasks, launch Docker, run tau user simulators,
mutate tau databases, or add live external-runner evidence.

## Splits

Each benchmark environment has three splits:

- `train`: visible to the improvement loop; used for diagnosis and proposal.
- `heldout`: hidden from proposal generation; used for validation.
- `regression`: protected behavior that must not degrade.

Promotion must never use heldout traces as proposal input.

The split contract applies within each environment and failure family. For
example, a `tool_use` regression should not be moved into `train` merely because
it is useful proposal evidence; it should be copied or distilled into a train
probe while the protected regression case remains protected.

Proposal evidence is train-only. For the improvement step, `results.json`,
`trace.jsonl`, task IDs, run IDs, run paths, and model prompt context must come
from a train run. Heldout and regression artifacts may appear in gates,
composite decisions, rejection artifacts, and promoted lineage, but they must
not appear in proposal generation. The cycle writes a split-isolation audit that
records the proposal source run, embedded proposal evidence, train task IDs,
heldout/regression validation task IDs, recursive validation-reference scan
results, and a digest of that audit.

## Failure-Family Coverage Reporting

`sim-v0` task rows carry `environment` and `family` labels, and benchmark
materialization writes a first-class `coverage.json` report before those labels
become hard gate inputs.

The report is derived from the same source profile that
`harness-rsi benchmark init --name sim-v0` materializes into
`.rsi/benchmarks/sim-v0`. It shows an environment-by-family matrix for each
split, task counts, split counts, evaluator digests, and explicit missing cells.
A missing high-priority family is recorded as either:

- covered by at least one task in the split
- intentionally waived with reason, owner, tracking reference, review date, and
  optional expiry condition
- missing required evidence that blocks gates

This keeps coverage review separate from scoring. The current runner can execute
tasks, enforce per-environment policy, and emit coverage reports. It does not
turn every sparse cell into a failure. Only cells listed as required in the
coverage policy can fail a gate. Waived and unclassified missing cells remain
visible in `coverage.json` and gate artifacts without blocking promotion by
themselves. Waiver metadata is strict: missing `reason`, `owner`,
`tracking_ref`, or `review_by` rejects the suite policy, as do duplicate waiver
cells, unknown waiver keys, and required/waiver overlap.

CM-0013 promotes several `world_model_static` trace families into required
coverage: rollout summarization in train, reset/replay in heldout and
regression, and drift detection in regression. This changes local measurement
coverage, not the external benchmark adapter boundary.

The waiver lifecycle report is an alternate index over waiver metadata. It
groups waived cells by owner and review date, carries tracking and expiry
context, and preserves suite/coverage identity. It also reports whether fresh
coverage identity still matches the stored `coverage.json` digest. It is
separate from scoring by default. A split `gate_policy.json` can opt into
promotion-blocking overdue waiver review with an explicit `waiver_review_as_of`
date. That gate only blocks overdue active-missing waivers; due-soon waivers and
overdue retire candidates remain evidence for cleanup.

## Evaluator And Suite Digests

Current run summaries record `task_digest`, `evaluator_digests`, and
`harness_behavior_digest`.
`benchmark compare` rejects task-digest mismatches, and promotion rejects missing
or mismatched candidate behavior digests.

Source benchmark materialization also writes explicit identity fields so
reviewers can see what changed without reverse-engineering a task hash:

- `suite_digest`: canonical hash of the benchmark manifest, source task rows by
  split, and gate policy used to materialize the suite.
- `evaluator_digest`: canonical hash of deterministic evaluator definitions,
  attached to compiled task rows and carried into run/gate evidence.
- `suite_version`: human-readable suite version or profile ID, such as
  `sim-v0.1`.

These fields appear in run summaries, comparisons, gates, composite gates, cycle
summaries, rejected-cycle decision artifacts, and promoted harness lineage where
applicable. They do not replace `task_digest`; they make the same comparability
invariant easier to audit and eventually allow evaluator-only changes to be
reviewed as measurement changes.

## Promotion Gate

A candidate harness can be promoted only when evidence says it is better or at
least not worse under the configured policy.

Required checks:

- same model
- same benchmark and split
- same task IDs and order
- same evaluator definitions
- heldout score meets the threshold
- regression score does not drop beyond tolerance
- trace artifacts remain inspectable

The first implemented metric is pass rate. Efficiency metrics are now recorded
and can be gate-enforced when a split policy configures thresholds.

Current metric schema:

- `pass_rate`: primary score for gates.
- `per_environment`: pass rate, attempts, and tool calls by environment.
- `metrics.attempts`: total model attempts in a run.
- `metrics.tool_calls`: total accepted tool-call observations.
- `metrics.duration_ms`: measured wall-clock runtime for local execution.
- `metrics.cost_usd`: nullable placeholder until provider accounting is wired.

Gates carry `metric_deltas` and `environment_scores`. Environment scores can
become gating fields through `max_environment_drop` or a benchmark
`gate_policy.json`. Efficiency deltas can become gating fields through
`max_attempt_delta`, `max_tool_call_delta`, `max_duration_ms_delta`, and
`max_cost_usd_delta`.

Current gate policy can enforce:

- aggregate heldout improvement must meet the configured threshold
- aggregate regression drop must stay within tolerance
- each gate-enforced environment must meet its floor or max-drop policy
- protected environments can veto promotion even when aggregate score improves
- required failure-family coverage must be present or explicitly waived
- gate-time coverage digest must match the coverage digest recorded by the runs
- overdue active-missing waivers can fail gates when an explicit review policy
  is configured
- attempts and tool-call regressions can fail gates when configured
- duration and cost regressions can fail gates when explicitly configured

`sim-v0` currently enforces `max_attempt_delta: 0` and
`max_tool_call_delta: 0` for heldout and regression gates. It also enables
`fail_on_overdue_waivers` with `waiver_review_as_of: 2026-06-19`, so the suite
has a deterministic waiver-review boundary rather than a wall-clock-dependent
one. Duration remains unset by default because local wall-clock timing is noisy.
Cost remains unset because provider usage is not collected yet. If a split
policy configures a threshold for a metric whose value is unavailable, the gate
fails closed with `metric_unavailable`.

This prevents an aggregate win from masking a local failure in a protected
environment. It also prevents a candidate from being promoted against coverage
metadata that changed after the run evidence was produced.

Composite gates are the promotion boundary. A composite gate can only combine a
heldout gate and a regression gate for the same baseline harness, candidate
harness, candidate behavior digest, benchmark, model, suite version, suite
digest, coverage digest, current coverage digest, and coverage-policy digest. A
digest, coverage digest, current coverage digest, coverage-policy digest,
waiver-review policy, and waiver-review evidence. A composite `promote`
decision requires both component gates to promote. The composite artifact
records canonical child-gate digests so promotion can re-read the child gate
files and reject missing or mutated evidence. Composite gates also carry the
split-isolation audit digest; promotion rejects missing, failing, or mutated
split-isolation evidence, and re-runs the stored coverage and waiver-review
policy before mutating a candidate harness.

## Version-Aware Promotion

Benchmark promotion uses two phases. First a proposal creates a candidate
harness, then a promote gate promotes that existing candidate:

```text
.rsi/harnesses/H0.json
.rsi/harnesses/H1.json  # status: candidate

benchmark run --harness H1
benchmark gate ...

.rsi/harnesses/H1.json  # status: promoted
```

`H1` must record:

- parent harness ID
- source proposal
- source gate
- baseline and candidate run IDs
- benchmark and split
- observed pass-rate delta
- behavior digest evaluated by the gate

Promotion rejects:

- rejected gates
- single-split gates that are not composite heldout+regression decisions
- parent mismatch
- candidate ID mismatch
- existing version overwrite
- model changes inside `config_patch`
- missing or mismatched candidate behavior digests
- missing or mutated child gate evidence
- stale coverage digest evidence at promotion time
- missing, failing, or mutated split-isolation audit evidence

This keeps harness-level RSI legible: each new harness version is a reviewable
artifact with its own evidence trail.

## Automated Cycle

The automated cycle is the first end-to-end approximation of harness-level RSI:

```text
run parent on train
  -> propose patch from train trace
  -> create Hn+1 candidate
  -> run Hn and Hn+1 on heldout
  -> run Hn and Hn+1 on regression
  -> write heldout gate
  -> write regression gate
  -> write composite gate
  -> promote or reject Hn+1
```

The train run is only evidence for proposal generation. It is not a promotion
gate. Promotion consumes a composite decision that requires both heldout and
regression to pass.

Cycle summaries live under `.rsi/cycles/` so every artifact path is reviewable.
Rejected cycles also write first-class decision artifacts under
`.rsi/decisions/` with proposal, heldout gate, regression gate, composite gate,
score deltas, and metric deltas.

## Repeated Local Cycle Stability

One successful cycle is not enough evidence for external benchmark adapters.
Before adding Terminal-Bench, SWE-bench, tau-style tasks, or live world-model
adapters, the local harness should show that repeated `Hn -> Hn+1` attempts keep
the same measurement contract intact.

`experiment stability` runs multiple cycles and writes
`.rsi/cycles/stability-*.json`. The report summarizes:

- parent/candidate chain and whether the parent advanced after promotion
- heldout, regression, and composite decisions for every cycle
- split-isolation audit status and digest
- suite, coverage, coverage-policy, and waiver-review policy stability
- coverage, waiver-review, environment, efficiency, and split-isolation failure
  counts
- a digest over the stability report itself

This is the adapter-readiness check. External adapters should add task sources
and fixture metadata, not new promotion semantics. If local `sim-v0` cycles
cannot repeatedly promote or reject candidates with deterministic artifacts, a
public benchmark adapter will only make the failure harder to inspect.

## Frontier Model Interaction

Frontier models make the harness question sharper because the model may already
be very strong. That means useful harness improvement often appears as:

- lower cost for the same score
- fewer retries
- better failure recovery
- safer tool use
- better task triage
- better memory selection
- better state tracking across long tasks

The fixed-model rule still applies. A frontier-model run should pin the provider
model for both `Hn` and `Hn+1`; otherwise a promotion can confuse model
improvement with harness improvement. The current CLI supports explicit
`--model` arguments for model-backed runs and rejects benchmark comparisons when
the recorded models differ. Waiver review protects the complementary failure
mode: a stronger model can make aggregate scores look good while sparse local
coverage still hides harness failures.

For world-model use cases, the harness should not merely ask whether a model can
generate plausible next states. It should evaluate whether the surrounding
system preserves state consistency, detects drift, selects interventions, and
uses simulation traces to improve the next rollout.

## Use-Case Pressure Tests

### Knowledge Work

The harness should improve at extracting objectives, constraints, evidence
needs, and decision criteria from ambiguous human requests. This is where
personal Codex-message-derived tasks can become useful after sanitization.

### Coding

The harness should improve at failure diagnosis, patch targeting, test
selection, and regression awareness. Terminal-Bench and SWE-bench are the
external benchmark directions for this track.

### Customer Support

The harness should improve at policy following, tool sequencing, escalation, and
stateful customer interaction. tau/tau3-style simulations are the external
benchmark direction for this track.

### World Models

Decart/Etched's Oasis-style world-model work is interesting because the model is
not just answering text; it is rolling forward a simulated state from actions.
The harness question becomes: can the surrounding system evaluate state
consistency, detect incoherence, choose interventions, and improve rollout
policy without changing the underlying world model?

The current repo only models this with static text probes in
`world_model_static`. CM-0013 adds rollout-shaped static trace cases, while
still keeping the live simulator adapter out of scope until trace identity,
evaluator identity, coverage, waiver review, and gate digests are stable.

Initial synthetic probes:

- state consistency
- drift detection
- intervention selection
- rollout trace summarization
- environment reset/replay

## References

- [Terminal-Bench](https://www.tbench.ai/)
- [SWE-bench](https://www.swebench.com/SWE-bench/)
- [tau/tau3-bench](https://github.com/sierra-research/tau2-bench)
- [Wired on Decart/Etched Oasis](https://www.wired.com/story/first-entirely-ai-generated-video-game-weird-and-fun)
