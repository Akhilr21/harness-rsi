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
counts, duration, and nullable cost placeholders. Gate policy can enforce
attempt and tool-call deltas today; duration and cost thresholds are explicit
opt-in because duration is noisy locally and provider cost is not collected yet.
Rejected cycles write a decision artifact under `.rsi/decisions/` with proposal,
gate, score-delta, and metric-delta evidence.

Repeated local stability runs chain the same cycle before external adapters are
added:

```bash
harness-rsi experiment stability \
  --parent H0 \
  --candidate-prefix H \
  --cycles 3 \
  --benchmark sim-v0 \
  --mock
```

This writes `.rsi/cycles/stability-*.json` with every child cycle, component
gate, composite gate, split-isolation audit, waiver-review summary, efficiency
summary, rollup, and stability digest. With promotion enabled, the parent
advances only after a candidate promotes, so a clean three-cycle run proves an
`H0 -> H1 -> H2 -> H3` chain under the current local gate contract.

External adapter work starts as read-only metadata, not as full benchmark
runners:

```bash
harness-rsi benchmark init --name external-adapter-smoke-v0
harness-rsi benchmark adapters --benchmark external-adapter-smoke-v0
```

The adapter report writes `.rsi/benchmarks/<name>/adapter_report.json` and
checks that Terminal-Bench, SWE-bench, and tau-style task rows preserve source
IDs, fixture versions, source URLs, local split mapping, evaluator digests, and
`mode: read_only` without changing gate policy or promotion semantics.

Frozen local exports can also be compiled into a source profile before
materialization:

```bash
harness-rsi benchmark import-adapters \
  --source /path/to/frozen-export.json \
  --profile frozen-adapters-v0
harness-rsi benchmark init --name frozen-adapters-v0
harness-rsi benchmark adapters --benchmark frozen-adapters-v0
```

The importer writes `benchmarks/<profile>/import_report.json`, source rows under
`benchmarks/<profile>/sources/`, and strict local gate/coverage policy defaults.
It is still read-only fixture plumbing: no terminal execution, Docker grading,
tau simulator, run artifact, gate artifact, or promotion decision is created by
the importer itself.

Larger frozen exports can be reviewed before materialization:

```bash
harness-rsi benchmark import-adapters \
  --source /path/to/frozen-export.json \
  --profile frozen-adapters-v0 \
  --split-map /path/to/split-map.json \
  --review-split-map
```

Strict import remains the default. Rejected rows block profile creation unless
`--allow-rejected-rows` is explicit, and strict failures write a review-only
artifact under `benchmarks/_import_reviews/<profile>/import_review.json`.
When the source is a directory of JSONL files, rejected-row records preserve the
source-directory-relative file path and 1-based line number, so larger imports
can be reviewed as `path/to/file.jsonl:line` without leaking absolute local
paths into artifacts.

A tiny committed SWE-bench Lite fixture exercises the same path with real public
benchmark identities:

```bash
harness-rsi benchmark import-adapters \
  --source benchmarks/_frozen_exports/swe-bench-lite-smoke-v0/tasks.json \
  --profile swe-bench-lite-smoke-v0 \
  --split-map benchmarks/_frozen_exports/swe-bench-lite-smoke-v0/split-map.json
harness-rsi benchmark init --name swe-bench-lite-smoke-v0
harness-rsi benchmark adapters --benchmark swe-bench-lite-smoke-v0
harness-rsi experiment stability \
  --parent H0 \
  --candidate-prefix DryRun \
  --first-candidate-index 1 \
  --cycles 1 \
  --benchmark swe-bench-lite-smoke-v0 \
  --mock \
  --no-promote
```

This smoke fixture is identity-only. It preserves SWE-bench Lite instance IDs,
source URLs, local split mapping, fixture versions, evaluator digests, and
read-only adapter metadata. It does not clone repositories, run Docker, generate
patches, or claim SWE-bench score evidence.

The same identity-only smoke pattern is available for Terminal-Bench and
tau2-bench retail fixtures:

```bash
harness-rsi benchmark import-adapters \
  --source benchmarks/_frozen_exports/terminal-bench-smoke-v0/tasks.json \
  --profile terminal-bench-smoke-v0 \
  --split-map benchmarks/_frozen_exports/terminal-bench-smoke-v0/split-map.json
harness-rsi benchmark init --name terminal-bench-smoke-v0
harness-rsi benchmark adapters --benchmark terminal-bench-smoke-v0
harness-rsi experiment stability \
  --parent H0 \
  --candidate-prefix DryRunTerminal \
  --first-candidate-index 1 \
  --cycles 1 \
  --benchmark terminal-bench-smoke-v0 \
  --mock \
  --no-promote

harness-rsi benchmark import-adapters \
  --source benchmarks/_frozen_exports/tau2-bench-retail-smoke-v0/tasks.json \
  --profile tau2-bench-retail-smoke-v0 \
  --split-map benchmarks/_frozen_exports/tau2-bench-retail-smoke-v0/split-map.json
harness-rsi benchmark init --name tau2-bench-retail-smoke-v0
harness-rsi benchmark adapters --benchmark tau2-bench-retail-smoke-v0
harness-rsi experiment stability \
  --parent H0 \
  --candidate-prefix DryRunTau \
  --first-candidate-index 1 \
  --cycles 1 \
  --benchmark tau2-bench-retail-smoke-v0 \
  --mock \
  --no-promote
```

These fixtures preserve public task identities and adapter metadata only. They
do not execute Terminal-Bench tasks, run Docker, launch tau user simulators,
mutate tau databases, or claim benchmark scores.

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

Gates now support aggregate pass-rate thresholds, regression-drop tolerance,
per-environment maximum drops, required coverage, split-isolation evidence, and
efficiency thresholds. `sim-v0` enforces no additional attempts or tool calls
for heldout/regression gates, while duration and cost remain unset by default.
It also pins waiver review to `2026-06-19` and rejects overdue active-missing
waivers when that split policy is enabled.

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
without blocking promotion by themselves unless the split policy explicitly
enables overdue-waiver review.
Waived cells carry owner, tracking reference, review date, and expiry-condition
metadata so intentionally missing evidence stays reviewable.
Promotion now requires a composite heldout+regression gate. Composite gates fail
closed when child gates mix split roles, benchmarks, models, suite digests,
coverage digests, coverage-policy digests, waiver-review evidence, or candidate
behavior digests, and promotion rechecks child gate digests before mutating a
candidate harness.
The coverage command prints a concise summary and writes the full
environment/family/split matrix to `.rsi/benchmarks/<name>/coverage.json`.
The waiver lifecycle command writes
`.rsi/benchmarks/<name>/waiver_lifecycle.json`, groups active waived cells by
owner and review date, and compares fresh coverage identity to the stored
`coverage.json` digest. A gate policy can reuse the same lifecycle evidence to
block overdue active-missing waivers with an explicit review date.

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
coverage-policy drift between run time and gate time, plus overdue waiver debt
when the split policy enables that review gate.

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
