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

## Split Contract

Each environment should keep three distinct splits:

- `train`: visible to the improvement loop; allowed as proposal evidence.
- `heldout`: hidden from proposal generation; used to validate the candidate.
- `regression`: protected behavior that must not degrade.

Promotion must never consume heldout or regression traces as proposal input. If a
task moves between splits, the change-management entry should record the reason,
the affected suite version, and the gates that need to be rerun.

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
- summary: missing split cells, total task count, suite digest, coverage digest,
  and evaluator digest coverage

CLI:

```bash
harness-rsi benchmark coverage --benchmark sim-v0
```

The command reads the materialized `.rsi/benchmarks/sim-v0` copy, writes
`coverage.json`, and reports missing environment/family split cells. The current
version is report-only; gate enforcement for missing required cells should come
after required cells and waivers are explicit.

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
- efficiency thresholds for attempts, tool calls, duration, and cost once those
  fields are reliable enough to gate on

Per-environment gating prevents an aggregate win from hiding a localized failure.
A candidate that improves `knowledge_work` should not be promoted if it breaks
`tool_use`, `world_model`, or another protected environment beyond policy.

Missing evidence should fail closed unless the change-management entry records
an explicit waiver and the reason that waiver is acceptable for the current
suite version.

## Frontier And World-Model Pressure

Frontier-model interaction should preserve the project invariant: fixed model,
changed harness. A stronger model does not reduce the need for harness evidence;
it changes where improvement is likely to show up:

- fewer retries or tool calls for the same score
- better recovery after a failed attempt
- safer tool sequencing under ambiguous instructions
- better memory and context selection
- better state tracking across longer traces

Decart/Oasis-style world-model use cases should start as trace-evaluation
problems, not live simulator integration. The current local proxy is
`world_model_static`, with families such as state consistency, drift detection,
impossible transitions, intervention selection, rollout summarization, and
reset/replay. A future adapter can ingest simulator traces, but it should still
produce local task rows, deterministic evaluator definitions, suite digests, and
the same promotion gate evidence as `sim-v0`.

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
- **Level 4: External adapter parity** checks that Terminal-Bench, SWE-bench, and
  tau/tau3-style adapters preserve the same local task, run, compare, and gate
  semantics.

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
suite/evaluator/coverage identity propagation.

The next increment should target:

1. Decide which coverage cells are required, waived, or report-only before
   making missing coverage fail gates.
2. Add explicit waiver files or manifest fields for intentionally missing
   family/split cells.
3. Expand `world_model_static` toward Decart-style rollout trace cases while
   keeping the adapter local and deterministic.
4. Add digest mismatch tests at the composite-gate and promotion boundary.
5. Only then add read-only external adapters for Terminal-Bench, SWE-bench, and
   tau/tau3-style tasks.
