# Enhanced Eval-Suite Roadmap

`sim-v0` is the next eval-suite layer above the current synthetic benchmark. It
should stay local, deterministic, cheap to run, and easy to inspect. Its job is
to prove harness-level improvement with a fixed model before the project spends
complexity on external benchmark adapters.

The suite is not meant to be a bigger agent framework. It is a richer measurement
surface for the same loop:

```text
train evidence -> candidate harness -> heldout gate + regression gate -> promote/reject
```

## Goals

- measure harness deltas, not model deltas
- separate proposal evidence from validation evidence
- cover multiple environments and recurring failure families
- make gate decisions explicit, reproducible, and reviewable
- preserve rejected candidates as useful future evaluation material
- keep benchmark sources traceable back to their origin and suite version

## Sim-v0 Benchmark Sources

`sim-v0` starts with committed hand-authored probes and regression seeds. It
should grow toward four source classes:

- **Hand-authored probes**: small tasks that exercise known harness surfaces such
  as instruction parsing, tool use, state tracking, retry behavior, and evaluator
  mechanics.
- **Static rollout trace cases**: deterministic world-model-style traces that
  exercise state consistency, drift detection, intervention choice, reset/replay,
  and rollout summaries without ingesting a live simulator runtime.
- **Sanitized real traces**: distilled tasks from Codex-style work traces,
  local CLI failures, customer-support style interactions, and world-model
  rollouts, with secrets and private details removed before inclusion.
- **Public benchmark miniatures**: adapter-shaped local tasks inspired by
  Terminal-Bench, SWE-bench, and tau/tau3-bench, used before wiring full external
  benchmark runners.
- **Regression seeds**: failures discovered by rejected candidates, escaped
  regressions, brittle evaluators, or manual review. Once a failure teaches the
  harness something, it should become a protected task or family.

Every task should carry enough metadata to explain why it exists:

- `environment`
- `split`
- `family`
- `source` when the task is derived from traces or external benchmarks
- `suite_version` once suite versioning is introduced
- `evaluator_digest` once evaluator definitions move beyond inline JSON
- fixture or seed version when relevant

No task should enter `sim-v0` if its source cannot be explained or replayed.
CM-0009 already gives `sim-v0` a committed manifest, source rows, split
materialization, family labels, and a gate policy. The next increment should make
those identities visible in reports and artifacts rather than adding a second
runner.
CM-0013 expands the local source data with static rollout trace cases only; live
rollout ingestion remains a future adapter problem.

## Split Contract

Each environment should keep three distinct splits:

- `train`: visible to the improvement loop; allowed as proposal evidence.
- `heldout`: hidden from proposal generation; used to validate the candidate.
- `regression`: protected behavior that must not degrade.

Promotion must never consume heldout or regression traces as proposal input. If a
task moves between splits, the change-management entry should record the reason,
the affected suite version, and the gates that need to be rerun.

CM-0016 makes this an audited information-flow invariant. Proposal generation
rejects validation split runs, writes a normalized evidence manifest, and cycle
summaries point to a split-isolation audit that recursively scans proposals for
heldout/regression task IDs, run IDs, trace paths, run paths, and gate paths.
Composite gates carry the audit digest, and promotion requires the audit to be
present, passing, and untampered.

The split contract is more important than the exact task count early on. A small
suite with clean separation is better evidence than a larger suite that leaks
validation examples into proposal generation.

## Failure-Family Coverage

`sim-v0` should track recurring failure modes separately from environments. The
initial family taxonomy can be small:

- `instruction_ambiguity`
- `incomplete_context`
- `tool_permission`
- `tool_sequence`
- `evaluator_mismatch`
- `state_drift`
- `regression_lock`
- `efficiency_regression`

Coverage should be reported as an environment-by-family matrix for each split.
Before an environment becomes gate-enforced, its high-priority families should
have at least one train task, one heldout task, and one regression task or a
documented waiver.

Implemented report shape:

- rows: environments such as `knowledge_work`, `coding_micro`, `data_ops`,
  `customer_support`, `world_model_static`, and `mechanics`
- columns: failure families seen in the selected suite profile
- cells: task count by split for each environment/family pair
- summary: required cells, waived cells, missing required cells, unclassified
  missing cells, total task count, suite digest, coverage digest, and evaluator
  digest coverage
- waiver lifecycle: waived cells indexed by owner, review date, tracking
  reference, expiry condition, and environment/family/split identity

CLI:

```bash
harness-rsi benchmark coverage --benchmark sim-v0
harness-rsi benchmark waivers --benchmark sim-v0
```

