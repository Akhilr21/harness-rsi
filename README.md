# harness-rsi

A minimal CLI lab for measuring harness-level improvement with a fixed model.

The first goal is deliberately small: run a model through versioned harness
configs, capture traces, evaluate outputs, ask for a harness patch proposal, and
explicitly promote or reject the candidate.

```text
task input -> prompt/program -> model -> trace -> eval -> proposal -> promote/reject
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Development workflow

Use PRs for changes going forward. Keep `main` as the stable branch, do active
work on `dev` or short-lived feature branches, and merge only after review.

## Quickstart

Initialize local harness artifacts:

```bash
harness-rsi init
```

Run the sample tasks without calling an API:

```bash
harness-rsi run --mock
```

Ask the model to propose a harness improvement from the latest run:

```bash
harness-rsi improve --mock
```

Promote or reject the proposal:

```bash
harness-rsi promote .rsi/proposals/<proposal-id>.json
harness-rsi reject .rsi/proposals/<proposal-id>.json --reason "overfit to toy task"
```

## Benchmark quickstart

Create the first synthetic benchmark environment and baseline harness:

```bash
harness-rsi benchmark init
```

Create a candidate `H1` from a proposal, then run `H0` and `H1` on heldout:

```bash
harness-rsi harness create-candidate \
  --parent H0 \
  --candidate H1 \
  --proposal .rsi/proposals/<proposal-id>.json

harness-rsi benchmark run --split heldout --harness H0 --mock
harness-rsi benchmark run --split heldout --harness H1 --mock
```

Compare and gate the runs:

```bash
harness-rsi benchmark compare \
  --baseline-run .rsi/runs/<h0-run> \
  --candidate-run .rsi/runs/<h1-run>

harness-rsi benchmark gate \
  --baseline-run .rsi/runs/<h0-run> \
  --candidate-run .rsi/runs/<h1-run> \
  --min-pass-rate-delta 0.01 \
  --max-allowed-drop 0
```

The benchmark layer enforces fixed-model comparison, matching task order, and
matching task/evaluator definitions.

The richer local simulation suite is source-controlled under `benchmarks/sim-v0`
and materializes into `.rsi/benchmarks/sim-v0`:

```bash
harness-rsi benchmark init --name sim-v0
harness-rsi benchmark run --benchmark sim-v0 --split heldout --harness H0 --mock
```

`sim-v0` currently covers knowledge work, coding microtasks, data operations,
customer support, static Decart/Oasis-style rollout trace cases under
`world_model_static`, and regression mechanics. These are local deterministic
fixtures. Its gate policy can reject a candidate when an aggregate score is flat
or improved but a protected environment regresses.

Promote the existing candidate only after a promote gate:

```bash
harness-rsi harness promote \
  --candidate H1 \
  --gate .rsi/gates/<gate-id>.json
```

This mutates `.rsi/harnesses/H1.json` from `status: candidate` to
`status: promoted` and records lineage back to the parent, proposal, gate,
benchmark split, and run evidence. Promotion refuses rejected gates,
parent/candidate mismatches, missing or mismatched behavior digests, existing
promotions, and model changes.

## Experiment cycle

The full local loop can be run as one command:

```bash
harness-rsi experiment cycle \
  --parent H0 \
  --candidate H1 \
  --benchmark synthetic \
  --mock
