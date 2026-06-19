# Evaluation Architecture

`harness-rsi` studies harness-level improvement:

```text
fixed model M + harness Hn -> score
fixed model M + harness Hn+1 -> score
```

The model, task split, evaluator, and budget should stay fixed while the harness
changes. A candidate harness earns promotion only through evidence, not because a
prompt sounds better.

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
- `world_model`: test state consistency in simulated environments.
- `mechanics`: protect basic regression behavior.

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

## Splits

Each benchmark environment has three splits:

- `train`: visible to the improvement loop; used for diagnosis and proposal.
- `heldout`: hidden from proposal generation; used for validation.
- `regression`: protected behavior that must not degrade.

Promotion must never use heldout traces as proposal input.

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