The command reads the materialized `.rsi/benchmarks/sim-v0` copy, writes
`coverage.json`, and prints a concise summary of required, waived, and
unclassified missing environment/family/split cells. The full sparse matrix
stays in the JSON artifact so review stays possible without flooding every CLI
run. Gates fail when required cells are missing and `fail_on_missing_required`
is enabled. Waived and unclassified missing cells are audit evidence by default.
Waived cells can also become gate evidence when a split policy enables overdue
waiver review, or they can be promoted to required coverage in a later suite
version.

Waivers are now typed measurement debt. Each waiver must include a non-empty
`reason`, `owner`, `tracking_ref`, and `review_by` date in `YYYY-MM-DD` format,
with optional `expires_when` text for the condition that should retire the
waiver. Duplicate waiver identities, unknown waiver keys, and required/waiver
overlap are rejected as malformed suite policy.
The waiver lifecycle command writes `waiver_lifecycle.json` as an alternate
index over the same metadata, grouped by owner and review date. It also compares
fresh coverage identity to the stored `coverage.json` digest so stale coverage
artifacts are visible. It is audit/query evidence by default. Split
`gate_policy.json` can opt into overdue-waiver promotion semantics with an
explicit review date, but `due_soon` waivers and retire candidates remain
non-blocking evidence.

CM-0013 adds required `world_model_static` coverage for
`rollout_summarization`, heldout and regression `reset_replay`, and regression
`drift_detection`. These cells are intentionally required now because they are
cheap deterministic traces and are central to later world-model adapter claims.

Rejected candidates should update the matrix. The point is not only to improve
the next prompt; it is to make the next evaluation harder in the exact place the
candidate failed.

## Evaluator And Suite Digests

The current runner records `task_digest` and `harness_behavior_digest`. That is
enough to reject incompatible comparisons, but it hides whether a change came
from task instructions, evaluator definitions, manifest metadata, or gate policy.

The implemented identity layer adds:

- `suite_digest`: canonical hash of manifest metadata, source task rows, split
  membership, and gate policy
- `evaluator_digest`: canonical hash of deterministic evaluator definitions
- `suite_version`: the named profile version, starting with `sim-v0.1`

Digest fields are written into run summaries, comparisons, gates, composite
gates, cycle summaries, rejected decision artifacts, promoted harness lineage,
and coverage reports. They should also appear in change-management entries
whenever task data, evaluator semantics, or gate policy changes. This makes
evaluator/suite edits reviewable measurement changes instead of quiet fixture
churn.

## Gate Policy

The current gate records aggregate pass-rate evidence and per-environment
scores. The roadmap is to make the composite gate enforce a policy with these
layers:

- same fixed model, benchmark, split, task IDs, task order, and evaluator
  definitions
- global heldout improvement above the configured threshold
- global regression drop within the configured tolerance
- per-environment floors or maximum allowed drops
- protected-environment vetoes for safety, tool access, and regression-lock
  behavior
- failure-family coverage minimums for environments that are gate-enforced
- coverage digest consistency between run time and gate time
- efficiency thresholds for attempts, tool calls, duration, and cost when those
  fields are configured and reliable enough to gate on

Per-environment gating prevents an aggregate win from hiding a localized failure.
A candidate that improves `knowledge_work` should not be promoted if it breaks
`tool_use`, `world_model`, or another protected environment beyond policy.

Missing required evidence fails closed. Waived cells are copied into reports and
gate artifacts with reason, owner, tracking reference, review date, and expiry
condition metadata. Unclassified missing cells remain visible as backlog
pressure for future suite versions. If coverage policy changes after benchmark
runs are produced, the gate rejects with `coverage_digest_mismatch` instead of
mixing stale run evidence with fresh waiver metadata.
Waiver lifecycle reports do not add promotion semantics by themselves; they make
measurement debt easier to query before a later gate policy decides whether any
overdue waiver should block promotion.

CM-0015 hardens the composite-gate boundary. Run comparison now rejects
baseline/candidate coverage-digest mismatch, composite gates reject mixed split
roles, benchmarks, models, suite identities, coverage identities, coverage-policy
identities, and candidate behavior digests, and promotion requires a composite
heldout+regression gate with untampered child gate digests. This is a gate
semantic change: old single-split promote gates are no longer sufficient
promotion evidence.
CM-0017 adds efficiency gates. `sim-v0` enforces no additional attempts and no
additional tool calls for heldout/regression gates. Duration and cost thresholds
remain explicit opt-in because local duration is noisy and provider cost is not
collected yet; if configured while unavailable, they fail closed.

## Frontier And World-Model Pressure

Frontier-model interaction should preserve the project invariant: fixed model,
changed harness. A stronger model does not reduce the need for harness evidence;
it changes where improvement is likely to show up:

- fewer retries or tool calls for the same score
- better recovery after a failed attempt
- safer tool sequencing under ambiguous instructions
- better memory and context selection
- better state tracking across longer traces

