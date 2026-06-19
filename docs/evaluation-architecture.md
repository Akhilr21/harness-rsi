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
- `world_model_static`: test state consistency in simulated environments.
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

The first implemented metric is pass rate. Later metrics should include cost,
latency, retries, tool errors, failure-family coverage, and per-environment
performance.

Current metric schema:

- `pass_rate`: primary score for gates.
- `per_environment`: pass rate, attempts, and tool calls by environment.
- `metrics.attempts`: total model attempts in a run.
- `metrics.tool_calls`: total accepted tool-call observations.
- `metrics.duration_ms`: measured wall-clock runtime for local execution.
- `metrics.cost_usd`: nullable placeholder until provider accounting is wired.

Gates carry `metric_deltas` and `environment_scores`. Metric deltas are evidence
fields for now. Environment scores can also become gating fields through
`max_environment_drop` or a benchmark `gate_policy.json`.

Current gate policy can enforce:

- aggregate heldout improvement must meet the configured threshold
- aggregate regression drop must stay within tolerance
- each gate-enforced environment must meet its floor or max-drop policy
- protected environments can veto promotion even when aggregate score improves

Roadmap policy should add:

- required failure-family coverage must be present or explicitly waived
- efficiency thresholds can gate attempts, tool calls, duration, and cost once
  those measurements are reliable enough

This prevents an aggregate win from masking a local failure in a protected
environment.

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
- parent mismatch
- candidate ID mismatch
- existing version overwrite
- model changes inside `config_patch`
- missing or mismatched candidate behavior digests

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
