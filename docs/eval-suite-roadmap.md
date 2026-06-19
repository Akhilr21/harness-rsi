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

Rejected candidates should update the matrix. The point is not only to improve
the next prompt; it is to make the next evaluation harder in the exact place the
candidate failed.

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
- evaluator changes and any digest changes
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

1. Add a `sim-v0` manifest with suite version, environments, families, and split
   counts.
2. Add task metadata for source, failure family, and evaluator digest.
3. Promote `per_environment` from evidence output into configurable gate policy.
4. Add a failure-family coverage report and fail-closed behavior for missing
   required cells.
5. Add policy tests that prove aggregate wins cannot mask environment-specific
   regressions.
6. Only then add read-only external adapters for Terminal-Bench, SWE-bench, and
   tau/tau3-style tasks.