Decart/Oasis-style world-model use cases now start as static trace-evaluation
problems, not live simulator integration. The current local proxy is
`world_model_static`, with families such as state consistency, drift detection,
impossible transitions, intervention selection, rollout summarization, and
reset/replay. A future adapter can ingest simulator traces, but it should still
produce local task rows, deterministic evaluator definitions, suite digests, and
the same promotion gate evidence as `sim-v0`. Waiver metadata is especially
important here because plausible frontier-model rollouts can hide missing
coverage for rare but important state failures.

## Testing Levels

The eval suite needs its own test pyramid because evaluation infrastructure is a
harness component.

- **Level 0: Schema and fixture contracts** verify task metadata, split names,
  evaluator digests, suite versions, and source annotations.
- **Level 1: Runtime mechanics** verify init, run, compare, gate, candidate
  creation, promotion, rejection, and trace capture.
- **Level 2: Sim-v0 smoke cycles** run a fixed-seed train to heldout to
  regression cycle and assert that every artifact path is written.
- **Level 3: Policy tests** intentionally fail model matching, task ordering,
  per-environment thresholds, failure-family coverage, and regression tolerances.
- **Level 4: External adapter metadata parity** checks that Terminal-Bench,
  SWE-bench, and tau/tau3-style task sources preserve source IDs, fixture
  versions, source URLs, split mapping, evaluator identity, and read-only mode
  before any external runner is wired in.
- **Level 5: Tiny real frozen-export smoke** imports one public benchmark-family
  fixture, materializes it, writes the read-only adapter report, and runs a
  no-promote stability cycle without adding live external runners.

External adapters should wait until Levels 0 through 3 are boring and stable.

## Change-Management Expectations

Eval-suite changes should be reviewable as product changes, not treated as
miscellaneous test data churn. Each meaningful suite change should record:

- source and rationale for new or changed tasks
- affected environments, failure families, and splits
- coverage-report changes and any suite/evaluator digest changes
- gate-policy changes and expected promotion impact
- validation commands and artifact paths
- migration or backfill plan for prior runs when old evidence is no longer
  comparable

Task data, evaluator definitions, and gate semantics should be versioned together.
A candidate should always gate against a named suite version. Once a candidate
run exists, the tasks and evaluator definitions used by that run should not be
edited in place.

PRs that change the eval suite should say whether they alter measurement only,
gate semantics, or both. Gate-semantic changes require extra scrutiny because
they can make the same candidate appear promoted or rejected without changing
the harness.

## Near-Term Milestones

CM-0009 completed the first foundation: committed `sim-v0` sources, benchmark
profile materialization, split metadata, per-environment scores, and
`gate_policy.json` enforcement. CM-0010 added coverage reporting plus
suite/evaluator/coverage identity propagation. CM-0011 added required and
waived coverage cells and gate enforcement for missing required coverage.
CM-0012 added strict waiver metadata and coverage-digest drift rejection.
CM-0013 added static Decart/Oasis-style rollout trace cases and promoted key
world-model trace families into required coverage.
CM-0014 added a waiver lifecycle report grouped by owner and review date without
changing promotion semantics.
CM-0015 added composite-gate and promotion-boundary digest checks.
CM-0016 added train-only proposal evidence manifests and split-isolation audit
gates.
CM-0017 added attempts/tool-call efficiency gates and opt-in duration/cost
thresholds.
CM-0018 added deterministic overdue-waiver review gates for active missing
coverage debt.
CM-0019 added repeated local-cycle stability reports that run the full current
gate contract across promoted or dry-run candidate chains.
CM-0020 added read-only external adapter metadata reports and an
`external-adapter-smoke-v0` profile for Terminal-Bench, SWE-bench, and
tau-style task shapes.
CM-0021 added read-only importers from frozen local external-adapter exports into
the CM-0020 metadata contract.
CM-0022 added rejected-row reporting and split-map review artifacts for larger
frozen imports without changing promotion semantics.
CM-0023 added `swe-bench-lite-smoke-v0`, a tiny public SWE-bench Lite frozen
export that runs through import, materialization, adapter report, and no-promote
stability smoke with identity-only local evaluators.
CM-0024 added source-directory-relative file and 1-based line preservation for
rejected rows from directory JSONL imports.
CM-0025 added tiny public Terminal-Bench and tau2-bench retail frozen exports
that run through import, materialization, adapter report, and no-promote
stability smoke with identity-only local evaluators.
CM-0026 added a read-only import-audit query command for existing
`import_report.json` and review-only `import_review.json` artifacts.

The next increment should target:

1. Keep live Terminal-Bench execution and tau simulators behind explicit runner
   contracts, source identity, cost/tool tracking, and gate-policy review.
2. Keep live simulator or world-model adapters behind stable local trace
   coverage, waiver review, and digest-boundary tests.
3. Add sanitized real traces only when their source, fixture version, and split
   contract can be replayed.