```

The cycle runs parent training evidence, proposes a patch, creates the candidate,
runs parent/candidate heldout and regression splits, writes separate gates,
writes a composite gate, and promotes the candidate only when both heldout and
regression gates pass.

Runs and gates also record per-environment scores, attempt counts, tool-call
counts, duration, and nullable cost placeholders. Rejected cycles write a
decision artifact under `.rsi/decisions/` with proposal, gate, score-delta, and
metric-delta evidence.

## Enhanced Eval Suite

`sim-v0` is the first named eval-suite layer above the starter synthetic
benchmark. It is local, deterministic, and cheap enough to run during harness
iterations.

The committed suite starts with hand-authored probes and regression seeds,
including static rollout-trace cases for world-model pressure. The roadmap is to
add sanitized real traces and public benchmark miniatures next. Each task
records its environment, family, split, and deterministic evaluator.

The split contract stays strict:

- `train` is visible to proposal generation.
- `heldout` validates the candidate and must not leak into proposals.
- `regression` protects behavior that previous candidates or reviews already
  taught us to care about.

Proposal generation now rejects heldout/regression source runs. Experiment
cycles also write `.rsi/cycles/<cycle-id>-split-isolation.json`, which records
the train source run, proposal evidence task IDs, validation task IDs, leaked
validation-reference scan results, and a split-isolation digest. Composite gates
carry that audit digest, and promotion requires a passing, untampered audit.

Gates now support aggregate pass-rate thresholds, regression-drop tolerance, and
per-environment maximum drops. The roadmap is to add failure-family coverage and
eventually efficiency thresholds for attempts, tool calls, duration, and cost.

The reporting and identity layer is also part of the harness now. `sim-v0`
materialization writes `coverage.json`, and the report can be regenerated with:

```bash
harness-rsi benchmark coverage --benchmark sim-v0
harness-rsi benchmark waivers --benchmark sim-v0
```

Compiled task rows carry evaluator digests, run metadata carries suite and
coverage digests, and compare/gate/cycle evidence preserves those identities.
`sim-v0` also defines required and waived coverage cells. Missing required cells
fail gates; waived and unclassified missing cells remain visible in artifacts
without blocking promotion by themselves.
Waived cells carry owner, tracking reference, review date, and expiry-condition
metadata so intentionally missing evidence stays reviewable.
Promotion now requires a composite heldout+regression gate. Composite gates fail
closed when child gates mix split roles, benchmarks, models, suite digests,
coverage digests, coverage-policy digests, or candidate behavior digests, and
promotion rechecks child gate digests before mutating a candidate harness.
The coverage command prints a concise summary and writes the full
environment/family/split matrix to `.rsi/benchmarks/<name>/coverage.json`.
The waiver lifecycle command writes
`.rsi/benchmarks/<name>/waiver_lifecycle.json`, groups active waived cells by
owner and review date, and compares fresh coverage identity to the stored
`coverage.json` digest without changing promotion semantics.

See `docs/eval-suite-roadmap.md` for the full roadmap and change-management
expectations.

## Real model runs

Set an API key and omit `--mock`:

```bash
export OPENAI_API_KEY=...
harness-rsi run --model gpt-5.5
harness-rsi improve --model gpt-5.5
```

`gpt-5.5` is the default model in the starter config, but every command keeps it
overrideable so experiments can pin a model explicitly.

Frontier-model experiments should keep the same fixed-model contract as mock and
local runs: compare `Hn` and `Hn+1` with the same model, then look for harness
improvements in recovery, state tracking, tool use, triage, retries, and cost.
The current Decart-style world-model coverage is represented by static
`world_model_static` tasks in `sim-v0`; live simulator or external world-model
adapters should wait until suite/evaluator digests and coverage reporting are in
place and stable. No live simulator, external world-model adapter, or
Decart/Oasis runtime validation has been exercised yet. Gates also reject
coverage-policy drift between run time and gate time.

## Artifact layout

`harness-rsi init` creates the starter harness, sample task file, and memory
directory. `harness-rsi benchmark init` adds versioned benchmark artifacts such
as `H0` and benchmark splits:

```text
.rsi/
  harness.json          # model, prompt, tools, retry policy
  harnesses/H0.json     # versioned baseline harness
  benchmarks/synthetic/ # train, heldout, regression splits
  tasks/sample.jsonl    # small task input suite
  memory/learnings.md   # promoted learnings the harness reads
  runs/                 # trace + eval artifacts
  proposals/            # candidate harness patches
  decisions/            # promotion/rejection records
  gates/                # benchmark promotion gate decisions
  cycles/               # end-to-end cycle summaries
```

## What each piece means

- **Task input**: JSONL tasks with `id`, `instruction`, and `eval`.
- **Tool access**: explicit config for shell availability and allowed commands.
- **Prompt/program**: the harness system prompt in `.rsi/harness.json`.
- **Memory/learnings**: promoted notes in `.rsi/memory/learnings.md`.
- **Retry policy**: `max_retries` in `.rsi/harness.json`.
- **Trace capture**: each attempt is written to `.rsi/runs/<run-id>/trace.jsonl`.
- **Evaluation**: simple deterministic checks in task `eval`.
- **Patch proposal**: `improve` writes a candidate JSON file.
- **Promotion/rejection**: `promote` appends accepted changes; `reject` records why.

This is not an agent framework. It is the smallest useful experiment engine for
the question: with the model fixed, can the harness improve?

## Tool calls

The raw tool protocol is intentionally primitive. If shell access is enabled in
`.rsi/harness.json`, the model may return:

```json
{"tool":{"name":"shell","command":"python --version"}}
```

The harness checks `tools.shell`, `tools.allowed_commands`, and
`tools.timeout_seconds`, writes the observation to the trace, and gives the
observation back to the model on the next attempt.

## Design docs

- `docs/evaluation-architecture.md`
- `docs/eval-suite-roadmap.md`
- `docs/change-management.md`
